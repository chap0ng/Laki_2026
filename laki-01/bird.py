"""
Whistle -> stylized bird, call-and-response engine.

Pipeline (all offline, one whistled phrase at a time):
    mic -> record-until-silence -> analyze (pitch + loudness) -> restyle -> play

Pitch tracking is a small pure-numpy YIN implementation, so the only
dependencies are numpy + sounddevice (+ soundfile, optional, for --save).
Runs unchanged on a Raspberry Pi.

Usage:
    .venv/bin/python bird.py                  # live: whistle, it replies
    .venv/bin/python bird.py --birdiness 0.3  # more human (0.0) .. more bird (1.0)
    .venv/bin/python bird.py --file in.wav    # process a wav instead of the mic
    .venv/bin/python bird.py --save replies   # write each reply to replies/NNN.wav
"""

import argparse
import os
import signal
import sys
import time
import numpy as np
from scipy import signal as sps

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SR = 44100          # sample rate
HOP = 256           # analysis hop (samples) -> ~5.8 ms time resolution
FRAME = 2048        # analysis frame (samples)
FMIN = 300.0        # lowest whistle pitch we look for (Hz)
HUM_FMIN = 80.0     # lowest hummed pitch we look for (--hum mode)
FMAX = 4000.0       # highest whistle pitch we look for (Hz)
WHISTLE_REGISTER = 1200.0  # hum mode aims the reply's median pitch here (Hz)

# LAKI_SHIFT_OFFSET - semitones added on top of whatever shift is already in
# force: the explicit --shift value, or the automatic whistle-register shift
# when --shift is absent. It is the only way to say "a semitone above the bird
# that runs on auto", because passing --shift a number switches auto off.
# Unset = 0.0 = no change at all.
SHIFT_OFFSET = float(os.environ.get("LAKI_SHIFT_OFFSET") or 0.0)
YIN_THRESHOLD = 0.15  # YIN voicing threshold (lower = stricter)

# Recording state machine
SILENCE_HOLD = 0.70   # seconds of silence that ends a phrase (long enough that
                      # a breath or inter-note gap doesn't split the melody)
MAX_PHRASE = 5.0      # safety cap on phrase length (seconds)
PREROLL = 6           # blocks of audio kept before onset (so attack isn't clipped)
ONSET_FACTOR = 6.0    # onset RMS = noise_floor * this (in whistle band)
RELEASE_FACTOR = 1.5  # silence RMS = noise_floor * this
NOISE_FLOOR_MIN = 0.002   # clamp calibration so one quiet/noisy moment can't
NOISE_FLOOR_MAX = 0.020   # make the gate hair-triggered or whistle-deaf


# ----------------------------------------------------------------------------
# Pitch tracking: YIN (de Cheveigne & Kawahara, 2002), pure numpy
# ----------------------------------------------------------------------------
def _difference_function(x, tau_max):
    """YIN difference function d(tau) via FFT autocorrelation."""
    x = x.astype(np.float64)
    n = len(x)
    fft_size = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(x, fft_size)
    acf = np.fft.irfft(spec * np.conj(spec), fft_size)[: tau_max + 1]
    power = np.concatenate(([0.0], np.cumsum(x * x)))
    taus = np.arange(tau_max + 1)
    term1 = power[n - taus] - power[0]      # sum x[0 : n-tau]^2
    term2 = power[n] - power[taus]          # sum x[tau : n]^2
    return term1 + term2 - 2.0 * acf


def _cmndf(d):
    """Cumulative mean normalized difference."""
    cmnd = np.ones_like(d)
    taus = np.arange(1, len(d))
    running = np.cumsum(d[1:])
    cmnd[1:] = d[1:] * taus / np.maximum(running, 1e-12)
    return cmnd


def _estimate_f0(frame, tau_min, tau_max):
    """Return (f0_hz, confidence) for one frame; f0 is 0.0 if unvoiced."""
    d = _difference_function(frame, tau_max)
    cmnd = _cmndf(d)

    tau = tau_min
    while tau < tau_max:
        if cmnd[tau] < YIN_THRESHOLD:
            while tau + 1 < tau_max and cmnd[tau + 1] < cmnd[tau]:
                tau += 1
            break
        tau += 1
    else:
        return 0.0, 0.0  # nothing below threshold -> unvoiced

    # parabolic interpolation for sub-sample period accuracy
    if 1 <= tau < tau_max:
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = a + c - 2 * b
        shift = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
        tau_ref = tau + np.clip(shift, -1, 1)
    else:
        tau_ref = tau

    return SR / tau_ref, 1.0 - cmnd[tau]


