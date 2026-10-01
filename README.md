# Laki — a flock of whistling birds

Four Raspberry Pi, each with a **ReSpeaker Lite** sound card and a small speaker.
You whistle a melody into one of them. The other three learn it, re-sing it **in
their own voice**, and the whole flock answers together when you say **"Lucky"**.

Same melody, four timbres. That is the whole idea.

---

## The flock

| Pi | role | board | voice | pitch |
|---|---|---|---|---|
| **[laki-01](laki-01/)** | **sender** | Zero 2 W (64-bit) | bright, light reverb | **auto** |
| **[laki-02](laki-02/)** | receiver | Zero W v1 (ARMv6) | round, long tail | **−12** (octave down) |
| **[laki-03](laki-03/)** | receiver | Zero W v1 (ARMv6) | round, long tail | **auto +1 semitone** |
| **[laki-04](laki-04/)** | receiver | Zero W v1 (ARMv6) | bright, light reverb | **−11** |

Two timbres, four distinct pitches. laki-01 and laki-04 share one voice colour,
laki-02 and laki-03 share the other.

> **Why only one sender?** The wake-word engine (`sherpa-onnx`) has no ARMv6
> build, so a Pi Zero W v1 can never listen for "Lucky". It makes a perfectly
> good receiver though — it just renders a melody in ~17 s instead of ~2 s.

---

## How it works

1. You press the button on **laki-01** and whistle. It records the raw whistle to
   `sounds/laki_in.wav`.
2. laki-01 **rsyncs that raw file** to the three receivers over SSH.
3. Each receiver notices the file changed, and **re-synthesises it with its own
   voice** into `sounds/laki_out.wav`. This is what makes the flock sing in
   chords rather than in unison. On an ARMv6 board that takes about 17 seconds —
   meanwhile laki-01 repeats a short **waiting cue** so the room hears it working.
4. When they have all had time to render, laki-01 broadcasts a UDP `PLAY` and
   **the whole flock sings your melody together**.
5. From then on, saying **"Lucky"** near laki-01 replays it any time.

Nothing here reaches the internet. The birds find each other by **mDNS `.local`
names**, answered by avahi running on the Pis themselves — no DNS server, no
DHCP, no internet needed. The whole flock works on a bare router.

---

## This repository

```
laki-01/  laki-02/  laki-03/  laki-04/   the CURRENT code of each bird, as it runs
SETUP.md                                 build a bird from nothing - the short version
SOUND_SETUP.md                           connect over SSH and tune the voices by hand
laki_Send_Pi2W/                          the long build guide for a sender
laki_receiver_PiW/                       the long build guide for a receiver, + shared assets
waiting-sound-propositions/              the waiting cues as .wav - listen before choosing
tools/                                   cue preview, and the patches that produced this code
```

- The four `laki-0X/` folders are **snapshots of what is actually running**:
  code, `laki.conf`, the systemd unit. That is where to look to answer "what is
  this bird doing right now", and what to restore from if one breaks.
- The two `laki_*_Pi*` folders are the **detailed build manuals** (wiring,
  flashing, I2S troubleshooting) and hold the **shared assets** the birds need:
  `birds/` (the hummingbird samples and the grain cache) and `sounds/`. Those are
  not duplicated per bird.

### Which file does what

| file | what it is |
|---|---|
| `laki.py` | the bird: audio stream, wake word, button, UDP, rsync, pattern watching |
| `bird.py` | synthesis and analysis: pitch tracking, reverb, the register shift |
| `mosaic.py` | the grain corpus built from `birds/*.wav` |
| `laki.conf` | **this bird's voice** — the only file that really differs between birds |
| `laki-send.sh` / `laki-receiver.sh` | the launcher. Its presence picks the role |
| `peers.txt` | sender only: who to push to. Read **once at startup** |
| `laki.service` | the systemd unit that starts the bird at boot |

---

## Credentials and network

Not published here, on purpose:

- SSH / `sudo` passwords: **`--Ask pool numerique--`**
- Wi-Fi network name and password: **`--Ask pool numerique--`**

Nothing in the code depends on these values — they are per-installation.

---

## Start here

- **You want to hear it and change how it sounds** → [`SOUND_SETUP.md`](SOUND_SETUP.md)
- **You want to build a fifth bird** → [`SETUP.md`](SETUP.md)
- **Something is broken** → the long guides in `laki_receiver_PiW/README.md`
  (receiver) or `laki_Send_Pi2W/README.md` (sender); both end with a
  troubleshooting table ordered by how often we actually needed it.
