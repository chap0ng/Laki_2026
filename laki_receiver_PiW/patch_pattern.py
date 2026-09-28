#!/usr/bin/env python3
"""Pattern sharing: peers receive the RAW whistle (laki_in.wav) and each bird
renders it in its own voice.  Run once per Pi:  python3 patch_pattern.py ~/laki/laki.py
Refuses to run if any anchor is missing or the patch was already applied."""
import sys, os, shutil, time, py_compile

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/laki/laki.py")
src = open(path).read()
if "LAKI_IN" in src:
    sys.exit("already patched: " + path)

edits = []
def rep(old, new):
    edits.append((old, new))

# 1. imports
rep("import queue\nimport signal\n", "import queue\nimport shutil\nimport signal\n")

# 2. header doc
rep('''Peers: every hostname in peers.txt gets the new phrase (rsync) when it is
stored, and a UDP "PLAY" broadcast when the wake word fires, so all birds
on the network whistle together.''',
'''Peers: every hostname in peers.txt gets the new PATTERN - the raw whistle,
sounds/laki_in.wav - by rsync when it is stored. Each bird renders that
pattern in ITS OWN voice (laki.conf / --flags) into sounds/laki_out.wav, at
arrival and again at every start (so a tuning change re-voices the pattern).
A UDP "PLAY" broadcast when the wake word fires makes all birds whistle the
same melody together, each with its own timbre.''')

# 3. constants
rep('LAKI_PREV = os.path.join(SOUNDS_DIR, "laki_out.prev.wav")   # the phrase before the last store (undo: mv it back)\n',
    'LAKI_PREV = os.path.join(SOUNDS_DIR, "laki_out.prev.wav")   # the phrase before the last store (undo: mv it back)\n'
    'LAKI_IN = os.path.join(SOUNDS_DIR, "laki_in.wav")           # the PATTERN: raw whistle shared with peers, rendered locally\n')

# 4. rsync sends the raw pattern
rep('r = subprocess.run(["rsync", "-q", "--timeout=20", LAKI_OUT,',
    'r = subprocess.run(["rsync", "-q", "--timeout=20", LAKI_IN,')
rep('log(f"peers: phrase sent to {host}")', 'log(f"peers: pattern (raw whistle) sent to {host}")')

# 5. state
rep("        self.phrase_mtime = 0.0\n",
    "        self.phrase_mtime = 0.0\n"
    "        self.raw_mtime = 0.0             # laki_in.wav we last rendered\n"
    "        self._rendering = False\n"
    "        self._raw_check = 0.0\n")

# 6. setup: render the pattern in this bird's voice at start
rep("        self._reload_phrase()\n        self._load_wake_model()\n",
    "        self._reload_phrase()\n        self._check_raw()                # re-voice the pattern with the current tuning\n        self._load_wake_model()\n")

# 7. reload doc + new methods
rep('''        """Pick up laki_out.wav if it changed (a peer may have rsynced it)."""''',
    '''        """Pick up laki_out.wav if it changed (re-rendered from a new pattern)."""''')
rep('''            log(f"phrase loaded ({len(self.phrase) / bird.SR:.1f}s)")

    # -- audio''',
'''            log(f"phrase loaded ({len(self.phrase) / bird.SR:.1f}s)")

    def _render(self, f0, voiced, loud):
        """Render an analysed contour in THIS bird's voice (VOICE dict)."""
        vf = f0[voiced]
        return bird.render_reply(f0, voiced, loud, VOICE["birdiness"],
                                 VOICE["reverb"], self.corpus,
                                 VOICE["texture"],
                                 shift=bird._resolve_shift(VOICE["shift"], vf),
                                 dry=VOICE["dry"], stages=VOICE["stages"],
                                 tail=VOICE["tail"], bend=VOICE["bend"])

    def _check_raw(self):
        """laki_in.wav is the PATTERN (raw whistle). When it is new - a peer
        rsynced it, or we just started - render it in our own voice, in the
        background so the audio loop keeps running."""
        try:
            m = os.path.getmtime(LAKI_IN)
        except OSError:
            return
        if m == self.raw_mtime or self._rendering:
            return
        self.raw_mtime = m
        self._rendering = True
        threading.Thread(target=self._render_raw, daemon=True).start()

    def _render_raw(self):
        try:
            t0 = time.time()
            raw = load_wav(LAKI_IN)
            f0, voiced, loud = bird.analyze(raw, fmin=self.fmin)
            f0, voiced, loud = clean_contour(f0, voiced, loud)
            if voiced.sum() < 12:
                log("pattern: no clear whistle in laki_in.wav - phrase unchanged")
                return
            reply = self._render(f0, voiced, loud)
            if len(reply) == 0:
                return
            if os.path.exists(LAKI_OUT):
                shutil.copy2(LAKI_OUT, LAKI_PREV)
            save_wav(LAKI_OUT, reply)
            log(f"pattern: laki_in.wav ({len(raw) / bird.SR:.1f}s) rendered in this "
                f"bird's voice in {time.time() - t0:.1f}s -> laki_out.wav")
        except Exception as e:
            log(f"pattern: render failed ({e})")
        finally:
            self._rendering = False

    # -- audio''')

# 8. listen loop polls for a new pattern once a second
rep("            block = self.read()\n            if self.wake is None:\n                continue\n",
    "            block = self.read()\n"
    "            if time.time() - self._raw_check > 1.0:\n"
    "                self._raw_check = time.time()\n"
    "                self._check_raw()\n"
    "            if self.wake is None:\n                continue\n")

# 9. train: use _render, keep the raw capture, store both
rep("        draft = None\n        while True:\n            got = self._record_phrase(noise)",
    "        draft = draft_raw = None\n        while True:\n            got = self._record_phrase(noise)")
rep('''            reply = bird.render_reply(f0, voiced, loud, VOICE["birdiness"],
                                      VOICE["reverb"], self.corpus,
                                      VOICE["texture"],
                                      shift=bird._resolve_shift(VOICE["shift"], vf),
                                      dry=VOICE["dry"], stages=VOICE["stages"],
                                      tail=VOICE["tail"], bend=VOICE["bend"])
''', "            reply = self._render(f0, voiced, loud)\n")
rep("            draft = reply\n", "            draft, draft_raw = reply, phrase\n")
rep('''        if os.path.exists(LAKI_OUT):
            import shutil
            shutil.copy2(LAKI_OUT, LAKI_PREV)      # one-step undo
        save_wav(LAKI_OUT, draft)
        log(f"TRAINING over: phrase stored -> {LAKI_OUT} (previous kept as {os.path.basename(LAKI_PREV)})")
''', '''        if os.path.exists(LAKI_OUT):
            shutil.copy2(LAKI_OUT, LAKI_PREV)      # one-step undo
        save_wav(LAKI_IN, draft_raw)               # the PATTERN - what peers receive
        self.raw_mtime = os.path.getmtime(LAKI_IN) # our render IS the draft: no re-render
        save_wav(LAKI_OUT, draft)
        log(f"TRAINING over: phrase stored -> {LAKI_OUT}, raw whistle -> {LAKI_IN} "
            f"(previous kept as {os.path.basename(LAKI_PREV)})")
''')

for old, new in edits:
    n = src.count(old)
    if n != 1:
        sys.exit(f"anchor found {n} times, expected 1:\n{old[:90]!r}")
    src = src.replace(old, new)

bak = path + ".bak-pattern-" + time.strftime("%Y%m%d")
shutil.copy2(path, bak)
open(path, "w").write(src)
py_compile.compile(path, doraise=True)
print(f"patched {path} ({len(edits)} edits), backup {bak}, compiles OK")