def analyze(signal, fmin=FMIN):
    """Frame the signal and return per-frame (f0, voiced, loudness) arrays."""
    tau_min = int(SR / FMAX)
    tau_max = int(SR / fmin)
    n_frames = max(1, 1 + (len(signal) - FRAME) // HOP)

    f0 = np.zeros(n_frames)
    voiced = np.zeros(n_frames, dtype=bool)
    loud = np.zeros(n_frames)

    for i in range(n_frames):
        frame = signal[i * HOP : i * HOP + FRAME]
        if len(frame) < FRAME:
            frame = np.pad(frame, (0, FRAME - len(frame)))
        rms = np.sqrt(np.mean(frame * frame) + 1e-12)
        loud[i] = rms
        pitch, conf = _estimate_f0(frame, tau_min, tau_max)
        if pitch > 0 and conf > 0:
            f0[i] = pitch
            voiced[i] = True

    # gate out near-silent frames (attack/decay tails): they have no real pitch
    # and YIN tends to lock to the tau_min rail there, giving octave errors.
    if loud.max() > 0:
        voiced &= loud > 0.15 * loud.max()
    f0[~voiced] = 0.0

    f0 = _median_filter(f0, 5)  # tame octave jumps / single-frame glitches
    voiced &= f0 > 0            # the filter can zero a frame — unmark it too
    return f0, voiced, loud


def _median_filter(x, k):
    if k < 2 or len(x) < k:
        return x
    pad = k // 2
    xp = np.pad(x, pad, mode="edge")
    return np.array([np.median(xp[i : i + k]) for i in range(len(x))])


def _fill_unvoiced(f0, voiced):
    """Hold the nearest voiced pitch across unvoiced gaps (avoids glides to 0)."""
    if not voiced.any():
        return np.full_like(f0, FMIN)
    idx = np.where(voiced, np.arange(len(f0)), -1)
    # forward-fill
    last = -1
    for i in range(len(idx)):
        if idx[i] >= 0:
            last = idx[i]
        elif last >= 0:
            idx[i] = last
    # back-fill the leading gap
    first_valid = np.argmax(voiced)
    idx[idx < 0] = first_valid
    return f0[idx]


# ----------------------------------------------------------------------------
# Synthesis: re-render the contour with a "between human and bird" voice
# ----------------------------------------------------------------------------
def synthesize(f0, voiced, loud, birdiness=0.5, reverb=0.25, shift=0.0,
               bend=0.8):
    """Turn an analyzed whistle into a stylized bird reply (float32 mono).

    Richness comes from four things beyond a plain oscillator: breath noise,
    pitch/harmonic micro-variation, a softening lowpass, and reverb.
    """
    b = float(np.clip(birdiness, 0.0, 1.0))
    n_frames = len(f0)
    if n_frames < 2 or not voiced.any():
        return np.zeros(0, dtype=np.float32)

    f0_filled = _fill_unvoiced(f0, voiced)
    frame_t = np.arange(n_frames) * HOP / SR
    in_dur = frame_t[-1] + HOP / SR

    # birds phrase a little faster -> gentle time compression (no chipmunk)
    speed = 1.0 + 0.2 * b
    n_out = max(1, int((in_dur / speed) * SR))
    t = np.arange(n_out) / SR
    src_t = t * speed

    f0_s = np.interp(src_t, frame_t, f0_filled)
    amp_s = np.interp(src_t, frame_t, loud)
    gate = np.interp(src_t, frame_t, voiced.astype(float)) > 0.5

    # upward register shift: --shift semitones + a little more with birdiness.
    # The subharmonic added below keeps the body, so this can sit higher
    # without thinning out.
    f0_s *= 2.0 ** ((shift + 3.0 * b) / 12.0)

    # natural pitch micro-drift: smoothed random walk, in cents
    drift = _drift(n_out, std_cents=8.0 + 10.0 * b)
    f0_s *= 2.0 ** (drift / 1200.0)

    # per-note random bend: each note eases from its pitch toward a small
    # random offset up OR down — no two notes land quite the same way
    if bend > 0:
        brng = np.random.default_rng()
        starts = (np.flatnonzero(~gate[:-1] & gate[1:]) + 1).tolist()
        if gate[0]:
            starts.insert(0, 0)
        for s in starts:
            e = s
            while e < n_out and gate[e]:
                e += 1
            if e - s < int(0.08 * SR):   # too short to bend musically
                continue
            amt = brng.uniform(0.3, 1.0) * bend * brng.choice([-1.0, 1.0])
            ramp = np.linspace(0.0, 1.0, e - s) ** 1.5
            f0_s[s:e] *= 2.0 ** (amt * ramp / 12.0)

    # tiny upward curl at each note ending — the "chirp flick"
    curl_n = int(0.06 * SR)
    if curl_n > 4:
        ends = np.flatnonzero(gate[:-1] & ~gate[1:]).tolist()
        if gate[-1]:
            ends.append(n_out - 1)
        for e in ends:
            s = max(0, e - curl_n)
            ramp = np.linspace(0.0, 1.0, e - s + 1) ** 2
            f0_s[s:e + 1] *= 2.0 ** (1.5 * ramp / 12.0)

    # vibrato: quick and light
    vib_rate = 6.0 + 3.0 * b
    vib_depth = 0.003 + 0.007 * b
    f_inst = f0_s * (1.0 + vib_depth * np.sin(2 * np.pi * vib_rate * t))

    # continuous phase so pitch glides without clicks
    phase = 2 * np.pi * np.cumsum(f_inst) / SR

    # timbre: warm 1/k harmonic rolloff with slight detune + random phase per
    # partial (chorus-like warmth instead of a sterile pure tone)
    rng = np.random.default_rng()
    n_harm = 7
    tone = np.zeros(n_out)
    wsum = 0.0
    for k in range(1, n_harm + 1):
        w = k ** -(1.3 - 0.3 * b)
        if k == 1:
            w *= 1.3   # fat fundamental: body without a separate low voice
        detune = 1.0 + rng.normal(0.0, 0.0025)
        # each partial breathes on its own slow cycle — a static harmonic
        # stack is what reads as "flat oscillator"
        am = 1.0 + 0.3 * np.sin(2 * np.pi * rng.uniform(0.5, 2.5) * t
                                + rng.uniform(0, 2 * np.pi))
        tone += w * am * np.sin(k * detune * phase + rng.uniform(0, 2 * np.pi))
        wsum += w
    tone /= wsum

    # breath / air: bandpass noise around the pitch region, kept subtle
    medf = float(np.median(f0_s[gate])) if gate.any() else float(f0_s.mean())
    lo = max(60.0, 0.7 * medf)
    hi = min(0.45 * SR, 2.5 * medf)
    breath = _bandpass(rng.standard_normal(n_out), lo, hi)
    if np.abs(breath).max() > 0:
        breath /= np.abs(breath).max()
    breath_level = 0.05 + 0.10 * b

    body = (1.0 - breath_level) * tone + breath_level * breath

    # amplitude envelope from the input, smoothed, gated to voiced regions
    amp = amp_s.copy()
    amp[~gate] = 0.0
    amp = _smooth(amp, int(0.012 * SR))
    if amp.max() > 0:
        amp /= amp.max()

    # ease each note in (~50 ms) — hard attacks read as beeps, not calls
    atk_n = int(0.05 * SR)
    if atk_n > 4:
        starts = (np.flatnonzero(~gate[:-1] & gate[1:]) + 1).tolist()
        if gate[0]:
            starts.insert(0, 0)
        for s in starts:
            e = min(n_out, s + atk_n)
            amp[s:e] *= np.linspace(0.0, 1.0, e - s) ** 1.5

    out = body * amp
    out = _fade(out, int(0.012 * SR))

    # soften: tame harsh highs that read as "squeaky". Cap scales with the
    # register so a higher voice keeps its harmonic count (richness).
    out = _lowpass(out, min(8000.0, 4.0 * medf))

    if reverb > 0:
        out = _apply_reverb(out, wet=float(np.clip(reverb, 0, 1)))

    peak = np.max(np.abs(out))
    if peak > 0:
        out = 0.9 * out / peak
    return out.astype(np.float32)


# --- synthesis helpers --------------------------------------------------------
def _drift(n, std_cents, corr_s=0.06):
    """Smoothly varying random offset (cents), for natural pitch wander."""
    x = np.random.default_rng().standard_normal(n)
    w = max(1, int(corr_s * SR))
    x = np.convolve(x, np.ones(w) / w, mode="same")
    s = x.std()
    return x / s * std_cents if s > 0 else x


def _butter(x, cutoff, btype, order=4):
    wn = np.asarray(cutoff, dtype=float) / (SR / 2)
    wn = float(wn) if wn.ndim == 0 else wn.tolist()  # scalar for low/high, list for band
    sos = sps.butter(order, wn, btype=btype, output="sos")
    return sps.sosfilt(sos, x)


def _lowpass(x, cutoff):
    return _butter(x, min(cutoff, 0.45 * SR), "lowpass")


def _highpass(x, cutoff, order=2):
    return _butter(x, max(cutoff, 20.0), "highpass", order=order)


def _bandpass(x, lo, hi):
    return _butter(x, [lo, hi], "bandpass")


def _apply_reverb(x, wet=0.25, seconds=1.6, dry=1.0, stages=1):
    """Convolution reverb with a synthetic, lowpassed exponential-decay IR.
    Tuned as a forest: a touch of pre-delay (nearest trees), then a long,
    dark, diffuse tail (foliage eats the highs).

    `dry` scales the direct signal (0 = reverb only, the source disappears
    into the space). `stages` convolves serially — each pass smears the tone
    further into diffuse wash. `seconds` is the TOTAL tail budget: it is
    split across stages so more diffusion doesn't also mean a longer ring."""
    stages = max(1, int(stages))
    sec = max(0.15, seconds / stages)
    decay = 4.8 / sec   # tail dies within its per-stage budget
    n = int(sec * SR)
    t = np.arange(n) / SR
    ir = np.random.default_rng().standard_normal(n) * np.exp(-decay * t)
    ir = _lowpass(ir, 2800.0)
    ir = np.concatenate([np.zeros(int(0.025 * SR)), ir])
    ir /= np.sqrt(np.sum(ir * ir)) + 1e-12
    wet_sig = x
    for _ in range(stages):
        wet_sig = sps.fftconvolve(wet_sig, ir)
    dry_sig = np.pad(x, (0, len(wet_sig) - len(x)))
    return float(np.clip(dry, 0, 1)) * (1.0 - wet) * dry_sig + wet * wet_sig


def _spec_env(mag, k=9):
    """Per-frame spectral envelope (smoothed across frequency), normalized to
    unit mean so it captures spectral *shape* (texture/formants), not level."""
    kernel = np.ones(k) / k
    env = np.empty_like(mag)
    for j in range(mag.shape[1]):
        env[:, j] = np.convolve(mag[:, j], kernel, mode="same")
    env += 1e-9
    env /= env.mean(axis=0, keepdims=True)
    return env


def _cross_synthesize(carrier, mod, amount):
    """Impose the modulator's spectral shape onto the carrier (vocoder cross-
    synthesis). Carrier keeps its pitch/harmonics + dynamics; `amount` morphs
    its timbre from itself (0) toward the modulator's bird texture (1)."""
    n = len(carrier)
    if n < 16:
        return carrier
    if len(mod) != n:
        mod = np.interp(np.linspace(0, len(mod), n, endpoint=False),
                        np.arange(len(mod)), mod)
    nfft = 1024 if n >= 1024 else 1 << int(np.floor(np.log2(n)))
    hop = nfft // 4
    _, _, cs = sps.stft(carrier, nperseg=nfft, noverlap=nfft - hop)
    _, _, ms = sps.stft(mod, nperseg=nfft, noverlap=nfft - hop)
    nf = min(cs.shape[1], ms.shape[1])
    cs, ms = cs[:, :nf], ms[:, :nf]
    cmag = np.abs(cs)
    ratio = (_spec_env(np.abs(ms)) / _spec_env(cmag)) ** float(np.clip(amount, 0, 1))
    # bound + smooth the morph over time: unclamped per-frame swings read as
    # flanging, especially below the melody
    ratio = np.clip(ratio, 0.3, 3.0)
    if ratio.shape[1] >= 3:
        kernel = np.ones(3) / 3
        ratio = np.apply_along_axis(
            lambda r: np.convolve(r, kernel, mode="same"), 1, ratio)
    out_spec = cmag * ratio * np.exp(1j * np.angle(cs))
    _, out = sps.istft(out_spec, nperseg=nfft, noverlap=nfft - hop)
    return out[:n].astype(np.float32)


def _smooth(x, n):
    if n < 2:
        return x
    kernel = np.ones(n) / n
    return np.convolve(x, kernel, mode="same")


def _fade(x, n):
    if len(x) < 2 * n or n < 1:
        return x
    ramp = np.linspace(0, 1, n)
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


# ----------------------------------------------------------------------------
# Reply rendering: tonal synth, optionally blended with bird-grain texture
# ----------------------------------------------------------------------------
def render_reply(f0, voiced, loud, birdiness, reverb,
                 corpus=None, texture=0.7, seed=None, shift=0.0,
                 dry=1.0, stages=1, tail=1.6, bend=0.8):
    """Render one reply. With a corpus, crossfades the tonal voice (carries the
    melody) with concatenative bird grains (carry the texture)."""
    tonal = synthesize(f0, voiced, loud, birdiness, reverb=0.0, shift=shift,
                       bend=bend)
    mix = tonal
    if corpus and texture > 0 and len(tonal):
        import mosaic
        # give the grain-matcher the OUTPUT register, not the input one —
        # matters when --shift/--hum moves the reply far from the source
        f0_out = f0 * 2.0 ** ((shift + 3.0 * birdiness) / 12.0)
        mos = mosaic.synthesize(f0_out, voiced, loud, corpus, seed=seed)
        if len(mos):
            # fuse into ONE voice: bird texture recolors the pitched tone
            mix = _cross_synthesize(tonal, mos, texture)

    if len(mix) and voiced.any():
        # final tone shaping AFTER the vocoder (it reshapes the spectrum, so
        # filtering the carrier alone isn't enough): steep highpass clears the
        # sub-melody rumble, lowpass rounds the top end.
        med = float(np.median(f0[voiced])) * 2.0 ** ((shift + 3.0 * birdiness) / 12.0)
        mix = _highpass(mix, 0.55 * med, order=4)
        mix = _lowpass(mix, min(7000.0, 3.5 * med))

    if reverb > 0 and len(mix):
        mix = _apply_reverb(mix, wet=float(np.clip(reverb, 0, 1)),
                            seconds=tail, dry=dry, stages=stages)
    peak = np.abs(mix).max() if len(mix) else 0.0
    if peak > 0:
        mix = 0.9 * mix / peak
    return mix.astype(np.float32)


def _load_corpus(texture_dir):
    if not texture_dir:
        return None
    import mosaic
    cached = os.path.exists(os.path.join(texture_dir, "_corpus.npz"))
    action = "Loading cached" if cached else "Building"
    print(f"{action} bird-grain corpus from {texture_dir} ...")
    t0 = time.perf_counter()
    corpus = mosaic.build_corpus(texture_dir)
    print(f"  {len(corpus)} grains "
          f"({sum(g.pitch > 0 for g in corpus)} pitched) "
          f"in {time.perf_counter() - t0:.1f}s")
    return corpus


# ----------------------------------------------------------------------------
# Audio I/O
# ----------------------------------------------------------------------------
def _flush_input(stream, flt, seconds=0.6):
    """Discard everything the mic buffered while the reply was playing, plus
    a short cooldown for the room tail — otherwise the bird hears its own
    reply, captures it, and answers itself with garbage."""
    while stream.read_available > 0:
        stream.read(min(stream.read_available, 4096))
    for _ in range(int(seconds * SR / HOP)):
        block, _ = stream.read(HOP)
        flt.rms(block[:, 0])   # keep the onset filter's state warm


def _explain_no_device():
    """Human answer for PortAudio's 'Error querying device -1'."""
    print("\nNo usable audio device. What ALSA sees right now:")
    try:
        with open("/proc/asound/cards") as f:
            print(f.read().rstrip() or "  (no cards at all)")
    except OSError:
        pass
    print(
        "\nExpected: a card 'GenericStereoAu' (the ReSpeaker Lite over I2S,\n"
        "overlay genericstereoaudiocodec). If it is missing, check\n"
        "/boot/firmware/config.txt (dtparam=i2s=on, dtoverlay=genericstereo-\n"
        "audiocodec) and the wiring, then reboot. If it is listed but busy,\n"
        "another process holds it: 'sudo fuser -v /dev/snd/*'."
    )


def _startup_watchdog(seconds=12.0):
    """Force-exit with a clear message if audio never starts flowing.

    A wedged ReSpeaker blocks forever inside PortAudio's C read, where
    Python can't deliver Ctrl-C — without this the process is unkillable.
    Returns an Event the caller sets once startup has completed."""
    import threading

    started = threading.Event()

    def bail():
        if not started.is_set():
            print(f"\nAudio device not responding after {seconds:.0f}s — "
                  "the ReSpeaker is likely wedged. Unplug it, wait 10s, "
                  "replug, then rerun.", flush=True)
            os._exit(2)

    timer = threading.Timer(seconds, bail)
    timer.daemon = True
    timer.start()
    return started


class _OnsetFilter:
    """Bandpass the onset-detector's view of the mic (whistle band only) so
    broadband rumble — traffic, wind, handling — can't trigger capture."""

    def __init__(self, lo=600.0, hi=4000.0):
        self.sos = sps.butter(4, [lo / (SR / 2), hi / (SR / 2)],
                              "bandpass", output="sos")
        self.zi = np.zeros((self.sos.shape[0], 2))

    def rms(self, block):
        y, self.zi = sps.sosfilt(self.sos, block, zi=self.zi)
        return float(np.sqrt(np.mean(y * y) + 1e-12))


def calibrate_noise(stream, flt, seconds=1.5):
    """Sample ambient in-band noise to set onset/silence thresholds.

    Median over a longer window (robust to a cough or a quiet lull), then
    clamped so the gate stays usable whatever the calibration moment was."""
    blocks = max(1, int(seconds * SR / HOP))
    rms = []
    for _ in range(blocks):
        block, _ = stream.read(HOP)
        rms.append(flt.rms(block[:, 0]))
    return float(np.clip(np.median(rms), NOISE_FLOOR_MIN, NOISE_FLOOR_MAX))


def record_phrase(stream, noise_floor, flt):
    """Block until a whistle starts, capture it, return mono float array."""
    onset = noise_floor * ONSET_FACTOR
    release = noise_floor * RELEASE_FACTOR
    preroll = []
    captured = []
    recording = False
    silent_blocks = 0
    silence_limit = int(SILENCE_HOLD * SR / HOP)
    max_blocks = int(MAX_PHRASE * SR / HOP)

    while True:
        block, _ = stream.read(HOP)
        mono = block[:, 0].copy()
        rms = flt.rms(mono)   # in-band only: rumble can't start/extend capture

        if not recording:
            preroll.append(mono)
            if len(preroll) > PREROLL:
                preroll.pop(0)
            if rms > onset:
                recording = True
                captured = list(preroll)
                print("  ... listening", end="", flush=True)
        else:
            captured.append(mono)
            print(".", end="", flush=True)
            if rms < release:
                silent_blocks += 1
                if silent_blocks >= silence_limit:
                    break
            else:
                silent_blocks = 0
            if len(captured) >= max_blocks:
                break

    print()
    return np.concatenate(captured)


def run_live(birdiness, reverb, texture, texture_dir, save_dir, shift=0.0,
             dry=1.0, stages=1, tail=1.6, hum=False, bend=0.8):
    import sounddevice as sd

    corpus = _load_corpus(texture_dir)
    fmin = HUM_FMIN if hum else FMIN
    mode = "hum" if hum else "whistle"
    tex_msg = f", texture={texture} ({len(corpus)} grains)" if corpus else ""
    sh_msg = "auto" if shift is None else f"{shift:+.0f}"
    print(f"Bird engine ready ({mode} mode, birdiness={birdiness}, "
          f"reverb={reverb}, shift={sh_msg}{tex_msg}). Ctrl-C to quit.\n")
    # One open + one close per session for BOTH directions: the ReSpeaker's
    # firmware degrades with device open/close cycles, so replies write into
    # a persistent output stream instead of sd.play() re-opening per reply.
    started = _startup_watchdog()
    try:
        stream_in = sd.InputStream(samplerate=SR, channels=1, blocksize=HOP,
                                   dtype="float32")
    except sd.PortAudioError:
        _explain_no_device()
        sys.exit(2)
    try:
        out = sd.OutputStream(samplerate=SR, channels=1, dtype="float32")
    except sd.PortAudioError:
        stream_in.close()
        _explain_no_device()
        sys.exit(2)
    # NOTE: `out` is opened once but NOT left running — a started-but-idle
    # output stream underruns continuously, which stresses the flaky
    # ReSpeaker firmware. It's started just around each reply instead.
    try:
        with stream_in as stream:
            _run_loop(stream, out, corpus, fmin, mode, hum, started,
                      birdiness, reverb, texture, shift, dry, stages, tail,
                      save_dir, bend)
    finally:
        out.close(ignore_errors=True)


def _run_loop(stream, out, corpus, fmin, mode, hum, started,
              birdiness, reverb, texture, shift, dry, stages, tail, save_dir,
              bend=0.8):
    flt = _OnsetFilter(120.0, 2500.0) if hum else _OnsetFilter()
    noise = calibrate_noise(stream, flt)
    started.set()
    print(f"Calibrated noise floor ({mode} band): {noise:.5f}\n")
    n = _save_start_index(save_dir)
    while True:
        print(f"{'Hum' if hum else 'Whistle'} something...")
        phrase = record_phrase(stream, noise, flt)
        t0 = time.perf_counter()
        f0, voiced, loud = analyze(phrase, fmin=fmin)
        t_analyze = time.perf_counter() - t0
        if voiced.sum() < 12:   # < ~70ms of real pitch = junk trigger
            print(f"  (didn't catch a clear {mode} in "
                  f"{len(phrase) / SR:.1f}s capture, try again)\n")
            continue
        vf = f0[voiced]
        print(f"  heard {voiced.sum()} voiced frames, "
              f"pitch {vf.min():.0f}-{vf.max():.0f} Hz "
              f"({len(phrase) / SR:.1f}s capture)")
        sh = _resolve_shift(shift, vf)
        t0 = time.perf_counter()
        reply = render_reply(f0, voiced, loud, birdiness, reverb,
                             corpus, texture, shift=sh,
                             dry=dry, stages=stages, tail=tail, bend=bend)
        t_render = time.perf_counter() - t0
        if len(reply) == 0:
            print("  (nothing to synthesize)\n")
            continue
        print(f"  bird replies "
              f"(analyze {t_analyze:.1f}s + synth {t_render:.1f}s)\n")
        out.start()
        out.write(np.ascontiguousarray(reply.reshape(-1, 1)))
        out.stop()   # drains playback, then idles the stream (no underruns)
        if save_dir:
            _save(reply, save_dir, n)
            n += 1
        _flush_input(stream, flt)   # don't listen to our own reply


def run_file(path, birdiness, reverb, texture, texture_dir, save_dir,
             shift=0.0, dry=1.0, stages=1, tail=1.6, hum=False, bend=0.8):
    import soundfile as sf
    import sounddevice as sd

    corpus = _load_corpus(texture_dir)
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data[:, 0]
    if sr != SR:
        mono = _resample(mono, sr, SR)
    f0, voiced, loud = analyze(mono, fmin=HUM_FMIN if hum else FMIN)
    if not voiced.any():
        print("No clear whistle found in file.")
        return
    reply = render_reply(f0, voiced, loud, birdiness, reverb, corpus, texture,
                         shift=_resolve_shift(shift, f0[voiced]),
                         dry=dry, stages=stages, tail=tail, bend=bend)
    print(f"Synthesized {len(reply) / SR:.2f}s reply.")
    sd.play(reply, SR)
    sd.wait()
    if save_dir:
        _save(reply, save_dir, 0)


def _resample(x, sr_in, sr_out):
    n_out = int(len(x) * sr_out / sr_in)
    return np.interp(np.linspace(0, len(x), n_out, endpoint=False),
                     np.arange(len(x)), x).astype(np.float32)


def _save(reply, save_dir, n):
    import soundfile as sf
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, f"{n:03d}.wav")
    sf.write(path, reply, SR)
    print(f"  saved {path}")


