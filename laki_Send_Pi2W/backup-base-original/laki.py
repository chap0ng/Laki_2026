"""
Laki — the connected bird.

    say "Lucky"           -> the bird whistles the phrase it was taught
    press the button      -> TRAIN: each whistle you make is answered by the
                             bird; the LAST answer is kept as a draft
    press the button again-> the draft becomes the bird's phrase (stored,
                             pushed to peer birds), back to listening

Sound cues (in the bird's own voice):
    READY      two rising notes   – bird is up and listening for "Lucky"
    LISTENING  one up-chirp       – training mode is armed, whistle now
    STORED     three falling notes– the phrase has been saved
    NOTHING    low double-note    – left training with nothing recorded

One process, ONE duplex audio stream open for the whole session (the
ReSpeaker Lite, now wired over I2S, is the bus clock master and runs at a
fixed 48 kHz), the wake-word model and the whistle capture simply share the
same block stream.

Buttons (all equivalent, any can be used at once):
    * `./laki button` from another terminal (sends SIGUSR1)
    * ENTER / SPACE in the terminal when run in the foreground
    * USB HID button (evdev key press on any /dev/input/event* whose name
      matches BUTTON_HID_NAME)
    * GPIO pin BUTTON_GPIO shorted to GND (gpiozero + lgpio from the system
      python packages; the venv is created with --system-site-packages)

Peers: every hostname in peers.txt gets the new phrase (rsync) when it is
stored, and a UDP "PLAY" broadcast when the wake word fires, so all birds
on the network whistle together.
"""

import argparse
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time

import numpy as np
from scipy import signal as sps

import bird
from bird import HOP

# The ReSpeaker Lite is wired over I2S (overlay `genericstereoaudiocodec`,
# card "GenericStereoAudioCodec"): playback is hw:0,0, capture is hw:0,1,
# 2 ch each, S16/S32. The codec is bit/frame clock MASTER at a fixed 48 kHz —
# ALSA accepts any nominal rate, but the data really flows at 48 k (measured
# 2026-09-03: a "4 s" capture at nominal 16 k took 1.35 s).
#
# The ENGINE (pitch analysis, rendering, cues, wake word, the phrase file)
# runs at 16 kHz: whistles live below 4 kHz, the wake model wants 16 k, and
# on a Zero 2 W a 5 s whistle takes 2.2 s to analyse+render at 16 k against
# 9.4 s at 48 k (measured 2026-09-03). read() decimates the mic 3:1 with a
# stateful FIR, play() upsamples the reply 1:3 once.
STREAM_SR = 48000
ENGINE_SR = 16000
RATIO = STREAM_SR // ENGINE_SR
bird.SR = ENGINE_SR
bird.FRAME = 1024                # 64 ms at 16 k (was 2048 = 43 ms at 48 k)
AUDIO_CARD = "GenericStereoAudioCodec"   # substring of the sounddevice names
ALSA_CARD_ID = "GenericStereoAu"         # as it appears in /proc/asound/cards
STALL_SECONDS = 3.0              # no mic block for this long = I2S clock gone
# Buffering. The loop reads one block then writes one block, so the output
# buffer would run at whatever fill it started with — prime it with silence so
# a slow step (the wake model runs ~every 80 ms) cannot starve the DAC, and ask
# PortAudio for a deep enough ring buffer on both sides.
STREAM_LATENCY = float(os.environ.get("LAKI_LATENCY", 0.3))    # s, both directions
PRIME_MS = float(os.environ.get("LAKI_PRIME_MS", 200))          # output lead (silence) kept ahead of the DAC
SLOW_STEP_MS = 60                # log a loop step (compute between two reads) longer than this

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# wake backends:
#   sherpa  – sherpa-onnx keyword spotter, ANY word typed in WAKE_WORDS, no
#             training (default; catches a single "Lucky")
#   oww     – openwakeword custom model (the student's "Lucky Lucky"; needs a
#             newly trained model to catch a single "Lucky")
WAKE_BACKEND = "sherpa"
WAKE_WORDS = ["LUCKY", "HEY LUCKY"]      # sherpa: plain text, upper-case
KWS_DIR = os.path.join(HERE, "wake", "kws")   # sherpa-onnx-kws-zipformer-gigaspeech-3.3M
KWS_THRESHOLD = 0.3                      # sherpa keywords_threshold (0.1 loose .. 0.5 strict)
WAKE_MODEL = os.path.join(HERE, "wake", "Lucky_Lucky.onnx")   # oww
WAKE_THRESHOLD = 0.6                     # oww score threshold
WAKE_COOLDOWN = 3.0           # s between two wake triggers
WAKE_SR = 16000
WAKE_CHUNK = 1280             # 80 ms at 16 kHz, what openwakeword expects


