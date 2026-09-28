#!/usr/bin/env python3
"""Add a --receiver mode to laki.py: no wake word, no training, the button is
ignored; the bird only sings the shared pattern when a peer broadcasts PLAY.
Run once per Pi (after patch_pattern.py):  python3 patch_receiver.py ~/laki/laki.py"""
import sys, os, shutil, time, py_compile

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/laki/laki.py")
src = open(path).read()
if "--receiver" in src:
    sys.exit("already patched: " + path)
if "LAKI_IN" not in src:
    sys.exit("apply patch_pattern.py first: " + path)

edits = []
def rep(old, new):
    edits.append((old, new))

# flag
rep('''    ap.add_argument("--no-wake", action="store_true",
                    help="skip the wake-word model (button/peers only)")
''', '''    ap.add_argument("--no-wake", action="store_true",
                    help="skip the wake-word model (button/peers only)")
    ap.add_argument("--receiver", action="store_true",
                    help="receive-only bird: no wake word, no training, button "
                         "ignored; sings the shared pattern on a peer's broadcast")
''')
rep("    args = ap.parse_args()\n",
    "    args = ap.parse_args()\n"
    "    if args.receiver:\n"
    "        args.no_wake = True\n")
rep('''    log("voice: " + ", ".join(f"{k}={v}" for k, v in VOICE.items()))
''', '''    log("voice: " + ", ".join(f"{k}={v}" for k, v in VOICE.items()))
    if args.receiver:
        log("mode: RECEIVER - no wake word, no training; sings the shared "
            "pattern (sounds/laki_in.wav) when a peer broadcasts PLAY")
''')

# listen loop: a receiver never leaves listen()
rep('''        log("LISTENING for the wake word")
''', '''        log("RECEIVER: waiting for a peer's PLAY broadcast" if self.args.receiver
            else "LISTENING for the wake word")
''')
rep('''            src = self.buttons.pressed()
            if src:
                log(f"button pressed ({src})")
                return
''', '''            src = self.buttons.pressed()
            if src:
                if self.args.receiver:
                    log(f"button pressed ({src}) - ignored, this bird is a receiver")
                    continue
                log(f"button pressed ({src})")
                return
''')

for old, new in edits:
    n = src.count(old)
    if n != 1:
        sys.exit(f"anchor found {n} times, expected 1:\n{old[:90]!r}")
    src = src.replace(old, new)

bak = path + ".bak-receiver-" + time.strftime("%Y%m%d")
shutil.copy2(path, bak)
open(path, "w").write(src)
py_compile.compile(path, doraise=True)
print(f"patched {path} ({len(edits)} edits), backup {bak}, compiles OK")
