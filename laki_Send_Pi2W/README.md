# laki_Send_Pi2W — the SENDER bird (Raspberry Pi Zero 2 W)

This folder is a copy of `~/laki` taken from **laki-01** (`laki_test@laki`, a Pi Zero 2 W)
on **2026-09-28**. It is the bird you whistle to. It records a melody, keeps the **raw
whistle**, pushes it by rsync to every receiver listed in `peers.txt`, and when it hears
the wake word **"Lucky"** it broadcasts a UDP `PLAY` so the whole flock sings at once —
same melody, each bird in its own voice.

The receiver counterpart is `../laki_receiver_PiW/` (Pi Zero W v1, laki-04).

> Everything below is written to be followed **in order**, from a blank microSD card to a
> bird that starts by itself at power-on. Commands with a `PS>` prompt run on the Windows
> PC (PowerShell or Git Bash); everything else runs on the Pi over SSH.

---

## 0. What you need

**Hardware**

| Item | Notes |
|---|---|
| Raspberry Pi **Zero 2 W** | 64-bit, 4 cores. The sender needs them: the wake word (sherpa-onnx) does not exist for ARMv6, so a Zero W v1 **cannot** be a sender. |
| microSD card + micro-USB PSU | plug the PSU into the **PWR** port, not the data one |
| **ReSpeaker Lite** (Seeed Studio) with pins soldered | mic array + amplifier, talks I2S |
| Speaker 5 W / 4 Ω | screw terminal on the ReSpeaker |
| Push button + 2 Dupont wires | no resistor needed (internal pull-up) |
| 8 Dupont wires | for the I2S + I2C link |
| USB-C cable + USB-OTG adapter | **only** if the ReSpeaker firmware has to be flashed (step 6) |

**Sizes**, if you are building an enclosure: Pi Zero 2 W 31 × 70 × 6 mm · ReSpeaker Lite
35 × 85 × ~15 mm · 5 W speaker 45 × 67 × 24 mm (with the mounting ears).

**On the PC**

