# laki-04 — a RECEIVER

A listening bird. It never records anything. It waits for the raw whistle that
laki-01 sends it, re-sings it **in its own voice**, and joins the chorus when
laki-01 broadcasts PLAY.

| | |
|---|---|
| hostname | `laki-04` |
| board | Raspberry Pi **Zero W v1** (32-bit, `armv6l`, one core, 512 MB) |
| role | **receiver** — no `laki-send.sh`, which is what makes it a receiver |
| wake word | none (runs with `--no-wake`) |
| pitch | **`--shift -11`** — one semitone above laki-02, same low octave. |
| password | `--Ask pool numerique--` |

## Its voice

```sh
export LAKI_VOLUME=75
export LAKI_PRIME_MS=400
export LAKI_LATENCY=0.3
export LAKI_TRAIN_LEVEL=0.08
--birdiness 0.3  --reverb 0.12  --dry 0.7  --stages 1
--tail 0.6  --texture 0.25  --bend 0.3  --hum 1
--shift -11
```

It shares laki-01 timbre exactly. It used to be `-12`, identical to laki-02,
so the two sang in unison; moving it to `-11` makes them beat gently against each
other instead.

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
