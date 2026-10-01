#!/usr/bin/env python3
"""Render laki-01's cues to .wav, exactly as the bird plays them.

    cd ~/laki && PYTHONPATH=$HOME/laki .venv/bin/python /tmp/preview_wait_cues.py /tmp/cues

It imports laki.py and calls its own make_cues(), so what you hear IS what the
bird plays - no reimplementation to drift out of sync. That matters more than it
sounds: laki.py sets `bird.SR = 16000` at import and takes `HOP = 256` from
bird, so any preview that guesses those values renders at the wrong speed.

Each file shows the cue as actually heard: the phrase, then LAKI_WAIT_EVERY
seconds of silence, repeated for ~30 s - about one real waiting window.
"""
import os
import sys

import numpy as np
import soundfile as sf

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cues"
sys.argv = [sys.argv[0]]           # laki.py parses argv at import, keep it clean

import laki                        # noqa: E402  (sets bird.SR, imports HOP)
import bird                        # noqa: E402

os.makedirs(OUT, exist_ok=True)

EVERY = float(os.environ.get("LAKI_WAIT_EVERY", 1.2))
TOTAL = 30.0

print(f"bird.SR = {bird.SR}   HOP = {laki.HOP}   "
      f"birdiness = {laki.VOICE['birdiness']}")

cues = laki.make_cues()
for name in sorted(cues):
    one = np.asarray(cues[name], dtype=np.float32)
    gap = np.zeros(int(EVERY * bird.SR), dtype=np.float32)
    loop = []
    while sum(len(x) for x in loop) < TOTAL * bird.SR:
        loop.append(one)
        loop.append(gap)
    audio = np.concatenate(loop)[: int(TOTAL * bird.SR)]
    path = os.path.join(OUT, f"{name}.wav")
    sf.write(path, audio, bird.SR)
    print(f"  {name:16s} phrase {len(one)/bird.SR:5.2f}s, "
          f"repeats every {len(one)/bird.SR + EVERY:5.2f}s")
