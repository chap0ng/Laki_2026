#!/bin/sh
# Laki SENDER - a copy of laki.sh (which stays untouched) that also loads this
# bird's voice from laki.conf. This is the bird you whistle to: it records the
# melody, keeps it, sends the RAW whistle (sounds/laki_in.wav) to every host in
# peers.txt and, when it hears "Lucky", tells them all to sing along.
#
#   ./laki-send.sh            run the bird in the foreground (log on screen and in
#                             /tmp/laki.log). Ctrl-C stops it cleanly.
#   ./laki-send.sh button     press the button (from another terminal)
#   ./laki-send.sh stop       stop a bird started elsewhere (systemd / other shell)
#
# Extra args go to laki.py and override laki.conf for this run
# (e.g. ./laki-send.sh --shift -5, --no-wake, --debug).
cd "$(dirname "$0")"
PID=/tmp/laki.pid
running() { [ -f $PID ] && kill -0 "$(cat $PID)" 2>/dev/null; }

case "$1" in
  button)
    running || { echo "laki is not running"; exit 1; }
    kill -USR1 "$(cat $PID)" && echo "pressed" ;;
  stop)
    running || { echo "laki is not running"; exit 0; }
    kill -TERM "$(cat $PID)"          # clean close of the ReSpeaker stream
    for i in 1 2 3 4 5 6 7 8; do
      running || { echo "stopped"; exit 0; }; sleep 1
    done
    echo "still running after 8s - not killing hard (would crash the ReSpeaker)"; exit 1 ;;
  *)
    running && { echo "already running (pid $(cat $PID)) - ./laki-send.sh stop first"; exit 1; }
    [ -f laki.conf ] && . ./laki.conf        # this bird's voice, see laki.conf
    exec .venv/bin/python -u laki.py $FLAGS "$@" 2>&1 < /dev/null | tee /tmp/laki.log ;;
esac
