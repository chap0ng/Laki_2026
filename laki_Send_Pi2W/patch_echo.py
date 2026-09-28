#!/usr/bin/env python3
"""Send-then-sing (SENDER only): once a melody is accepted, the pattern is sent
to the peers and the bird whistles it ONE MORE TIME after a short pause, so the
receivers have time to render it in their own voice and the exchange ends on a
calm repeat instead of an abrupt silence.

    python3 patch_echo.py ~/laki/laki.py

Refuses to run if any anchor is missing or the patch was already applied.
Tuning (laki.conf): LAKI_ECHO_DELAY (s, 0 = off), LAKI_ECHO_PEER_WAIT (s)."""
import sys, os, shutil, time, py_compile

path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/laki/laki.py")
src = open(path).read()
if "ECHO_DELAY" in src:
    sys.exit("already patched: " + path)
if "LAKI_IN" not in src:
    sys.exit("run patch_pattern.py first: " + path)

edits = []
def rep(old, new):
    edits.append((old, new))

# 1. header doc
rep('''A UDP "PLAY" broadcast when the wake word fires makes all birds whistle the
same melody together, each with its own timbre.''',
'''A UDP "PLAY" broadcast when the wake word fires makes all birds whistle the
same melody together, each with its own timbre.

Send-then-sing: right after a melody is accepted the sender pushes the pattern
and whistles it once more after a pause (LAKI_ECHO_DELAY), which covers the
transfer and the peers' rendering time.''')

# 2. constants
rep('''PEER_REMOTE_DIR = "~/laki/sounds/"
UDP_PORT = 5005
UDP_MAGIC = b"LAKI PLAY"
''',
'''PEER_REMOTE_DIR = "~/laki/sounds/"
UDP_PORT = 5005
UDP_MAGIC = b"LAKI PLAY"

# Send-then-sing. When a melody is accepted, the pattern goes out to the peers
# and this bird whistles it once more after a short pause. The pause covers the
# transfer AND gives every receiver time to render the pattern in its own voice
# (about 2 s on a Zero 2 W, up to 20 s on a Zero W v1), so the flock is ready
# when the melody comes back instead of the sender falling silent. Per bird in
# laki.conf; a button press during the pause skips the repeat.
ECHO_DELAY = float(os.environ.get("LAKI_ECHO_DELAY", 3.0))          # s of silence before the repeat, 0 = no repeat
ECHO_PEER_WAIT = float(os.environ.get("LAKI_ECHO_PEER_WAIT", 15.0)) # s at most spent waiting for the rsyncs to finish
''')

# 3. push_phrase hands back its threads so the caller can wait for the transfer
rep('''    def push_phrase(self):
        for host in self.hosts:
            threading.Thread(target=self._rsync, args=(host,),
                             daemon=True).start()
''',
'''    def push_phrase(self):
        """Start one rsync per peer and return the threads, so the caller can
        wait for the pattern to be delivered before singing it again."""
        threads = [threading.Thread(target=self._rsync, args=(host,), daemon=True)
                   for host in self.hosts]
        for t in threads:
            t.start()
        return threads
''')

# 4. a wait that keeps the duplex stream alive
rep('''    def _flush(self, seconds=0.6):
        """Discard what the mic heard while we were playing (+ room tail)."""
        for _ in range(int(seconds * bird.SR / HOP)):
            self.read()
''',
'''    def _flush(self, seconds=0.6):
        """Discard what the mic heard while we were playing (+ room tail)."""
        for _ in range(int(seconds * bird.SR / HOP)):
            self.read()

    def _wait_draining(self, seconds, until=None):
        """Wait, but keep reading: a plain time.sleep() would let the capture
        buffer overflow and the output lead run dry. What the mic hears is
        thrown away. Stops early if until() says so; returns True if it did."""
        for i in range(int(max(seconds, 0.0) * bird.SR / HOP)):
            if until is not None and i % 8 == 0 and until():
                return True
            self.read()
        return until is not None and until()
''')

# 5. train(): send, pause, sing it again
rep('''        self._reload_phrase()
        self.cue("stored")
        self.peers.push_phrase()
''',
'''        self._reload_phrase()
        self.cue("stored")
        self._echo_after_store(self.peers.push_phrase())

    def _echo_after_store(self, sent):
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
''')

for old, new in edits:
    n = src.count(old)
    if n != 1:
        sys.exit(f"anchor found {n} times, expected 1:\n{old[:90]!r}")
    src = src.replace(old, new)

bak = path + ".bak-echo-" + time.strftime("%Y%m%d")
shutil.copy2(path, bak)
open(path, "w").write(src)
py_compile.compile(path, doraise=True)
print(f"patched {path} ({len(edits)} edits), backup {bak}, compiles OK")