def _wake_ratio():
    """(up, down, in_chunk): resample factors engine rate -> 16 kHz and how
    many engine samples make one 1280-sample wake chunk. With the engine at
    16 k this is 1:1 — no resampling."""
    from math import gcd
    g = gcd(WAKE_SR, bird.SR)
    up, down = WAKE_SR // g, bird.SR // g
    return up, down, WAKE_CHUNK * down // up

SOUNDS_DIR = os.path.join(HERE, "sounds")
LAKI_OUT = os.path.join(SOUNDS_DIR, "laki_out.wav")
LAKI_PREV = os.path.join(SOUNDS_DIR, "laki_out.prev.wav")   # the phrase before the last store (undo: mv it back)
PEERS_FILE = os.path.join(HERE, "peers.txt")
PEER_REMOTE_DIR = "~/laki/sounds/"
UDP_PORT = 5005
UDP_MAGIC = b"LAKI PLAY"

PIDFILE = "/tmp/laki.pid"
BUTTON_HID_NAME = "hid 8808:6600"     # student's USB button; lowercase substring
BUTTON_GPIO = 17                     # BCM pin -> GND
BUTTON_DEBOUNCE = 0.4                # s between two accepted presses
BUTTON_GPIO_HOLD = 0.03              # s the pin must stay low to count

# Training only starts a capture when the whistle-band level is above BOTH
# noise*ONSET_FACTOR and this absolute floor, so a voice across the room does
# not get recorded and answered. (The wake word has no such gate: people call
# the bird from afar.) Tune with LAKI_TRAIN_LEVEL; the log prints each
# capture's level so you can see where whistles and false starts land.
TRAIN_MIN_LEVEL = float(os.environ.get("LAKI_TRAIN_LEVEL", 0.08))

# Output level. The I2S card has no mixer, so the gain is applied in software
# to every output block (there is no way to emit sound before it is set).
# Same scale as the old ALSA softvol control: 100 % = 0 dB, 75 % = -12.75 dB,
# 1 % = -50.5 dB (LAKI_VOLUME=1 for silent soaks).
VOLUME_PERCENT = int(os.environ.get("LAKI_VOLUME", 75))
VOLUME_DB_RANGE = 51.0


def output_gain(percent=None):
    p = max(0, min(100, VOLUME_PERCENT if percent is None else percent))
    if p == 0:
        return 0.0
    return float(10 ** (-VOLUME_DB_RANGE * (1 - p / 100) / 20))

# bird voice — same settings as the cues (Vytas preferred their tighter sound,
# 2026-08-24): light reverb, mostly dry, short tail, small bends, no grain
# texture. hum=True keeps the low pitch floor / wide onset band for capture;
# shift=None auto-places the reply in whistle register (≈0 for a whistle).
VOICE = dict(birdiness=0.3, reverb=0.12, dry=0.7, stages=1, tail=0.6,
             texture=0.25, shift=None, bend=0.3, hum=True)
TEXTURE_DIR = os.path.join(HERE, "birds")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def require_respeaker():
    """First thing at startup: is the I2S sound card there at all? Fail fast
    with one clear line — don't touch ALSA, don't load models."""
    try:
        cards = open("/proc/asound/cards").read()
    except OSError:
        return                      # not Linux (dev machine) — skip
    if ALSA_CARD_ID not in cards:
        log(f"I2S sound card not found (no '{ALSA_CARD_ID}' in /proc/asound/cards). "
            "Check `dtoverlay=genericstereoaudiocodec` + `dtparam=i2s=on` in "
            "/boot/firmware/config.txt and the ReSpeaker wiring, then reboot.")
        sys.exit(2)


def set_volume():
    """Nothing to materialise any more: the gain is baked into every output
    block (see output_gain). Just say what it is."""
    g = output_gain()
    db = 20 * np.log10(g) if g > 0 else float("-inf")
    log(f"volume {VOLUME_PERCENT}% ({db:+.1f} dB, software gain on the I2S output)")


def load_wav(path):
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data[:, 0]
    if sr != bird.SR:
        mono = bird._resample(mono, sr, bird.SR)
    return np.ascontiguousarray(mono)


def save_wav(path, audio):
    import soundfile as sf
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.wav"
    sf.write(tmp, audio, bird.SR)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Contour cleaning: make an analyzed whistle as smooth as a drawn cue
# ---------------------------------------------------------------------------
CLEAN = dict(
    gap_ms=80,        # unvoiced holes shorter than this are bridged (breath, edge flicker)
    min_note_ms=40,   # voiced islands shorter than this are junk → dropped
    pitch_ms=30,      # pitch smoothing window (after a 9-frame median)
    loud_ms=40,       # loudness smoothing window
)


