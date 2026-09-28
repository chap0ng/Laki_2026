"""
Concatenative ("mosaic") bird-texture synthesis.

Idea: take a corpus of REAL bird recordings, chop them into short grains
(syllables), and re-sequence + pitch-shift those grains to follow your
whistle's pitch and rhythm. The output is built from real bird audio, so it
carries genuine bird texture that a tonal synth can't fake. Light enough for a
Pi Zero 2 W: just segmentation, resampling, and overlap-add.

Drop bird recordings (wav/flac/mp3) into a folder and point --texture-dir at it.
Good source: xeno-canto.org (Creative-Commons bird recordings).
"""

import os
import glob
import numpy as np
from scipy import signal as sps

import bird  # reuse SR, FRAME, HOP and the YIN estimator

# Birds range higher than a human whistle, so widen the pitch search for grains.
BIRD_FMIN = 400.0
BIRD_FMAX = 6000.0
GRAIN_MS = 120          # nominal grain length when splitting sustained sounds
GRAIN_MIN_MS = 50       # discard grains shorter than this
FADE_MS = 6             # edge fade per grain for click-free overlap-add


class Grain:
    __slots__ = ("audio", "pitch", "rms")

    def __init__(self, audio, pitch, rms):
        self.audio = audio
        self.pitch = pitch
        self.rms = rms


def _load_mono(path):
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data[:, 0]
    if sr != bird.SR:
        n_out = int(len(mono) * bird.SR / sr)
        mono = np.interp(np.linspace(0, len(mono), n_out, endpoint=False),
                         np.arange(len(mono)), mono).astype(np.float32)
    return mono


def _grain_pitch(grain):
    """Dominant spectral frequency in the bird band (0.0 if no energy).

    Bird syllables sweep fast and are semi-noisy, so YIN periodicity is
    unreliable; the strongest spectral peak is robust and is exactly the
    frequency we align to the whistle's pitch.
    """
    if len(grain) < 256:
        return 0.0
    w = grain * np.hanning(len(grain))
    spec = np.abs(np.fft.rfft(w))
    fr = np.fft.rfftfreq(len(grain), 1.0 / bird.SR)
    band = (fr >= BIRD_FMIN) & (fr <= BIRD_FMAX)
    if not band.any():
        return 0.0
    spec = np.where(band, spec, 0.0)
    idx = int(np.argmax(spec))
    return float(fr[idx]) if spec[idx] > 0 else 0.0


def _segment(signal):
    """Split a recording into syllable grains by amplitude gating."""
    win = max(1, int(0.01 * bird.SR))
    env = np.convolve(np.abs(signal), np.ones(win) / win, mode="same")
    if env.max() <= 0:
        return []
    thresh = 0.08 * env.max()
    active = env > thresh

    grains = []
    grain_len = int(GRAIN_MS / 1000 * bird.SR)
    min_len = int(GRAIN_MIN_MS / 1000 * bird.SR)

    i, n = 0, len(signal)
    while i < n:
        if not active[i]:
            i += 1
            continue
        j = i
        while j < n and active[j]:
            j += 1
        # split a long active run into grain-sized chunks
        for s in range(i, j, grain_len):
            chunk = signal[s:min(s + grain_len, j)]
            if len(chunk) >= min_len:
                grains.append(chunk.copy())
        i = j
    return grains


def build_corpus(folder, cache=True):
    """Load + segment + analyze every recording in `folder` into grains."""
    cache_path = os.path.join(folder, f"_corpus_{int(bird.SR)}.npz")
    if cache and os.path.exists(cache_path):
        d = np.load(cache_path, allow_pickle=True)
        audios, pitches, rmss = d["audios"], d["pitches"], d["rmss"]
        return [Grain(a, float(p), float(r))
                for a, p, r in zip(audios, pitches, rmss)]

    paths = []
    for ext in ("wav", "flac", "aiff", "aif", "mp3", "ogg"):
        paths += glob.glob(os.path.join(folder, f"*.{ext}"))
    if not paths:
        raise FileNotFoundError(f"No audio files in {folder}")

    grains = []
    for p in sorted(paths):
        try:
            sig = _load_mono(p)
        except Exception as e:
            print(f"  skip {os.path.basename(p)}: {e}")
            continue
        for g in _segment(sig):
            pitch = _grain_pitch(g)
            rms = float(np.sqrt(np.mean(g * g) + 1e-12))
            grains.append(Grain(g.astype(np.float32), pitch, rms))

    if cache and grains:
        np.savez(cache_path,
                 audios=np.array([g.audio for g in grains], dtype=object),
                 pitches=np.array([g.pitch for g in grains]),
                 rmss=np.array([g.rms for g in grains]))
    return grains


def _pitch_shift(grain, factor):
    """Resample a grain so its pitch is multiplied by `factor` (length / factor)."""
    if abs(factor - 1.0) < 1e-3 or len(grain) < 4:
        return grain
    n_out = max(4, int(len(grain) / factor))
    return sps.resample(grain, n_out).astype(np.float32)