- [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- An SSH key at `C:\Users\<you>\.ssh\id_ed25519.pub` (`ssh-keygen -t ed25519` if you have none)

---

## 1. Flash the microSD card

1. Raspberry Pi Imager → **Raspberry Pi OS Lite (64-bit)**. Lite, no desktop — the Pi is
   headless and the GPU stack is dead weight.
2. Open the gear / **OS customisation** panel and set:
   - hostname `laki`
   - username `laki_test`, password `--Ask poolnumerique for info--`
   - Wi-Fi SSID + password, **Wi-Fi country** (without it the radio stays off)
   - **Enable SSH** → *Allow public-key authentication only*, and paste your
     `id_ed25519.pub`
3. Write, then **leave the card in the PC** — the next step happens on the card.

> **`--Ask poolnumerique for info--`** stands in for a credential that is not published
> with this repository. Ask Pool Numérique for the real value, or simply pick your own —
> nothing in the code depends on it.

---

## 2. Prepare the card from the PC (no screen, no keyboard)

Windows only mounts the FAT partition, `bootfs`. That is enough: Raspberry Pi OS reads
cloud-init from it at first boot.

### 2a. `config.txt` — put the Pi in I2S slave mode

Back it up first (`copy config.txt config.txt.bak-laki`), then make it contain:

```ini
dtparam=i2c_arm=on
dtparam=i2s=on
dtoverlay=genericstereoaudiocodec
#dtparam=audio=on        # off: the ReSpeaker Lite is the sound card
```

⚠️ The overlay name must be **exactly** `genericstereoaudiocodec`, no `.dtbo` suffix. A
typo is ignored silently and you get no sound card at all.

### 2b. Copy the overlay

Copy `boot/genericstereoaudiocodec.dtbo` from this folder into `bootfs\overlays\`.

MD5 `3c9f470d6e645e4b5c2d8268d4e05a82`, 2474 bytes. (It is built from
`genericstereoaudiocodec.dts` with `dtc`; the prebuilt binary is here so you never have to.)

### 2c. `user-data` — let cloud-init do the apt work

Edit `bootfs\user-data` so it installs the packages and drops two config files at first
boot:

```yaml
packages:
  - python3-venv
  - libportaudio2
  - libsndfile1
  - rsync
  - alsa-utils
  - i2c-tools
  - dfu-util
  - python3-gpiozero
  - python3-lgpio
  - libopenblas0
  - libgfortran5

write_files:
  - path: /etc/NetworkManager/conf.d/wifi-powersave-off.conf
    content: |
      [connection]
      wifi.powersave = 2
  - path: /etc/modules-load.d/i2c-dev.conf
    content: |
      i2c-dev
```

The powersave file is **not optional**: without it a Zero 2 W drops off the Wi-Fi about
10 minutes after boot (brcmfmac power saving) and rsync to the receivers starts failing.

Eject the card, put it in the Pi, power up.

---

## 3. First boot and SSH

First boot takes **3–5 minutes** (cloud-init installs the packages); SSH answers after
60–90 s but the packages land later. `Connection refused` early on is normal — wait.

Add this to `C:\Users\<you>\.ssh\config` on the PC:

```
Host laki laki-*
    StrictHostKeyChecking accept-new

Host laki
    HostName laki
    User laki_test
```

Then:

```
PS> ssh laki
laki_test@laki:~$ cloud-init status        # want: status: done
```

It must log in **without a password**. If it asks for one, the key did not make it:

```
PS> type C:\Users\<you>\.ssh\id_ed25519.pub | ssh laki_test@laki "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo key installed"
```

If the name does not resolve at all, the Pi is not on the Wi-Fi. `ipconfig /flushdns` on
the PC; `laki.local` (mDNS/avahi) also works and needs no DNS server.

> **After re-flashing a card, run `ssh-keygen -R laki` on the PC**, otherwise SSH refuses
> to connect with *HOST IDENTIFICATION HAS CHANGED*.

If cloud-init did not run (classic Imager flash, no `user-data`), do it by hand:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv libportaudio2 libsndfile1 rsync alsa-utils \
                    i2c-tools dfu-util device-tree-compiler \
                    python3-gpiozero python3-lgpio libopenblas0 libgfortran5
printf '[connection]\nwifi.powersave = 2\n' | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf
sudo systemctl restart NetworkManager
echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf && sudo modprobe i2c-dev
```

---

## 4. Wiring

**Power the Pi off first.** Check 5V and GND twice — the ReSpeaker runs on **5V, never
3.3V**.

| Raspberry Pi | physical pin | ReSpeaker Lite / button |
|---|---|---|
| 5V | 2 or 4 | **5V** |
| GND | 6, 9, 14, 20, 25, 30, 34, 39 | **GND** |
| GPIO18 · PCM_CLK | **12** | I2S_BCLK |
| GPIO19 · PCM_FS | 35 | I2S_LRCLK |
| GPIO20 · PCM_DIN | 38 | I2S_DIN_XIAO (din) |
| GPIO21 · PCM_DOUT | 40 | I2S_DIN_SEC (dout) |
| GPIO2 · SDA | 3 | SDA |
| GPIO3 · SCL | 5 | SCL |
| GPIO17 | 11 | button, leg 1 |
| GND | any free one above | button, leg 2 |

Speaker on the ReSpeaker's screw terminal. Same pinout on Zero W and Zero 2 W.

**Two wiring traps we actually hit**

- **BCLK two pins off.** `dmesg \| grep -i pcm` said `no PCM clock` and the clock was
  alive on GPIO15 (pin 10). Count the pins from the corner of the header: BCLK is
  **pin 12**.
- **Dead data wires.** Clocks fine, sound "saturated then nothing", huge white noise on
  capture. The check is in step 5c — if RMS comes out at 0.5–0.7 instead of <0.01,
  replace the GPIO20/GPIO21 wires.

---

## 5. Check the I2S link

```bash
ssh laki
arecord -l
```

Expected: `card 0: GenericStereoAu [GenericStereoAudioCodec], device 1: bcm2835-i2s-dir-hifi`
(capture is `hw:0,1`, playback `hw:0,0`). If the card is missing, in this order: did you
reboot? does `/boot/firmware/overlays/genericstereoaudiocodec.dtbo` exist? is the name
spelled right in `config.txt`?

```bash
pinctrl get 2,3,18,19,20,21    # the six pins must read a0 (SDA1 SCL1 PCM_CLK PCM_FS PCM_DIN PCM_DOUT)
```

### 5b. Is the module really running at 48 kHz?

The ReSpeaker is the **I2S clock master** — its firmware decides the real sample rate and
ALSA will happily accept any number you ask for without complaining. Laki expects 48 kHz
(`STREAM_SR = 48000` in `laki.py`).

```bash
time arecord -D hw:0,1 -f S16_LE -c 2 -r 48000 -d 5 /tmp/t48.wav
```

- `real ≈ 5 s` → module is 48 kHz ✅ nothing to flash, skip step 6
- `real ≈ 15 s` → module is 16 kHz → step 6

```bash
sudo i2cdetect -y 1                                    # expect 18 (TLV320 codec) and 42 (XMOS)
sudo i2ctransfer -y 1 w3@0x42 0xF0 0xD8 0x04 r4@0x42   # 0x00 0x01 0x00 0x09 = firmware 1.0.9
```

### 5c. Are the data wires alive?

Laki stopped, quiet room:

```bash
arecord -D hw:0,1 -f S16_LE -c 2 -r 48000 -d 2 /tmp/t.wav
~/laki/.venv/bin/python -c "import soundfile as sf,numpy as np;x,sr=sf.read('/tmp/t.wav',dtype='int16');a=x[:,0]/32768.;print('rms %.4f'%np.sqrt(np.mean(a**2)))"
```

Good wiring: **rms < 0.01**. Bad: 0.5–0.7 (that is full-scale white noise — the Pi is
reading random bits). I2C, firmware version and clocks can all look perfect while the
data line is dead.

---

## 6. Update the ReSpeaker Lite firmware — only if step 5b said 16 kHz

Of the four modules in this project, only one ever needed this. **Measure before you flash.**

1. Download the 48 kHz firmware (the `raw.githubusercontent.com` link is mandatory, the
   web page link gives you HTML):

   ```bash
   wget https://raw.githubusercontent.com/respeaker/ReSpeaker_Lite/master/xmos_firmwares/respeaker_lite_i2s_dfu_firmware_48k_v1.0.9.bin
   ls -lh respeaker_lite_i2s_dfu_firmware_48k_v1.0.9.bin && md5sum respeaker_lite_i2s_dfu_firmware_48k_v1.0.9.bin
   ```

   Expect 274 432 bytes, MD5 `f29e6229a4f6ca5c80553aa79fbbef0e`.

2. Plug the ReSpeaker into the Pi by USB-C through the OTG adapter. Use the USB-C port
   **next to the 3.5 mm jack**, not the XIAO one.

   ```bash
   sudo dfu-util -l          # three "Found DFU: [2886:0019]" lines; ver=0109 is 1.0.9, ver=0108 is 1.0.8
   ```

3. Flash:

   ```bash
   time sudo dfu-util -R -e -a 1 -D respeaker_lite_i2s_dfu_firmware_48k_v1.0.9.bin
   ```

   Wait for `Done!` and **watch the clock**: ~6 s means it really wrote, ~3 s means the
   partition was not written (Seeed issue #6, see below). **Never unplug during
   `Download`.**

4. **A real power cycle.** The module is fed by the Pi's 5V *and* by USB-C, so:
   `sudo poweroff` → cut the PSU → unplug the USB-C → unplug the 5V Dupont → wait 10 s.
   Then redo step 5b.

5. The firmware survives re-flashing the Pi's SD card. You only do this once per module.

> **If the flash "succeeds" but nothing changes** ([issue #6](https://github.com/respeaker/ReSpeaker_Lite/issues/6)):
> two UPGRADEs in ~2.8 s, `ver=0108` unchanged, still 16 kHz. Known bug, no fix from
> Seeed. On our module #2 a second flash followed by a true power cycle eventually took.
> Do **not** try the FACTORY flash (`-a 0`) — it is the only command that can brick the
> module, and the only factory image available is 16 kHz anyway.
> **Plan B:** run Laki at 16 kHz — its internal engine is 16 kHz already:
> `cd ~/laki && cp laki.py laki.py.bak-48k && sed -i 's/^STREAM_SR = 48000/STREAM_SR = 16000/' laki.py`

---

## 7. Copy the code onto the Pi

From this folder on the PC (Git Bash), with the Pi reachable as `laki`:

```bash
cd .../Laki_git/Laki_2026/laki_Send_Pi2W
ssh laki 'mkdir -p ~/laki'
scp -r bird.py laki.py laki.sh laki-send.sh laki.conf mosaic.py peers.txt \
       requirements.txt install_autostart.sh \
       patch_pattern.py patch_receiver.py patch_echo.py \
       LAKI.md PARAMETERS.md \
       birds sounds wake backup-base-original \
       laki:~/laki/
ssh laki 'cd ~/laki && sed -i "s/\r$//" *.sh && chmod +x laki.sh laki-send.sh install_autostart.sh'
```

⚠️ The `sed -i 's/\r$//'` is **not optional**. `scp` from Windows carries CRLF line
endings and a shell script with them fails as `/bin/sh^M: bad interpreter`.

`laki.py` in this folder is **already patched** — you do not need to run the `patch_*.py`
scripts. They are kept for reference and because they are idempotent (they refuse to run
twice or if an anchor is missing). What they add:

| patch | what it does |
|---|---|
| `patch_pattern.py` | the shared pattern is the **raw whistle** `sounds/laki_in.wav`, not a rendered file — so every bird renders it in its own voice |
| `patch_receiver.py` | adds `--receiver`: no wake word, no training, button ignored, sings only on the peers' PLAY broadcast |
| `patch_echo.py` | after sending, the sender waits (`LAKI_ECHO_DELAY`) and sings the melody once more, so the flock answers together |

To go back to the untouched upstream code at any point:
`cp ~/laki/backup-base-original/laki.py ~/laki/backup-base-original/laki.sh ~/laki/`

---

## 8. Python environment

The venv **must** be created with `--system-site-packages`: the `lgpio` wheel does not
build without swig, and the Debian package is already there.

```bash
ssh laki
python3 -m venv --system-site-packages ~/laki/.venv
~/laki/.venv/bin/pip install -r ~/laki/requirements.txt
~/laki/.venv/bin/python -c "import numpy, scipy, sounddevice, soundfile, sherpa_onnx, onnxruntime, sklearn, gpiozero; print('ok')"
```

A few minutes on a Zero 2 W. `sherpa-onnx` is the wake-word engine — the sender is the
only bird that needs it, and it only exists for 64-bit ARM.

Versions measured on laki-01: Debian 13 trixie 64-bit, kernel 6.18.39, Python 3.13.5,
numpy 2.5.2, scipy 1.18.1, sounddevice 0.5.6, soundfile 0.14.0, sherpa-onnx 1.13.7,
onnxruntime 1.29.0, scikit-learn 1.9.0.

---

## 9. This bird's voice — `laki.conf`

`laki.conf` is a plain shell file sourced by `laki-send.sh` at every start. Edit it, stop
the bird, start it again. Flags typed on the command line still win for that run.

```sh
export LAKI_VOLUME=75          # output level %, 100 = 0 dB
export LAKI_PRIME_MS=200       # output lead ms; raise it if xrun lines appear
export LAKI_LATENCY=0.3        # PortAudio buffer, s
export LAKI_TRAIN_LEVEL=0.08   # minimum whistle level accepted while training (sender only)
export LAKI_ECHO_DELAY=3       # s of silence after sending before the bird re-sings (0 = off)
export LAKI_ECHO_PEER_WAIT=15  # s max spent waiting for the rsyncs to land
FLAGS="$FLAGS --birdiness 0.3" # 0 faithful whistle .. 1 full bird
FLAGS="$FLAGS --reverb 0.12"   # wet amount 0..1
FLAGS="$FLAGS --dry 0.7"       # direct voice 0..1
FLAGS="$FLAGS --shift -12"     # pitch in semitones, -12 = one octave down; commented out = auto
```

The real pitch control is **`--shift`**. Without it the automatic mode pulls the median
towards `WHISTLE_REGISTER` (1200 Hz, in `bird.py`) but **never downwards**. `--birdiness`
only adds 3 semitones at most. laki-01 runs on the defaults (auto pitch) so the receivers
can each sit an octave below it. Every parameter is documented in `PARAMETERS.md`.

---

## 10. Link the sender to the receivers

`peers.txt`, one SSH target per line, **always mDNS `.local` names, never IPs**:

```
laki_test_02@laki-02.local
laki_test_03@laki-03.local
laki_test_04@laki-04.local
```

Three reasons: an IP follows the **board**, not the SD card (we got bitten by exactly
that); an IP changes with the router; and `.local` is answered by avahi running on the
birds themselves, so it survives a bare router with no DNS and no internet.

`peers.txt` is read **once at start** — restart the bird after editing it.

The sender needs its own SSH key on each receiver, and a `~/.ssh/config` that accepts
unknown hosts (without it rsync dies with `Host key verification failed`):

```bash
ssh laki
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519      # if it has none yet
cat > ~/.ssh/config <<'EOF'
Host laki-0* *.local
    StrictHostKeyChecking accept-new
    ConnectTimeout 8
    ServerAliveInterval 5
    ServerAliveCountMax 3
EOF
chmod 600 ~/.ssh/config
for h in laki-02 laki-03 laki-04; do
  ssh-copy-id -i ~/.ssh/id_ed25519.pub laki_test_${h#laki-}@$h.local
done
for h in laki-02 laki-03 laki-04; do
  ssh -o BatchMode=yes laki_test_${h#laki-}@$h.local "echo OK from \$(hostname)"
done
```

Every line must answer `OK from laki-0X`.

> If a card gets re-flashed, its host key changes and the sender will refuse it:
> `ssh-keygen -R laki-0X.local` **on laki-01**.

The PC-side helper `patches/setup_link.sh` (in the parent `Laki/` folder) does all of
this in one shot and is idempotent:
`sh patches/setup_link.sh laki laki-04 laki_test_04@laki-04.local`

---

## 11. Run it

Receivers first, sender last — otherwise the sender pushes to birds that are not
listening yet.

```bash
ssh laki-02 'cd ~/laki && ./laki-receiver.sh'    # each in its own terminal
ssh laki-04 'cd ~/laki && ./laki-receiver.sh'
ssh laki    'cd ~/laki && ./laki-send.sh'
```

The full sequence on laki-01: **press the button → whistle a phrase → press the button
again** → the bird answers in its own voice → press the button to accept → the pattern is
rsynced to the receivers → a pause (rsyncs finish, then `LAKI_ECHO_DELAY` = 3 s) →
**laki-01 sings the melody once more** while each receiver renders it. Then say
**"Lucky"** and the whole flock sings.

Logs to look for on the sender:

```
TRAINING over ... raw whistle -> laki_in.wav
peers: pattern (raw whistle) sent to laki_test_04@laki-04.local
```

and on a receiver:

```
pattern: laki_in.wav (3.0s) rendered in this bird's voice in 12s -> laki_out.wav
```

Rendering takes ~2 s on a Zero 2 W, up to ~20 s on a Zero W v1.

Other commands:

```bash
./laki-send.sh button      # simulate a button press from another terminal
./laki-send.sh stop        # clean stop (SIGTERM)
./laki-send.sh --shift -5  # override laki.conf for this run
./laki-send.sh --no-wake   # run without the wake word
tail -f /tmp/laki.log
```

> ⚠️ **Never `kill -9` / `pkill -9` laki.py.** It leaves the ReSpeaker in a wedged state
> that only a power cut fixes. Always `stop`, Ctrl-C, or `systemctl stop laki`.

---

## 12. Start at boot

```bash
ssh laki
sudo ~/laki/install_autostart.sh
```

The script detects the role by itself (`laki-send.sh` present → sender), writes
`/etc/systemd/system/laki.service`, enables and starts it. It runs **`laki-send.sh`, not
`laki.py`** — that is what loads `laki.conf`. It also adds a random 15–35 s start delay so
the ReSpeaker and the Wi-Fi settle and the birds do not all hit the network in the same
second after a power cut.

```bash
systemctl status laki
journalctl -u laki -f
tail -f /tmp/laki.log
sudo systemctl stop laki        # before hacking by hand; gives laki.py 25 s to close the ReSpeaker
sudo systemctl disable laki     # no autostart (dev)
```

If `./laki-send.sh` answers **"already running"**, the service still has it — `stop` first.

After a power cut, count **2–3 minutes** before the flock answers (boot + random delay +
importing numpy/scipy).

---

## 13. Moving to another network

Nothing in Laki reaches the internet, at boot or at run time. What survives a network
change untouched: the code, the venv, `laki.conf`, the SSH keys, the systemd service, the
`.local` names (avahi runs on the Pis), the UDP PLAY broadcast (link-local, port 5005) and
`peers.txt` itself.

All you do, once per Pi and **before you leave** while they are still reachable:

```bash
sudo nmcli con add type wifi ifname wlan0 con-name venue ssid "NEW_SSID" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "password" \
  connection.autoconnect yes connection.autoconnect-priority 20
```

> ⚠️ **Never `nmcli device wifi connect …` over SSH** — it drops your session instantly.
> Adding a connection with `autoconnect yes` without activating it is safe.

Three traps with an unknown router:

1. **AP / client isolation** — on by default on many consumer routers. The Pis reach the
   internet but cannot see each other: no broadcast, no rsync, no `.local`, and nothing in
   the logs says so except failing rsyncs. **Turn it off first.**
2. **All the birds on the same SSID and subnet.** A split 2.4/5 GHz setup breaks the flock
   the same way. (Zero W boards are 2.4 GHz only anyway.)
3. **No internet means no NTP**, and no Pi here has an RTC — log timestamps will be wrong.
   Harmless, just do not let it confuse you while debugging.

Check afterwards:

```bash
ssh laki 'for h in laki-02 laki-03 laki-04; do printf "%-16s " $h.local; getent hosts $h.local || echo "NOT RESOLVED"; done'
ssh laki 'cd ~/laki && rsync -q --timeout=20 sounds/laki_in.wav laki_test_04@laki-04.local:~/laki/sounds/ && echo "rsync OK"'
```

Names resolve but rsync fails → trap 1. Names do not resolve → a Pi is on the wrong SSID.

---

## 14. Troubleshooting, in the order we actually needed it

| Symptom | Cause / fix |
|---|---|
| `arecord -l` shows no GenericStereoAu | no reboot after `config.txt`; or `.dtbo` missing from `/boot/firmware/overlays/`; or the overlay name is misspelled |
| `dmesg \| grep -i pcm` → `no PCM clock` | BCLK on the wrong pin — it is **pin 12** |
| Capture is pure loud noise, `rms` 0.5–0.7, log shows `noise floor 0.0200` / `level 0.58` | dead or swapped GPIO20/GPIO21 data wires |
| A 5 s capture really takes 15 s | ReSpeaker module is in 16 kHz → step 6 |
| Pi unresponsive after plugging the ReSpeaker | unplug the ReSpeaker and test the Pi alone |
| `lsusb` shows nothing | normal in operation — USB-C is only used for flashing |
| SSH stops working ~10 min after boot | Wi-Fi powersave — the `wifi-powersave-off.conf` file is missing |
| `HOST IDENTIFICATION HAS CHANGED` | card was re-flashed → `ssh-keygen -R laki` on the PC |
| `/bin/sh^M: bad interpreter` | CRLF from a Windows `scp` → `sed -i 's/\r$//' *.sh` |
| `peers: ... failed` in the sender log | that receiver is off the Wi-Fi, or `peers.txt` was edited without restarting |
| Occasional `slow step` / `xrun` lines while rendering | normal; if it is audible raise `LAKI_PRIME_MS` to 300 |
| A receiver stays silent on "Lucky" | is it on the same Wi-Fi? is it running `laki-receiver.sh` and not `laki.sh`? does its log show `rendered`? |
| `Waiting for cache lock` during apt | automatic update running, wait 1–2 min |

---

## 15. What is in this folder

| Path | What |
|---|---|
| `laki.py` | the bird — **patched** (pattern + `--receiver` + echo). 48 kHz I2S stream, 16 kHz engine |
| `bird.py` | synthesis: pitch tracking, grains, reverb, `WHISTLE_REGISTER` |
| `mosaic.py` | grain corpus built from `birds/*.wav` |
| `laki.sh` | the original launcher, left untouched |
| `laki-send.sh` | **sender launcher** — sources `laki.conf`, runs `laki.py $FLAGS`. Also `button` / `stop` |
| `laki.conf` | this bird's voice, volume, timings (§9) |
| `peers.txt` | the receivers, as `.local` SSH targets (§10) |
| `install_autostart.sh` | writes and enables `laki.service` (§12) — taken from the PC's `patches/`, laki-01 does not carry it yet |
| `patch_pattern.py`, `patch_receiver.py`, `patch_echo.py` | the three patches, already applied to `laki.py`; idempotent |
| `backup-base-original/` | untouched upstream `laki.py`, `laki.sh`, `bird.py`, `mosaic.py`, `peers.txt` — the way back |
| `birds/` | 12 hummingbird wavs + the `_corpus_*.npz` grain caches (regenerated if deleted) |
| `birds-all/` | the full sample library (cuckoo, collared dove, hummingbird) |
| `sounds/laki_in.wav` | the raw whistle — what gets rsynced to the peers |
| `sounds/laki_out.wav` | the phrase rendered in this bird's voice — what PLAY plays |
| `sounds/laki_out_default.wav` | the fallback song before any training |
| `wake/kws/` | sherpa-onnx keyword-spotting model; `keywords_laki.txt` holds `LUCKY` and `HEY_LUCKY` |
| `wake/Lucky_Lucky.onnx` | openwakeword model (alternative `--wake oww` backend) |
| `boot/genericstereoaudiocodec.dtbo` | the I2S overlay for `bootfs\overlays\` (§2b) |
| `laki.service`, `laki-autostart.service` | earlier systemd attempts, superseded by `install_autostart.sh` |
| `laki.py.bak-*`, `laki.conf.bak-echo`, `peers.txt.bak-ip-*` | on-Pi backups from each patch, kept as history |
| `LAKI.md`, `PARAMETERS.md` | upstream notes and the full parameter reference |

Not copied: `.venv/` (rebuild it, step 8) and `__pycache__/`.

---

## 16. Links

- ReSpeaker Lite repo, firmwares and DFU guide — https://github.com/respeaker/ReSpeaker_Lite
- Issue #6, the flash that does not take — https://github.com/respeaker/ReSpeaker_Lite/issues/6
- Community I2S-on-Pi guide — https://github.com/corus87/Respeaker-lite-on-raspberry-pi
- Seeed forum thread on this build — https://forum.seeedstudio.com/t/respeaker-lite-on-raspberry-using-i2s/281743
- Raspberry Pi Imager — https://www.raspberrypi.com/software/

Project documents in the parent `Laki/` folder:
`26_09_23_Laki_recap-projet-respeaker-lite-i2s_V3.md` (the complete write-up, in French),
`Final-Laki-setup.md` (quick checklist), `WiFi_and_Autolauncher.md`,
`26_09_24_Laki_receivers-02-03_et_reseau.md`, `PARAMETERS.md`, `I2S_Troubleshooting.md`.
