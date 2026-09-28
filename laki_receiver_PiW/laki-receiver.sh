#!/bin/sh
# Laki RECEIVER - a copy of laki.sh (which stays untouched) that starts the
# bird in receive-only mode with this bird's voice from laki.conf.
# A receiver does not listen for "Lucky" and cannot be trained (the button is
# ignored). It waits for the raw whistle (sounds/laki_in.wav) sent by the
# sender bird, renders it in ITS OWN voice, and sings it when the sender
# broadcasts PLAY - same melody as the sender, this bird's timbre.
#
#   ./laki-receiver.sh        run in the foreground (log on screen and in
#                             /tmp/laki.log). Ctrl-C stops it cleanly.
#   ./laki-receiver.sh stop   stop a bird started elsewhere (systemd / other shell)
#
# Extra args go to laki.py and override laki.conf for this run
# (e.g. ./laki-receiver.sh --shift -5). Retune: edit laki.conf, stop, start.
cd "$(dirname "$0")"
PID=/tmp/laki.pid
running() { [ -f $PID ] && kill -0 "$(cat $PID)" 2>/dev/null; }

case "$1" in
  button)
    echo "this bird is a receiver: the button does nothing (train the sender instead)"; exit 1 ;;
  stop)
    running || { echo "laki is not running"; exit 0; }
    kill -TERM "$(cat $PID)"          # clean close of the ReSpeaker stream
    for i in 1 2 3 4 5 6 7 8; do
      running || { echo "stopped"; exit 0; }; sleep 1
    done
    echo "still running after 8s - not killing hard (would crash the ReSpeaker)"; exit 1 ;;
  *)
    running && { echo "already running (pid $(cat $PID)) - ./laki-receiver.sh stop first"; exit 1; }
    [ -f laki.conf ] && . ./laki.conf        # this bird's voice, see laki.conf
    exec .venv/bin/python -u laki.py --receiver $FLAGS "$@" 2>&1 < /dev/null | tee /tmp/laki.log ;;
esac
