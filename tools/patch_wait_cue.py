#!/usr/bin/env python3
"""Sender only - a waiting sound while the flock gets ready, then a real chorus.

Today, after you whistle and accept, laki-01 goes SILENT: it rsyncs the raw
whistle to the peers, waits ECHO_PEER_WAIT for the transfers, waits ECHO_DELAY
(3 s) more, and then whistles the melody ALONE. Meanwhile the receivers are
still rendering - an ARMv6 core needs ~17 s - so they are not ready in time and
the flock never actually sings the new melody together.

This patch changes both halves:

  1. WAITING SOUND. While the pattern is being sent and rendered, the sender
     repeats a short cue built with the same synth as the existing cues, so the
     room hears that something is happening. Three are provided, pick by ear:

       nest      two low soft descending notes, a slow settled pulse.
                 Calm, sits under the room, bearable for twenty seconds.
       question  a rising pair - the interrogative chirp, "is it there yet?".
                 More present, reads as expectation.
       tick      three tiny high clicks, a small mechanism at work.
                 The most "machine", good if you want the processing audible.

     LAKI_WAIT_CUE=nest|question|tick|off     (off = silent, timing unchanged)

  2. A REAL CHORUS. Once the peers have had PEER_RENDER seconds to render, the
     sender broadcasts PLAY - exactly what the wake word does - so ALL FOUR
     birds sing the new melody together, instead of the sender echoing alone.

New variables, all settable in laki.conf:
    LAKI_WAIT_CUE     nest (default) | question | tick | off
    LAKI_WAIT_EVERY   1.2   seconds between two repeats of the cue
    LAKI_PEER_RENDER  18    seconds given to the peers before the chorus

Unchanged: LAKI_ECHO_DELAY=0 still turns the whole after-store behaviour off,
and a button press at any moment skips the rest and starts a new capture.

    python3 patch_wait_cue.py ~/laki/laki.py        (laki-01 only)

Idempotent: refuses if already applied, checks every anchor, dated backup,
py_compile before replacing the file.
"""
import os
import py_compile
import sys
import time

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/laki/laki.py")
if not os.path.isfile(path):
    sys.exit(f"no such file: {path}")

src = open(path, encoding="utf-8").read()
if "LAKI_WAIT_CUE" in src:
    sys.exit("already patched (wait-cue): " + path)
if "def _echo_after_store" not in src:
    sys.exit("this is not a sender laki.py (no _echo_after_store): " + path)

# --------------------------------------------------------------- 1. the knobs
A1 = ('ECHO_PEER_WAIT = float(os.environ.get("LAKI_ECHO_PEER_WAIT", 15.0))'
      ' # s at most spent waiting for the rsyncs to finish\n')
B1 = A1 + '''
# While the pattern travels to the peers and they render it in their own voice
# (~17 s on one ARMv6 core), the sender used to stand silent and then whistle
# alone. It now repeats a short waiting cue, and ends by broadcasting PLAY so
# the WHOLE FLOCK sings the new melody together.
WAIT_CUE = os.environ.get("LAKI_WAIT_CUE", "nest").strip().lower()  # nest|question|tick|off
WAIT_EVERY = float(os.environ.get("LAKI_WAIT_EVERY", 1.2))      # s between two repeats
PEER_RENDER = float(os.environ.get("LAKI_PEER_RENDER", 18.0))   # s given to the peers to render
'''

# ---------------------------------------------------------------- 2. the cues
A2 = """    def render(notes):
        f0, v, l = _contour(notes)
"""
B2 = """    def render(notes, gap=0.05):
        f0, v, l = _contour(notes, gap)
"""

A3 = '        "nothing":   render([(1200, 1000, 0.12), (1200, 1000, 0.12)]),\n    }\n'
B3 = '''        "nothing":   render([(1200, 1000, 0.12), (1200, 1000, 0.12)]),

        # Waiting cues - looped while the peers receive and render the pattern.
        # Pick one with LAKI_WAIT_CUE in laki.conf; they are deliberately short
        # and quiet, because they repeat for about twenty seconds.
        #   nest: two low soft descending notes, a settled pulse. Calm.
        "wait_nest":     render([(900, 820, 0.11), (840, 760, 0.13)], gap=0.08),
        #   question: a rising pair, the interrogative chirp. Expectant.
        "wait_question": render([(1150, 1800, 0.13), (1750, 1950, 0.09)], gap=0.06),
        #   tick: three tiny high clicks, a small mechanism at work.
        "wait_tick":     render([(2300, 2450, 0.05), (2300, 2450, 0.05),
                                 (2300, 2450, 0.05)], gap=0.07),
    }
'''

