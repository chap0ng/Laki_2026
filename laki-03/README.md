# laki-03 — a RECEIVER

A listening bird. It never records anything. It waits for the raw whistle that
laki-01 sends it, re-sings it **in its own voice**, and joins the chorus when
laki-01 broadcasts PLAY.

| | |
|---|---|
| hostname | `laki-03` |
| board | Raspberry Pi **Zero W v1** (32-bit, `armv6l`, one core, 512 MB) |
| role | **receiver** — no `laki-send.sh`, which is what makes it a receiver |
| wake word | none (runs with `--no-wake`) |
| pitch | **auto, then +1 semitone** (`LAKI_SHIFT_OFFSET=1`, no `--shift` line) |
| password | `--Ask pool numerique--` |

## Its voice

```sh
export LAKI_VOLUME=75
export LAKI_PRIME_MS=400
export LAKI_LATENCY=0.3
export LAKI_TRAIN_LEVEL=0.08
export LAKI_SHIFT_OFFSET=1
--birdiness 0.1  --reverb 0.2  --dry 0.65  --stages 1
--tail 0.9  --texture 0.1  --bend 0.2  --hum 1
# no --shift line on purpose - see below
```

### Why `LAKI_SHIFT_OFFSET` and not `--shift 1`

This bird is tuned to sit **one semitone above laki-01**. laki-01 runs on
**auto**, and auto depends on the whistle, so there is no fixed number to write.
Giving `--shift` a number would switch auto **off** — `--shift 1` would mean "one
semitone above the *whistle*", which is a different thing entirely.

`LAKI_SHIFT_OFFSET` is a small local patch in `bird.py`: it adds its value on top
of whatever shift is in force, auto or not. All four birds carry the patch; it
does nothing (`0.0`) where the variable is not set.

It shares laki-02 timbre, so the two differ only in register. This is the
highest-pitched bird of the flock.

## Things that are true of every receiver

- **`LAKI_PRIME_MS=400` is mandatory** on a Zero W v1. At 200 the output
  crackles: the first playback step stalls ~293 ms while upsampling.
- `peers.txt` is **empty on purpose** — a receiver pushes to nobody.
- It takes **~17 s** to render a new melody (one ARMv6 core). During that time a
  chorus still plays the *previous* one. That is normal.
- ~85 s from service start to "waiting": a random 10-25 s stagger, plus importing
  numpy and scipy on one core.

## Day to day

```bash
systemctl status laki          # is it alive
tail -f /tmp/laki.log          # what it is doing
sudo systemctl restart laki    # after editing laki.conf
```

Expected in the log: `mode: RECEIVER`, `output lead 400 ms` (proof
`laki.conf` was read), `RECEIVER: waiting for a peer's PLAY broadcast`.

Full tutorial for someone who has never touched it: `../SOUND_SETUP.md`.
