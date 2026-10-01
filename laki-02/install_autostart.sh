#!/bin/sh
# Laki autolauncher - installs the systemd service on THIS Pi so the bird
# starts at boot and restarts itself if it crashes. Run ON the Pi:
#
#   sudo ~/laki/install_autostart.sh
#
# The role is detected, not asked: laki-send.sh present -> SENDER (laki-01),
# otherwise -> RECEIVER. The service runs the ROLE SCRIPT (not laki.py), so
# laki.conf - this bird's voice, volume, PRIME_MS - is loaded at every start.
# Idempotent: re-running it rewrites the unit and reloads systemd.
set -e
[ "$(id -u)" = 0 ] || { echo "run me with sudo: sudo ~/laki/install_autostart.sh"; exit 1; }

U=${SUDO_USER:-$(logname 2>/dev/null)}
[ -n "$U" ] || { echo "cannot tell which user to run as"; exit 1; }
H=$(getent passwd "$U" | cut -d: -f6)
D=$H/laki
[ -d "$D" ] || { echo "no $D directory"; exit 1; }

if [ -f "$D/laki-send.sh" ]; then
  ROLE=sender;   SCRIPT=laki-send.sh;     DELAY=15-35
else
  ROLE=receiver; SCRIPT=laki-receiver.sh; DELAY=10-25
fi
[ -f "$D/$SCRIPT" ] || { echo "missing $D/$SCRIPT"; exit 1; }
chmod +x "$D/$SCRIPT"
[ -x "$D/.venv/bin/python" ] || { echo "missing $D/.venv - create the venv first"; exit 1; }

cat > /etc/systemd/system/laki.service <<EOF
# Laki autostart - $ROLE. Written by install_autostart.sh on $(date +%Y-%m-%d).
# Runs $SCRIPT (NOT laki.py) so laki.conf - this bird's voice - is loaded.
[Unit]
Description=Laki the whistling bird ($ROLE)
After=sound.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$U
WorkingDirectory=$D
# random $DELAY s: lets the ReSpeaker and the Wi-Fi settle, and staggers the
# birds so they do not all hit the network at the same second after a power cut
ExecStartPre=/bin/sh -c 'sleep \$(shuf -i $DELAY -n 1)'
ExecStart=$D/$SCRIPT
Restart=always
RestartSec=10
# Restart=always, NOT on-failure: when the ReSpeaker stops clocking I2S, laki.py
# prints "AUDIO DEVICE STALLED" and exits with code 0. systemd reads that as a
# clean stop, so on-failure would never restart the bird (learned on laki-04,
# 30.09.2026). always covers both a crash and that silent clean exit.
# SIGTERM closes the ReSpeaker stream cleanly - never SIGKILL, it wedges the card
KillSignal=SIGTERM
TimeoutStopSec=25

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now laki.service
echo "----------------------------------------------------------"
echo "installed: laki.service -> $SCRIPT ($ROLE), user $U"
echo "  status : systemctl status laki"
echo "  log    : tail -f /tmp/laki.log"
echo "  stop   : sudo systemctl stop laki      (disable = no autostart)"
echo "----------------------------------------------------------"