def _edge_fade(x):
    n = min(int(FADE_MS / 1000 * bird.SR), len(x) // 2)
    if n < 1:
        return x
    ramp = np.linspace(0, 1, n)
    x = x.copy()
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


def synthesize(f0, voiced, loud, corpus, grain_hop_ms=70, topk=4, seed=None):
    """Re-sequence corpus grains to follow the whistle's pitch + rhythm."""
    pitched = [g for g in corpus if g.pitch > 0]
    if not pitched:
        return np.zeros(0, dtype=np.float32)
    pitch_arr = np.array([g.pitch for g in pitched])

    rng = np.random.default_rng(seed)
    f0_filled = bird._fill_unvoiced(f0, voiced)
    n_frames = len(f0)
    in_len = n_frames * bird.HOP
    hop = max(1, int(grain_hop_ms / 1000 * bird.SR))
    loud_norm = loud / (loud.max() + 1e-12)

    out = np.zeros(in_len + int(0.5 * bird.SR), dtype=np.float32)
    pos = 0
    while pos < in_len:
        frame = min(n_frames - 1, pos // bird.HOP)
        if not voiced[frame]:
            pos += hop
            continue
        target = f0_filled[frame]

        # pick among the k nearest-pitch grains (variety avoids robotic repeats)
        order = np.argsort(np.abs(np.log2(pitch_arr / target)))
        choice = pitched[order[rng.integers(0, min(topk, len(order)))]]

        factor = float(np.clip(choice.pitch / target, 0.5, 2.0))
        grain = _pitch_shift(choice.audio, factor)
        grain = _edge_fade(grain)
        peak = np.abs(grain).max()
        if peak > 0:
            grain = grain / peak * loud_norm[frame]

        end = pos + len(grain)
        if end > len(out):
            out = np.pad(out, (0, end - len(out)))
        out[pos:end] += grain
        pos += hop

    peak = np.abs(out).max()
    if peak > 0:
        out = 0.9 * out / peak
    return out.astype(np.float32)


# --- synthetic test corpus (so the pipeline runs before you source samples) ---
def make_test_corpus(n=24, seed=0):
    """Cheap chirpy grains for testing the mosaic plumbing without real audio."""
    rng = np.random.default_rng(seed)
    grains = []
    for _ in range(n):
        dur = rng.uniform(0.06, 0.15)
        t = np.arange(int(dur * bird.SR)) / bird.SR
        base = rng.uniform(900, 3500)
        sweep = base * (1 + rng.uniform(-0.3, 0.3) * np.sin(2 * np.pi * 30 * t))
        phase = 2 * np.pi * np.cumsum(sweep) / bird.SR
        env = np.sin(np.pi * np.linspace(0, 1, len(t))) ** 0.6
        audio = (np.sin(phase) + 0.3 * np.sin(2 * phase)) * env
        audio += 0.05 * rng.standard_normal(len(t)) * env
        audio = audio.astype(np.float32)
        grains.append(Grain(audio, _grain_pitch(audio), float(np.sqrt(np.mean(audio**2)))))
    return grains


# --- run directly to inspect/audition a corpus --------------------------------
def _main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Inspect or audition a bird-grain corpus (the engine itself "
                    "runs via bird.py --texture-dir).")
    ap.add_argument("folder", help="folder of bird recordings")
    ap.add_argument("--audition", metavar="OUT.wav",
                    help="write the extracted grains (pitch-sorted) to a wav so "
                         "you can hear what the segmenter produced")
    ap.add_argument("--rebuild", action="store_true",
                    help="ignore any cached _corpus.npz and re-segment")
    args = ap.parse_args()

    corpus = build_corpus(args.folder, cache=not args.rebuild)
    pitched = [g for g in corpus if g.pitch > 0]
    total_s = sum(len(g.audio) for g in corpus) / bird.SR
    print(f"\n{len(corpus)} grains  ({len(pitched)} pitched)  "
          f"{total_s:.1f}s total")
    if pitched:
        ps = sorted(g.pitch for g in pitched)
        print(f"pitch range: {ps[0]:.0f}-{ps[-1]:.0f} Hz   "
              f"median {ps[len(ps) // 2]:.0f} Hz")
        if ps[0] >= BIRD_FMIN * 1.05:
            print(f"(all grains >= {BIRD_FMIN:.0f} Hz; lower BIRD_FMIN if your "
                  f"birds sit below that)")

    if args.audition:
        import soundfile as sf
        gap = np.zeros(int(0.08 * bird.SR), dtype=np.float32)
        clips = []
        for g in sorted(pitched or corpus, key=lambda g: g.pitch):
            a = _edge_fade(g.audio)
            peak = np.abs(a).max()
            clips.append(a / peak * 0.9 if peak > 0 else a)
            clips.append(gap)
        sf.write(args.audition, np.concatenate(clips) if clips else gap, bird.SR)
        print(f"wrote audition montage -> {args.audition}")


if __name__ == "__main__":
    _main()
