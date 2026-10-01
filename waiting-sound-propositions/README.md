# Waiting cues — listen before you choose

The sound laki-01 repeats while it sends your melody to the other three birds
and they rebuild it in their own voice (about twenty seconds). Set the one you
want with `LAKI_WAIT_CUE` in laki-01's `laki.conf`, then restart the service.

| file | `LAKI_WAIT_CUE=` | phrase | character |
|---|---|---|---|
| `wait_nest.wav` | `nest` | 4.96 s | *bi boup … la la la … bi … la la … looo …* — low, soft, with pauses between the groups. Calm and unhurried; plays about three times across the wait. **The default** |
| `wait_question.wav` | `question` | 0.91 s | a rising chirp, the interrogative. More present, reads as expectation |
| `wait_tick.wav` | `tick` | 0.94 s | three tiny high clicks, a small mechanism at work |

`off` keeps the same timing but stays silent.

Each file is 12 s: the phrase, then `LAKI_WAIT_EVERY` (1.2 s) of silence,
repeating — exactly as you would hear it standing in the room.

They are **not samples.** Every one is built from the same synth the birds sing
with, from a list of `(start Hz, end Hz, seconds, pause after)` notes in
`laki-01/laki.py` (`make_cues`). To hear a change you made, re-render them with
`tools/preview_wait_cues.py` — it imports `laki.py` and calls its own
`make_cues()`, so the files are always what the bird really plays.
