#!/usr/bin/env python3
"""Sender only - make the 'nest' waiting cue a longer, breathing phrase.

The first nest was two notes, 1.2 s, repeating every 2.4 s. Correct in
character but too insistent over a twenty-second wait. This replaces it with

    bi boup ...  la la la ...  bi ...  la la ...  looo ...

about 6 s of sound and then it breathes - roughly two phrases per waiting
window instead of eight. Same register, same softness, same synth.

It also teaches `_contour` a fourth value per note: the pause AFTER that note,
overriding the uniform gap. Without it every silence in a cue is the same
length and the phrase cannot breathe. Existing 3-value notes are unaffected, so
the other cues keep working untouched.

    python3 patch_wait_nest_long.py ~/laki/laki.py      (laki-01 only)

Needs patch_wait_cue.py applied first. Idempotent, checks its anchors, dated
backup, py_compile before replacing the file.
"""
import os
import py_compile
import sys
import time

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/laki/laki.py")
if not os.path.isfile(path):
    sys.exit(f"no such file: {path}")

src = open(path, encoding="utf-8").read()
if "LAKI_WAIT_CUE" not in src:
    sys.exit("apply patch_wait_cue.py first: " + path)
if "bi boup" in src:
    sys.exit("already patched (nest-long): " + path)

# ------------------------------------------- 1. per-note pauses in _contour
A1 = '''def _contour(notes, gap=0.05):
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
'''
B1 = '''def _contour(notes, gap=0.05):
    """notes = [(f_start, f_end, seconds), ...] -> (f0, voiced, loud) frames.

    A note may carry a FOURTH value: the pause after it, overriding `gap` for
    that note only. Without it every silence in a cue is the same length and
    the phrase cannot breathe - which is the whole difference between a beep
    repeating and "bi boup ... la la la ...". Three-value notes are unaffected,
    so the cues written before this keep sounding exactly as they did."""
    f0, voiced, loud = [], [], []
    for note in notes:
        f_a, f_b, dur = note[:3]
        pause = note[3] if len(note) > 3 else gap   # NOT reassigning `gap`:
        n = max(2, int(dur * bird.SR / HOP))        # it must stay the default
        f0.extend(np.geomspace(f_a, f_b, n))
        voiced.extend([True] * n)
        env = np.sin(np.linspace(0, np.pi, n)) ** 0.5   # soft in/out
        loud.extend(0.05 + 0.15 * env)
        g = int(pause * bird.SR / HOP)
        f0.extend([0.0] * g)
        voiced.extend([False] * g)
        loud.extend([0.0] * g)
    return np.array(f0), np.array(voiced), np.array(loud)
'''

# ------------------------------------------------------ 2. the longer nest
A2 = '''        #   nest: two low soft descending notes, a settled pulse. Calm.
        "wait_nest":     render([(900, 820, 0.11), (840, 760, 0.13)], gap=0.08),
'''
B2 = '''        #   nest: "bi boup ... la la la ... bi ... la la ... looo ...".
        #   ~6 s of sound, then it breathes. Low, soft, unhurried: over a
        #   twenty-second wait it plays about twice, not eight times. The
        #   fourth number on a note is the pause after it - the pauses carry
        #   the calm as much as the notes do.
        "wait_nest":     render([(980, 1060, 0.08),              # bi
                                 (900,  800, 0.13, 0.55),        # boup   --
                                 (820,  795, 0.10),              # la
                                 (805,  780, 0.10),              # la
                                 (790,  750, 0.14, 0.70),        # laa    ----
                                 (1010, 1090, 0.07, 0.50),       # bi     --
                                 (800,  775, 0.10),              # la
                                 (785,  755, 0.12, 0.60),        # la     ---
                                 (770,  690, 0.28, 0.95)],       # looo   -----
                                gap=0.07),
'''

for name, anchor in (("_contour", A1), ("wait_nest", A2)):
    n = src.count(anchor)
    if n != 1:
        sys.exit(f"anchor '{name}' found {n} time(s), want exactly 1 "
                 f"- nothing changed")

out = src.replace(A1, B1).replace(A2, B2)

bak = f"{path}.bak-nestlong-{time.strftime('%Y%m%d-%H%M%S')}"
tmp = path + ".new"
open(tmp, "w", encoding="utf-8", newline="\n").write(out)
try:
    py_compile.compile(tmp, doraise=True)
except py_compile.PyCompileError as e:
    os.remove(tmp)
    sys.exit(f"the patched file does not compile, nothing changed:\n{e}")
os.replace(path, bak)
os.replace(tmp, path)
print(f"patched (nest-long): {path}   backup: {bak}")
print("the phrase now ends with its own long pause, so lower LAKI_WAIT_EVERY")
print("to about 0.6 in laki.conf, then restart laki")
