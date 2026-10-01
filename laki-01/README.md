# laki-01 — the SENDER

The only bird you whistle into. It records your melody, pushes it to the three
receivers, and starts the chorus when it hears the wake word.

| | |
|---|---|
| hostname | `laki-01` (its user is the one without a number) |
| board | Raspberry Pi **Zero 2 W** (64-bit, `aarch64`) |
| role | **sender** — has `laki-send.sh`, which is what makes it the sender |
| wake word | **"Lucky"** / "Hey Lucky" (sherpa-onnx, threshold 0.3) |
| pitch | **auto** — no `--shift` line. The reply is lifted toward 1200 Hz |
| password | `--Ask pool numerique--` |

## Its voice

```sh
export LAKI_VOLUME=75
export LAKI_PRIME_MS=200        # 200 is fine here: a Zero 2 W has 4 cores
export LAKI_LATENCY=0.3
export LAKI_TRAIN_LEVEL=0.08
export LAKI_ECHO_DELAY=3        # sender only: silence after sending, then it sings again
export LAKI_ECHO_PEER_WAIT=15   # sender only: max wait for the rsyncs to land
--birdiness 0.3  --reverb 0.12  --dry 0.7  --stages 1
--tail 0.6  --texture 0.25  --bend 0.3  --hum 1
# no --shift line = AUTO
```

## What is special about it

- It is the **only** bird with a wake word. `sherpa-onnx` has no ARMv6 build, so
  a Pi Zero W v1 can never be the sender — that is why this one is a Zero 2 W.
- It is the only one with `peers.txt` filled in. It is read **once at startup**:
  after editing it, restart the service.
- It renders roughly **10x faster** than the receivers (~2 s vs ~17 s) because it
  has four cores.

## While the flock gets ready — the waiting sound

After you whistle and accept, three things used to happen in **silence**: the raw
whistle was sent to the three receivers, they each spent ~17 s re-rendering it in
their own voice, and then laki-01 whistled the melody **alone** — too early for
the others to join.

Now the sender fills that window and ends it properly:

1. it repeats a short **waiting cue** while the pattern is sent and rendered;
2. then it **broadcasts PLAY**, so **all four birds sing the new melody
   together** — the same path the wake word uses.

```sh
export LAKI_WAIT_CUE=nest       # nest | question | tick | off
export LAKI_WAIT_EVERY=1.2      # seconds between two repeats
export LAKI_PEER_RENDER=18      # seconds given to the receivers to render
```

The three cues are built with the **same synth as the bird's own voice** — they
are tiny whistles, not samples:

| name | what it sounds like | when to pick it |
|---|---|---|
| `nest` | a phrase: **bi boup … la la la … bi … la la … looo …** — 3.8 s of low soft notes and 1.2 s of breath, repeating about every 6 s | calm and unhurried; it plays ~3 times across the wait instead of eight. **Default** |
| `question` | a rising pair — the interrogative chirp, ~0.9 s | more present; reads as expectation, "is it there yet?" |
| `tick` | three tiny high clicks, ~0.9 s | the most mechanical; use it if you want the processing to be audible |

`off` keeps the timing but stays silent. `LAKI_ECHO_DELAY=0` turns the whole
after-whistle behaviour off, as before. A **button press at any moment** skips the
rest and starts a new capture — though with `nest` the press is only read between
phrases, so it can take up to ~5 s to register. It is never lost.

> `LAKI_PEER_RENDER=18` is sized for a Zero W v1 receiver (~17 s per melody). If
> the flock ever runs on faster boards, lower it and the chorus comes sooner.

### The pauses are part of the cue

A note in a cue is `(start Hz, end Hz, seconds)` and may carry a **fourth value:
the pause after it**. Without that, every silence in a phrase is the same length
and the cue can only be an even stream of beeps — the fourth value is what lets
`nest` breathe in groups. Three-value notes keep the uniform `gap`, so the older
cues are untouched.

### To hear them before choosing

```bash
# from the PC, with this repository checked out
scp tools/preview_wait_cues.py laki-01:/tmp/
ssh laki-01 'cd ~/laki && PYTHONPATH=$HOME/laki .venv/bin/python /tmp/preview_wait_cues.py /tmp/cues'
scp 'laki-01:/tmp/cues/*.wav' .
```

It imports `laki.py` and calls its **own** `make_cues()`, so the files are what
the bird actually plays. Do not reimplement the cue builder in a preview: `laki.py`
sets `bird.SR = 16000` and takes `HOP = 256` from `bird`, and a preview that
guesses those renders at the wrong speed.

## Day to day

```bash
systemctl status laki          # is it alive
tail -f /tmp/laki.log          # what it is doing
sudo systemctl restart laki    # after editing laki.conf or peers.txt
```

Full tutorial for someone who has never touched it: `../SOUND_SETUP.md`.