# ------------------------------------------------------- 3. the waiting logic
A4 = '''    def _echo_after_store(self, sent):
        """Send-then-sing: wait for the pattern to reach the peers, leave them
        ECHO_DELAY seconds to render it in their own voice, then whistle the new
        melody one more time. LAKI_ECHO_DELAY=0 turns the repeat off. A button
        press during the pause skips it - the press is left in the queue, so
        listen() picks it up at once and a new capture starts."""
        if ECHO_DELAY <= 0:
            return
        pressed = lambda: self.buttons.q.qsize() > 0      # peek, do not consume
        if sent:
            self._wait_draining(ECHO_PEER_WAIT,
                                until=lambda: pressed() or
                                not any(t.is_alive() for t in sent))
        if not pressed():
            log(f"echo: singing the new melody again in {ECHO_DELAY:.1f}s "
                f"(the peers render it meanwhile)")
            self._wait_draining(ECHO_DELAY, until=pressed)
        if pressed():
            log("echo: button pressed - repeat skipped")
            return
        self.say_phrase("echo")
'''

B4 = '''    def _echo_after_store(self, sent):
        """Send-then-sing, in three phases, and never silent for them:

          1. the raw whistle is rsynced to the peers. We wait for the transfers,
             repeating the waiting cue so the room hears it is working.
          2. the peers need ~17 s on one ARMv6 core to re-render the melody in
             their own voice. We keep the cue going for PEER_RENDER seconds.
          3. PLAY is broadcast and the WHOLE FLOCK sings the new melody
             together - the same path the wake word uses.

        LAKI_ECHO_DELAY=0 turns all of this off. LAKI_WAIT_CUE=off keeps the
        timing but stays silent. A button press at any moment skips the rest -
        the press is left in the queue, so listen() picks it up at once and a
        new capture starts."""
        if ECHO_DELAY <= 0:
            return
        pressed = lambda: self.buttons.q.qsize() > 0      # peek, do not consume
        cue = None if WAIT_CUE in ("off", "none", "") \\
            else self.cues.get("wait_" + WAIT_CUE)
        if cue is None and WAIT_CUE not in ("off", "none", ""):
            log(f"wait cue: unknown name '{WAIT_CUE}' - staying silent "
                f"(use nest, question, tick or off)")

        def hold(seconds, until=None):
            """Wait, repeating the cue, while still reading the mic. True if
            it stopped early (button, or until() became true)."""
            done = lambda: pressed() or (until is not None and until())
            t_end = time.time() + max(seconds, 0.0)
            while time.time() < t_end:
                if done():
                    return True
                if cue is not None:
                    self.play(cue)
                left = t_end - time.time()
                if left <= 0:
                    break
                if self._wait_draining(min(WAIT_EVERY, left), until=done):
                    return True
            return done()

        if sent:
            log(f"sending the pattern to {len(sent)} peer(s)"
                + ("" if cue is None else f", waiting cue '{WAIT_CUE}'"))
            hold(ECHO_PEER_WAIT, until=lambda: not any(t.is_alive() for t in sent))
        if not pressed():
            log(f"peers have the pattern - {PEER_RENDER:.0f}s for them to render "
                f"it, then the whole flock sings")
            hold(PEER_RENDER)
        if pressed():
            log("button pressed - chorus skipped")
            return
        self.peers.broadcast_play()     # everyone sings, not this bird alone
        self.say_phrase("chorus")
'''

for name, anchor in (("knobs", A1), ("render helper", A2),
                     ("cues dict", A3), ("_echo_after_store", A4)):
    n = src.count(anchor)
    if n != 1:
        sys.exit(f"anchor '{name}' found {n} time(s), want exactly 1 "
                 f"- nothing changed")

out = src.replace(A1, B1).replace(A2, B2).replace(A3, B3).replace(A4, B4)

bak = f"{path}.bak-waitcue-{time.strftime('%Y%m%d-%H%M%S')}"
tmp = path + ".new"
open(tmp, "w", encoding="utf-8", newline="\n").write(out)
try:
    py_compile.compile(tmp, doraise=True)
except py_compile.PyCompileError as e:
    os.remove(tmp)
    sys.exit(f"the patched file does not compile, nothing changed:\n{e}")
os.replace(path, bak)
os.replace(tmp, path)
print(f"patched (wait-cue): {path}   backup: {bak}")
print("set LAKI_WAIT_CUE=nest|question|tick|off in laki.conf, then restart laki")