def _ma(x, n):
    """Centered moving average, edge-padded."""
    n = max(1, int(n))
    if n == 1 or len(x) < n:
        return x
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, np.ones(n) / n, mode="valid")


def _runs(mask):
    """[(start, end)) of True runs in a boolean array."""
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def clean_contour(f0, voiced, loud):
    """YIN output → smooth pitch, continuous notes, steady loudness. The cues
    sound clean because they skip analysis; this brings the whistle path up
    to the same standard."""
    fpm = bird.SR / HOP / 1000.0            # frames per millisecond
    f0 = f0.copy(); voiced = voiced.copy(); loud = loud.copy()

    # 1. drop voiced islands too short to be a note
    for a, b in _runs(voiced):
        if b - a < CLEAN["min_note_ms"] * fpm:
            voiced[a:b] = False
    if not voiced.any():
        return f0, voiced, loud

    # 2. bridge short unvoiced holes between notes (breath, edge flicker)
    for a, b in _runs(~voiced):
        if a > 0 and b < len(voiced) and b - a < CLEAN["gap_ms"] * fpm:
            voiced[a:b] = True
            f0[a:b] = np.interp(np.arange(a, b), [a - 1, b], [f0[a - 1], f0[b]])

    # 3. pitch: median (kills octave/one-frame glitches) then smooth, in cents
    #    so the smoothing is musically uniform; done per note so notes don't
    #    bleed into each other
    for a, b in _runs(voiced):
        seg = f0[a:b]
        cents = 1200.0 * np.log2(np.maximum(seg, 1.0))
        k = min(9, (b - a) | 1)
        if k >= 3:
            cents = np.array([np.median(cents[max(0, i - k // 2): i + k // 2 + 1])
                              for i in range(len(cents))])
        cents = _ma(cents, CLEAN["pitch_ms"] * fpm)
        f0[a:b] = 2.0 ** (cents / 1200.0)
    f0[~voiced] = 0.0

    # 4. loudness: smooth, and give every note a soft edge
    loud = _ma(loud, CLEAN["loud_ms"] * fpm)
    for a, b in _runs(voiced):
        n = b - a
        e = max(1, min(int(15 * fpm), n // 2))
        ramp = np.linspace(0.3, 1.0, e)
        loud[a:a + e] *= ramp
        loud[b - e:b] *= ramp[::-1]
    return f0, voiced, loud


# ---------------------------------------------------------------------------
# Cues: tiny whistles rendered through the bird's own synth
# ---------------------------------------------------------------------------
def _contour(notes, gap=0.05):
    """notes = [(f_start, f_end, seconds), ...] -> (f0, voiced, loud) frames."""
    f0, voiced, loud = [], [], []
    for f_a, f_b, dur in notes:
        n = max(2, int(dur * bird.SR / HOP))
        f0.extend(np.geomspace(f_a, f_b, n))
        voiced.extend([True] * n)
        env = np.sin(np.linspace(0, np.pi, n)) ** 0.5   # soft in/out
        loud.extend(0.05 + 0.15 * env)
        g = int(gap * bird.SR / HOP)
        f0.extend([0.0] * g)
        voiced.extend([False] * g)
        loud.extend([0.0] * g)
    return np.array(f0), np.array(voiced), np.array(loud)


def make_cues():
    def render(notes):
        f0, v, l = _contour(notes)
        return bird.render_reply(f0, v, l, VOICE["birdiness"], 0.15,
                                 None, 0.0, shift=0.0, dry=0.6, stages=1,
                                 tail=0.6, bend=0.3)

    return {
        "ready":     render([(1400, 1900, 0.18), (1900, 2600, 0.22)]),
        "listening": render([(1600, 2800, 0.16)]),
        "stored":    render([(2600, 2300, 0.11), (2100, 1800, 0.11),
                             (1700, 1300, 0.16)]),
        "nothing":   render([(1200, 1000, 0.12), (1200, 1000, 0.12)]),
    }


# ---------------------------------------------------------------------------
# Button sources -> one queue
# ---------------------------------------------------------------------------
class Buttons:
    def __init__(self):
        self.q = queue.Queue()
        self._last = 0.0

    def press(self, source):
        now = time.time()
        if now - self._last < BUTTON_DEBOUNCE:
            return
        self._last = now
        self.q.put(source)

    def pressed(self):
        """Non-blocking: name of the source that pressed, or None."""
        try:
            return self.q.get_nowait()
        except queue.Empty:
            return None

    def start_all(self):
        signal.signal(signal.SIGUSR1, lambda *_: self.press("signal"))
        if sys.stdin.isatty():
            threading.Thread(target=self._keyboard, daemon=True).start()
            log("button: ENTER/SPACE in this terminal")
        threading.Thread(target=self._evdev, daemon=True).start()
        threading.Thread(target=self._gpio, daemon=True).start()
        log(f"button: `./laki button`")

    def _keyboard(self):
        for line in sys.stdin:
            self.press("keyboard")

    def _evdev(self):
        import struct
        fmt = "llHHI"
        size = struct.calcsize(fmt)
        fds = []
        base = "/dev/input"
        if not os.path.isdir(base):
            return
        for ev in sorted(os.listdir(base)):
            if not ev.startswith("event"):
                continue
            try:
                with open(f"/sys/class/input/{ev}/device/name") as f:
                    name = f.read().strip().lower()
                if BUTTON_HID_NAME not in name:
                    continue
                fds.append(os.open(f"{base}/{ev}", os.O_RDONLY))
                log(f"button: USB HID {ev} ({name})")
            except Exception:
                continue
        if not fds:
            return
        import select
        while True:
            ready, _, _ = select.select(fds, [], [], 1.0)
            for fd in ready:
                data = os.read(fd, size)
                if len(data) != size:
                    continue
                _, _, etype, code, value = struct.unpack(fmt, data)
                if etype == 1 and value == 1:      # EV_KEY press, any key
                    self.press("usb-button")

    def _gpio(self):
        try:
            from gpiozero import Button
        except Exception:
            return
        try:
            btn = Button(BUTTON_GPIO, pull_up=True, bounce_time=0.05)

            def on_edge():
                # a real press keeps the pin low; a glitch on the wire does not
                time.sleep(BUTTON_GPIO_HOLD)
                if btn.is_pressed:
                    self.press("gpio")
            btn.when_pressed = on_edge
            log(f"button: GPIO{BUTTON_GPIO} -> GND")
            while True:
                time.sleep(60)
        except Exception as e:
            log(f"button: gpio unavailable ({e})")


# ---------------------------------------------------------------------------
# Peers: push the phrase, broadcast play
# ---------------------------------------------------------------------------
class Peers:
    def __init__(self, on_remote_play):
        self.hosts = []
        if os.path.exists(PEERS_FILE):
            with open(PEERS_FILE) as f:
                self.hosts = [l.strip() for l in f
                              if l.strip() and not l.startswith("#")]
        if self.hosts:
            log(f"peers: {', '.join(self.hosts)}")
        self._on_remote_play = on_remote_play
        self._id = os.urandom(4)          # so we ignore our own broadcast
        threading.Thread(target=self._listen, daemon=True).start()

    def push_phrase(self):
        for host in self.hosts:
            threading.Thread(target=self._rsync, args=(host,),
                             daemon=True).start()

    def _rsync(self, host):
        r = subprocess.run(["rsync", "-q", "--timeout=20", LAKI_OUT,
                            f"{host}:{PEER_REMOTE_DIR}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode == 0:
            log(f"peers: phrase sent to {host}")
        else:
            log(f"peers: could not send to {host}: "
                f"{r.stderr.decode(errors='replace').strip()[:120]}")

    def broadcast_play(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(UDP_MAGIC + self._id, ("255.255.255.255", UDP_PORT))
            s.close()
        except Exception as e:
            log(f"peers: broadcast failed ({e})")

    def _listen(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", UDP_PORT))
        except Exception as e:
            log(f"peers: no UDP listener ({e})")
            return
        while True:
            data, (ip, _) = s.recvfrom(64)
            if data.startswith(UDP_MAGIC) and data[len(UDP_MAGIC):] != self._id:
                self._on_remote_play(ip)


# ---------------------------------------------------------------------------
# Wake-word backends: feed 16 kHz float chunks, get True when the name is said
# ---------------------------------------------------------------------------
class WakeSherpa:
    """sherpa-onnx transducer keyword spotting: keywords are text, no training."""

    def __init__(self, threshold):
        import sherpa_onnx
        import sentencepiece as spm
        d = KWS_DIR
        sp = spm.SentencePieceProcessor(model_file=os.path.join(d, "bpe.model"))
        kw_path = os.path.join(d, "keywords_laki.txt")
        with open(kw_path, "w") as f:
            for w in WAKE_WORDS:
                f.write(" ".join(sp.encode(w, out_type=str))
                        + " @" + w.replace(" ", "_") + "\n")
        stem = "epoch-12-avg-2-chunk-16-left-64.int8.onnx"
        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=os.path.join(d, "tokens.txt"),
            encoder=os.path.join(d, f"encoder-{stem}"),
            decoder=os.path.join(d, f"decoder-{stem}"),
            joiner=os.path.join(d, f"joiner-{stem}"),
            num_threads=1, max_active_paths=4, keywords_file=kw_path,
            keywords_score=1.0, keywords_threshold=threshold,
            num_trailing_blanks=1, provider="cpu")
        self.stream = self.kws.create_stream()
        self.name = f"sherpa-onnx kws {WAKE_WORDS} (threshold {threshold})"

    def feed(self, x16):
        self.stream.accept_waveform(WAKE_SR, x16)
        hit = None
        while self.kws.is_ready(self.stream):
            self.kws.decode_stream(self.stream)
            r = self.kws.get_result(self.stream)
            if r:
                hit = r
                self.kws.reset_stream(self.stream)
        return hit

    def reset(self):
        self.stream = self.kws.create_stream()


class WakeOWW:
    """openwakeword custom model (.onnx)."""

    def __init__(self, threshold):
        from openwakeword.model import Model
        self.model = Model(wakeword_models=[WAKE_MODEL],
                           inference_framework="onnx")
        self.threshold = threshold
        self.debug = False
        self.name = f"openwakeword {os.path.basename(WAKE_MODEL)} (threshold {threshold})"

    def feed(self, x16):
        pcm = np.clip(x16 * 32767, -32768, 32767).astype(np.int16)
        scores = self.model.predict(pcm)
        score = max(scores.values()) if scores else 0.0
        if self.debug and score > 0.1:
            log(f"  wake score {score:.2f}")
        return f"score {score:.2f}" if score >= self.threshold else None

    def reset(self):
        self.model.reset()


# ---------------------------------------------------------------------------
# The bird
# ---------------------------------------------------------------------------
class Laki:
    def __init__(self, args):
        self.args = args
        self.buttons = Buttons()
        self.play_requests = queue.Queue()   # from wake word / peers
        self.peers = Peers(lambda ip: self.play_requests.put(f"peer {ip}"))
        self.phrase = None
        self.phrase_mtime = 0.0
        self.cues = {}
        self.wake = None
        self.corpus = None
        self.stream = None
        self.flt = (bird._OnsetFilter(120.0, 2500.0) if VOICE["hum"]
                    else bird._OnsetFilter())
        self.fmin = bird.HUM_FMIN if VOICE["hum"] else bird.FMIN
        self.last_wake = 0.0
        self._bad = 0
        self._pending = None
        self._pos = 0
        self._reading_since = None       # set while blocked in stream.read()
        self._silence = np.zeros((HOP * RATIO, 2), dtype=np.int16)
        # 3:1 mic decimator: linear-phase FIR, streaming state kept across blocks
        self._dec_b = sps.firwin(63, 0.45 * ENGINE_SR, fs=STREAM_SR)
        self._dec_zi = np.zeros(len(self._dec_b) - 1)
        self._gain = output_gain()
        self._devices = (None, None)
        self._xruns = [0, 0, 0.0]        # input overflows, output underflows, last report
        self._t_out = None               # when the last read() returned (step timing)
        self._slow_logged = 0.0

    # -- setup ------------------------------------------------------------
    def setup(self):
        require_respeaker()
        set_volume()
        log("rendering cues ...")
        self.cues = make_cues()
        self.corpus = bird._load_corpus(TEXTURE_DIR) if VOICE["texture"] > 0 \
            else None
        self._reload_phrase()
        self._load_wake_model()

    def _load_wake_model(self):
        if self.args.no_wake:
            log("wake word disabled (--no-wake)")
            return
        thr = self.args.threshold
        if self.args.wake == "oww":
            self.wake = WakeOWW(thr if thr is not None else WAKE_THRESHOLD)
            self.wake.debug = self.args.debug
        else:
            self.wake = WakeSherpa(thr if thr is not None else KWS_THRESHOLD)
        log(f"wake word: {self.wake.name}")

    def _reload_phrase(self):
        """Pick up laki_out.wav if it changed (a peer may have rsynced it)."""
        try:
            m = os.path.getmtime(LAKI_OUT)
        except OSError:
            if self.phrase is None:
                log("no phrase stored yet — press the button and whistle")
            return
        if m != self.phrase_mtime:
            self.phrase = load_wav(LAKI_OUT)
            self.phrase_mtime = m
            log(f"phrase loaded ({len(self.phrase) / bird.SR:.1f}s)")

    # -- audio ------------------------------------------------------------
    def read(self):
        """One duplex step: read HOP*RATIO stream frames AND write as many
        (the next slice of pending playback, or silence). The output side is
        never started/stopped. Returns (HOP, 1) float32 at ENGINE_SR."""
        n = HOP * RATIO
        t = time.time()
        if self._t_out is not None and (t - self._t_out) * 1000 > SLOW_STEP_MS \
                and t - self._slow_logged > 30:
            self._slow_logged = t
            log(f"slow step: {(t - self._t_out) * 1000:.0f} ms between two mic reads "
                f"(output lead is {PRIME_MS:.0f} ms)")
        self._reading_since = t
        try:
            inp, overflowed = self.stream.read(n)
        except Exception as e:
            log(f"AUDIO DEVICE LOST ({e}) — exiting, check the I2S wiring / reboot")
            os._exit(3)
        self._reading_since = None
        if self._pending is not None:
            a, b = self._pos, self._pos + n
            chunk = self._pending[a:b]
            self._pos = b
            if len(chunk) < n:
                chunk = np.pad(chunk, (0, n - len(chunk)))
                self._pending = None
            pcm = np.clip(chunk * (32767 * self._gain), -32768, 32767).astype(np.int16)
            out = np.stack([pcm, pcm], 1)
        else:
            out = self._silence
        try:
            underflowed = self.stream.write(out)
        except Exception as e:
            log(f"AUDIO DEVICE LOST on write ({e}) — exiting, check the I2S wiring / reboot")
            os._exit(3)
        if overflowed or underflowed:
            self._bad += 1
            if self._bad > 400:
                log("AUDIO DEVICE LOST (every block over/underruns) — exiting, "
                    "check the I2S wiring / reboot")
                os._exit(3)
            self._note_xrun(overflowed, underflowed)
            if underflowed:
                self._prime()            # the lead is gone after an underrun — rebuild it
        else:
            self._bad = 0
        self._t_out = time.time()
        x = inp[:, 0].astype(np.float32) / 32768.0
        y, self._dec_zi = sps.lfilter(self._dec_b, 1.0, x, zi=self._dec_zi)
        return y[::RATIO].reshape(-1, 1).astype(np.float32)

    def _prime(self):
        """Write PRIME_MS of silence so the output runs that far ahead of the
        DAC; the read-then-write loop keeps the lead constant afterwards."""
        n = HOP * RATIO
        blocks = int(PRIME_MS / 1000 * STREAM_SR / n)
        for _ in range(blocks):
            self.stream.write(self._silence)
        return blocks * n * 1000 / STREAM_SR

    def _note_xrun(self, overflowed, underflowed):
        """Count over/underruns (blocking read/write return plain bools); log
        the first few, then a summary at most once a minute. They are what
        crackling sounds like."""
        x = self._xruns
        x[0] += bool(overflowed)
        x[1] += bool(underflowed)
        total = x[0] + x[1]
        now = time.time()
        if total <= 3 or now - x[2] > 60:
            x[2] = now
            log(f"xrun: in-overflow={bool(overflowed)} out-underflow={bool(underflowed)} "
                f"(so far: {x[0]} overflows, {x[1]} underflows)")

    def _stall_watchdog(self):
        """If the codec stops clocking the I2S bus, stream.read() blocks in C
        forever, where Ctrl-C cannot reach. Exit with a message instead.
        Only time spent INSIDE stream.read() counts — the main thread is
        legitimately away from the mic for seconds while rendering a reply,
        and that must not look like a stall (false alarm seen 2026-09-03)."""
        while True:
            time.sleep(0.5)
            t0 = self._reading_since
            if t0 is not None and time.time() - t0 > STALL_SECONDS:
                log(f"AUDIO DEVICE STALLED (a mic read blocked for {STALL_SECONDS:.0f}s) — "
                    "exiting; the ReSpeaker stopped clocking I2S. Power-cycle it "
                    "(or reboot), rerun ./laki.sh")
                os._exit(3)

    def _calibrate_noise(self, seconds=1.5):
        blocks = max(1, int(seconds * bird.SR / HOP))
        rms = [self.flt.rms(self.read()[:, 0]) for _ in range(blocks)]
        return float(np.clip(np.median(rms), bird.NOISE_FLOOR_MIN,
                             bird.NOISE_FLOOR_MAX))

    def _flush(self, seconds=0.6):
        """Discard what the mic heard while we were playing (+ room tail)."""
        for _ in range(int(seconds * bird.SR / HOP)):
            self.read()

    def play(self, audio):
        if audio is None or len(audio) == 0:
            return
        audio = np.asarray(audio, dtype=np.float32)
        self._pending = sps.resample_poly(audio, RATIO, 1).astype(np.float32)
        self._pos = 0
        while self._pending is not None:
            self.read()                  # keeps capture flowing, drains playback
        self._flush()                    # don't hear ourselves
        if self.wake is not None:
            self.wake.reset()

    def cue(self, name):
        log(f"cue: {name}")
        self.play(self.cues[name])

    def say_phrase(self, why):
        self._reload_phrase()
        if self.phrase is None:
            log(f"{why}: nothing to whistle yet")
            self.cue("nothing")
            return
        log(f"{why}: whistling the phrase")
        self.play(self.phrase)

    # -- LISTEN mode ------------------------------------------------------
    def listen(self):
        """Feed the mic to the wake model until the button is pressed."""
        log("LISTENING for the wake word")
        buf = np.zeros(0, dtype=np.float32)
        up, down, in_chunk = _wake_ratio()
        while True:
            src = self.buttons.pressed()
            if src:
                log(f"button pressed ({src})")
                return
            try:
                why = self.play_requests.get_nowait()
                self.say_phrase(why)
                buf = buf[:0]
                continue
            except queue.Empty:
                pass
            block = self.read()
            if self.wake is None:
                continue
            buf = np.concatenate([buf, block[:, 0]])
            if len(buf) < in_chunk:
                continue
            chunk, buf = buf[:in_chunk], buf[in_chunk:]
            x16 = (chunk if up == down else
                   sps.resample_poly(chunk, up, down)).astype(np.float32)
            hit = self.wake.feed(x16)
            if hit and time.time() - self.last_wake > WAKE_COOLDOWN:
                self.last_wake = time.time()
                log(f"wake word! ({hit})")
                self.peers.broadcast_play()
                self.say_phrase("wake")
                buf = buf[:0]

    # -- TRAIN mode -------------------------------------------------------
    def _record_phrase(self, noise):
        """bird.record_phrase, but abortable by the button at ANY moment
        (a press mid-capture throws the capture away — the previous answer
        is what the user wants to keep). Returns (audio, peak level) or
        None if the button was pressed."""
        onset = max(noise * bird.ONSET_FACTOR, TRAIN_MIN_LEVEL)
        release = noise * bird.RELEASE_FACTOR
        preroll, captured = [], []
        recording, silent, peak = False, 0, 0.0
        silence_limit = int(bird.SILENCE_HOLD * bird.SR / HOP)
        max_blocks = int(bird.MAX_PHRASE * bird.SR / HOP)
        while True:
            src = self.buttons.pressed()
            if src:
                if recording:
                    print()
                    log(f"button pressed ({src}) — capture in progress discarded")
                else:
                    log(f"button pressed ({src})")
                return None
            block = self.read()
            mono = block[:, 0].copy()
            rms = self.flt.rms(mono)
            if not recording:
                preroll.append(mono)
                if len(preroll) > bird.PREROLL:
                    preroll.pop(0)
                if rms > onset:
                    recording = True
                    captured = list(preroll)
                    print("  ... listening", end="", flush=True)
            else:
                captured.append(mono)
                peak = max(peak, rms)
                if rms < release:
                    silent += 1
                    if silent >= silence_limit:
                        break
                else:
                    silent = 0
                if len(captured) >= max_blocks:
                    break
        print()
        return np.concatenate(captured), peak

    def train(self):
        log("TRAINING: calibrating room noise ...")
        noise = self._calibrate_noise()
        self.cue("listening")
        log(f"TRAINING: whistle something (noise floor {noise:.4f}, onset above "
            f"{max(noise * bird.ONSET_FACTOR, TRAIN_MIN_LEVEL):.3f}); "
            "press the button when you like the last answer")
        draft = None
        while True:
            got = self._record_phrase(noise)
            if got is None:                 # button
                break
            phrase, level = got
            t_render = time.time()
            f0, voiced, loud = bird.analyze(phrase, fmin=self.fmin)
            f0, voiced, loud = clean_contour(f0, voiced, loud)
            if voiced.sum() < 12:
                log(f"  (no clear whistle, level {level:.3f} — try again)")
                continue
            vf = f0[voiced]
            log(f"  heard {len(phrase) / bird.SR:.1f}s, level {level:.3f}, "
                f"pitch {vf.min():.0f}-{vf.max():.0f} Hz — rendering")
            reply = bird.render_reply(f0, voiced, loud, VOICE["birdiness"],
                                      VOICE["reverb"], self.corpus,
                                      VOICE["texture"],
                                      shift=bird._resolve_shift(VOICE["shift"], vf),
                                      dry=VOICE["dry"], stages=VOICE["stages"],
                                      tail=VOICE["tail"], bend=VOICE["bend"])
            if len(reply) == 0:
                continue
            # a press that arrived while we were analysing/rendering means
            # "keep what you had" — this capture was not wanted
            src = self.buttons.pressed()
            if src:
                log(f"button pressed ({src}) during processing — "
                    "keeping the previous answer")
                break
            draft = reply
            log(f"  bird answers ({time.time() - t_render:.1f}s to process) — whistle again or press")
            self.play(reply)
            # a press during the reply counts as "keep this one"
            src = self.buttons.pressed()
            if src:
                log(f"button pressed ({src})")
                break
        if draft is None:
            log("TRAINING over: nothing recorded, phrase unchanged")
            self.cue("nothing")
            return
        if os.path.exists(LAKI_OUT):
            import shutil
            shutil.copy2(LAKI_OUT, LAKI_PREV)      # one-step undo
        save_wav(LAKI_OUT, draft)
        log(f"TRAINING over: phrase stored -> {LAKI_OUT} (previous kept as {os.path.basename(LAKI_PREV)})")
        self._reload_phrase()
        self.cue("stored")
        self.peers.push_phrase()

    # -- main -------------------------------------------------------------
    @staticmethod
    def find_devices():
        """(capture index, playback index) of the I2S card. The simple-card
        overlay exposes them as two separate ALSA PCMs (hw:0,1 in, hw:0,0
        out), so sounddevice sees two devices; PortAudio joins them into one
        duplex stream."""
        import sounddevice as sd
        cap = play = None
        for i, d in enumerate(sd.query_devices()):
            if AUDIO_CARD not in d["name"]:
                continue
            if cap is None and d["max_input_channels"] > 0:
                cap = i
            if play is None and d["max_output_channels"] > 0:
                play = i
        if cap is None or play is None:
            raise RuntimeError(f"no '{AUDIO_CARD}' capture+playback devices "
                               f"(in={cap}, out={play})")
        return cap, play

    def open_stream(self):
        """ONE full-duplex stream in the card's native format, opened once
        and kept running for the whole session."""
        import sounddevice as sd
        try:
            cap, play = self.find_devices()
            self._devices = (cap, play)
            return sd.Stream(device=(cap, play), samplerate=STREAM_SR,
                             channels=2, dtype="int16", blocksize=HOP * RATIO,
                             latency=STREAM_LATENCY)
        except Exception as e:
            log(f"cannot open the I2S sound card ({e})")
            bird._explain_no_device()
            sys.exit(2)

    def run(self):
        started = bird._startup_watchdog()
        self._gain = output_gain()
        self.stream = self.open_stream()
        log(f"audio: {AUDIO_CARD} in=#{self._devices[0]} out=#{self._devices[1]} "
            f"duplex {STREAM_SR} Hz / 2 ch S16, engine {ENGINE_SR} Hz, "
            f"block {HOP * RATIO} ({1000 * HOP / bird.SR:.0f} ms), never restarted")
        with self.stream:
            primed = self._prime()
            lat = self.stream.latency
            log(f"audio: output lead {primed:.0f} ms, buffers in {lat[0] * 1000:.0f} ms "
                f"/ out {lat[1] * 1000:.0f} ms")
            self.read()                 # first block flowing
            started.set()
            threading.Thread(target=self._stall_watchdog, daemon=True).start()
            self.buttons.start_all()
            self.cue("ready")
            while True:
                self.listen()
                self.train()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-wake", action="store_true",
                    help="skip the wake-word model (button/peers only)")
    ap.add_argument("--debug", action="store_true",
                    help="print openwakeword scores > 0.1")
    ap.add_argument("--wake", choices=["sherpa", "oww"], default=WAKE_BACKEND,
                    help="wake-word backend (default %(default)s)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="override the backend's detection threshold")
    v = ap.add_argument_group("voice (override the VOICE dict for this run; "
                              "same meaning as bird.py's flags)")
    v.add_argument("--birdiness", type=float, help="0 faithful whistle .. 1 full bird")
    v.add_argument("--reverb", type=float, help="0 dry .. 1 drenched")
    v.add_argument("--dry", type=float, help="direct-voice level 0..1")
    v.add_argument("--stages", type=int, help="serial reverb passes 1-3")
    v.add_argument("--tail", type=float, help="reverb tail seconds")
    v.add_argument("--texture", type=float, help="bird-grain morph 0 tone .. 1 bird")
    v.add_argument("--shift", type=float, help="semitones above the input (default: auto)")
    v.add_argument("--bend", type=float, help="max per-note random bend, semitones")
    v.add_argument("--hum", type=int, choices=[0, 1], help="1 = also accept hummed input (default 1)")
    args = ap.parse_args()
    for k in ("birdiness", "reverb", "dry", "stages", "tail", "texture", "shift", "bend", "hum"):
        val = getattr(args, k)
        if val is not None:
            VOICE[k] = bool(val) if k == "hum" else val
    log("voice: " + ", ".join(f"{k}={v}" for k, v in VOICE.items()))

    signal.signal(signal.SIGTERM, bird._sigterm)
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)   # a press before we're ready
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    laki = Laki(args)
    try:
        laki.setup()
        laki.run()
    except KeyboardInterrupt:
        log("bye")
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