def _resolve_shift(shift, voiced_f0):
    """None = auto: place the reply's median pitch in whistle register, so a
    hummed melody at ANY octave comes back whistled, never growled."""
    if shift is not None:
        return shift + SHIFT_OFFSET
    med = float(np.median(voiced_f0[voiced_f0 > 0])) if (voiced_f0 > 0).any() else 0.0
    if med <= 0:
        return 24.0 + SHIFT_OFFSET
    return float(np.clip(12.0 * np.log2(WHISTLE_REGISTER / med), 0.0, 40.0)) + SHIFT_OFFSET


def _save_start_index(save_dir):
    """Continue numbering after existing files so a new session never
    overwrites an earlier session's saved replies."""
    if not save_dir or not os.path.isdir(save_dir):
        return 0
    taken = [int(f[:3]) for f in os.listdir(save_dir)
             if f.endswith(".wav") and f[:3].isdigit()]
    return max(taken) + 1 if taken else 0


# ----------------------------------------------------------------------------
def _sigterm(_sig, _frame):
    # behave like Ctrl-C so the audio stream context manager closes cleanly —
    # dying mid-stream crashes the ReSpeaker's USB firmware (needs a replug)
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGTERM, _sigterm)
    ap = argparse.ArgumentParser(description="Whistle -> stylized bird engine")
    ap.add_argument("--birdiness", type=float, default=0.5,
                    help="0.0 = faithful whistle, 1.0 = full bird (default 0.5)")
    ap.add_argument("--reverb", type=float, default=0.25,
                    help="0.0 = dry, 1.0 = drenched (default 0.25)")
    ap.add_argument("--texture-dir", dest="texture_dir",
                    help="folder of bird recordings for concatenative texture")
    ap.add_argument("--texture", type=float, default=0.7,
                    help="bird-texture morph: 0.0 = pure tone, 1.0 = full bird "
                         "timbre on your pitch (default 0.7)")
    ap.add_argument("--shift", type=float, default=None,
                    help="register shift in semitones above the input "
                         "(default 0; in --hum mode default +24 so the low "
                         "hum comes back as a whistling bird)")
    ap.add_argument("--bend", type=float, default=0.8,
                    help="max per-note random pitch bend in semitones, each "
                         "note bending up or down by chance (0 = off, "
                         "default 0.8)")
    ap.add_argument("--hum", action="store_true",
                    help="listen for a hummed melody instead of a whistle "
                         "(tracks down to 80 Hz)")
    ap.add_argument("--dry", type=float, default=1.0,
                    help="direct-voice level 0..1 (0 = reverb only, the bird "
                         "dissolves into the space; default 1)")
    ap.add_argument("--reverb-stages", dest="stages", type=int, default=1,
                    help="serial reverb passes, 1-3: more = more diffuse wash "
                         "(default 1)")
    ap.add_argument("--tail", type=float, default=1.6,
                    help="total reverb tail length in seconds, split across "
                         "stages (default 1.6)")
    ap.add_argument("--file", help="process a wav file instead of the mic")
    ap.add_argument("--save", dest="save_dir",
                    help="directory to save each reply as a wav")
    args = ap.parse_args()
    if args.shift is None and not args.hum:
        args.shift = 0.0   # hum mode keeps None = auto whistle register

    try:
        if args.file:
            run_file(args.file, args.birdiness, args.reverb, args.texture,
                     args.texture_dir, args.save_dir, shift=args.shift,
                     dry=args.dry, stages=args.stages, tail=args.tail,
                     hum=args.hum, bend=args.bend)
        else:
            run_live(args.birdiness, args.reverb, args.texture,
                     args.texture_dir, args.save_dir, shift=args.shift,
                     dry=args.dry, stages=args.stages, tail=args.tail,
                     hum=args.hum, bend=args.bend)
    except KeyboardInterrupt:
        print("\nbye")
        sys.exit(0)


if __name__ == "__main__":
    main()
