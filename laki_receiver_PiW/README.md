# laki_receiver_PiW — a RECEIVER bird (Raspberry Pi Zero W v1)

This folder is a copy of `~/laki` taken from **laki-04** (`laki_test_04@laki-04`, a Pi
**Zero W v1**) on **2026-09-28**. It is a listening bird: it never records anything. It
waits for the **raw whistle** (`sounds/laki_in.wav`) that the sender bird rsyncs over,
renders it **in its own voice**, and sings it when the sender broadcasts UDP `PLAY` on the
wake word "Lucky". Same melody as the sender, different timbre.

The sender counterpart is `../laki_Send_Pi2W/` (Pi Zero 2 W, laki-01).

> **Why a Zero W v1 can only be a receiver.** It is ARMv6, one core, 512 MB. `sherpa-onnx`
> — the wake-word engine — has no ARMv6 build, so this Pi cannot listen for "Lucky" and
> cannot be the sender. Everything else runs fine, just slower: ~20 s to render a pattern
> instead of ~2 s. It makes a perfectly good receiver.

> Commands with a `PS>` prompt run on the Windows PC (PowerShell or Git Bash); everything
> else runs on the Pi over SSH. `0X` is this bird's number (`04` here).

---

## 0. What you need

**Hardware**

| Item | Notes |
|---|---|
| Raspberry Pi **Zero W v1** (a Zero 2 W works too) | Zero W v1 is ARMv6 → **32-bit OS mandatory** |
| microSD card + micro-USB PSU | into the **PWR** port, not the data one |
| **ReSpeaker Lite** (Seeed Studio) with pins soldered | a receiver only uses the amplifier side, but the module is still the I2S clock master |
| Speaker 5 W / 4 Ω | screw terminal on the ReSpeaker |
| 8 Dupont wires | I2S + I2C |
| USB-C cable + USB-OTG adapter | **only** if the ReSpeaker firmware has to be flashed (step 6) |

No button is needed on a receiver — it is ignored. Wire one anyway if you want the boards
identical.

**On the PC**

- [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- An SSH key at `C:\Users\<you>\.ssh\id_ed25519.pub`

---

## 1. Flash the microSD card

1. Raspberry Pi Imager → **Raspberry Pi OS Lite (32-bit)**.
   ⚠️ **32-bit is mandatory on a Zero W v1.** The 64-bit image will not boot on ARMv6.
2. **OS customisation** panel:
   - hostname `laki-04`
   - username `laki_test_04`, password `--Ask poolnumerique for info--`
   - Wi-Fi SSID + password, **Wi-Fi country**
   - **Enable SSH** → *Allow public-key authentication only*, paste your `id_ed25519.pub`
3. Write, then **leave the card in the PC**.

> **`--Ask poolnumerique for info--`** stands in for a credential that is not published
> with this repository. Ask Pool Numérique for the real value, or simply pick your own —
> nothing in the code depends on it.

---

## 2. Prepare the card from the PC (no screen, no keyboard)

Windows only mounts the FAT partition, `bootfs`. That is enough — Raspberry Pi OS reads
cloud-init from it at first boot. This is exactly how laki-04 was built.

### 2a. `config.txt` — put the Pi in I2S slave mode

Back it up (`copy config.txt config.txt.bak-laki`), then make it contain:

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
MD5 `3c9f470d6e645e4b5c2d8268d4e05a82`, 2474 bytes.

### 2c. `user-data` — let cloud-init do the apt work

Edit `bootfs\user-data`:

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

`libopenblas0` and `libgfortran5` are what the piwheels armv6 numpy/scipy wheels link
against — without them the venv builds but `import scipy` fails. The powersave file stops
the Pi from dropping off the Wi-Fi ~10 minutes after boot.

Eject, insert in the Pi, power up.

---

## 3. First boot and SSH

First boot is **slow** — cloud-init installs the packages on a single ARMv6 core. Give it
5–10 minutes. `Connection refused` in the meantime is normal.

Add to `C:\Users\<you>\.ssh\config` on the PC:

```
Host laki laki-*
    StrictHostKeyChecking accept-new

Host laki-04
    HostName laki-04
    User laki_test_04
```

Then:

```
PS> ssh laki-04
laki_test_04@laki-04:~$ cloud-init status        # want: status: done
```

It must log in **without a password**. If it asks for one:

```
PS> type C:\Users\<you>\.ssh\id_ed25519.pub | ssh laki_test_04@laki-04 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo key installed"
```

If the name does not resolve, the Pi is not on the Wi-Fi. `ipconfig /flushdns` on the PC;
`laki-04.local` (mDNS/avahi) also works and needs no DNS server at all.

> **After re-flashing a card, run `ssh-keygen -R laki-04` on the PC** — and also
> `ssh-keygen -R laki-04.local` **on the sender**, or its rsync will refuse the new host
> key.

If cloud-init did not run, do it by hand (this is the only step needing `sudo`, and it
will ask for the password):

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-venv libportaudio2 libsndfile1 rsync alsa-utils \
                    i2c-tools dfu-util python3-gpiozero python3-lgpio \
                    libopenblas0 libgfortran5
printf '[connection]\nwifi.powersave = 2\n' | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf
sudo systemctl restart NetworkManager
echo i2c-dev | sudo tee /etc/modules-load.d/i2c-dev.conf && sudo modprobe i2c-dev
```

---

## 4. Wiring

**Power the Pi off first.** Check 5V and GND twice — the ReSpeaker runs on **5V, never
3.3V**. The pinout is identical on Zero W and Zero 2 W.

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
| GPIO17 | 11 | button, leg 1 — *optional on a receiver, it is ignored* |
| GND | any free one above | button, leg 2 |

Speaker on the ReSpeaker's screw terminal.

**The trap this very Pi hit:** BCLK was two pins off — `dmesg | grep -i pcm` said
`no PCM clock` and `pinctrl` showed the clock alive on GPIO15 (pin 10). Count the pins
from the corner of the header: **BCLK is pin 12**.

The other one, from laki-03: dead I2S data wires. Clocks fine, sound "saturated then
nothing". The check is in step 5c.

---

## 5. Check the I2S link

```bash
ssh laki-04
arecord -l
```

Expected: `card 0: GenericStereoAu [GenericStereoAudioCodec], device 1: bcm2835-i2s-dir-hifi`
(capture `hw:0,1`, playback `hw:0,0`). If the card is missing, in this order: did you
reboot? does `/boot/firmware/overlays/genericstereoaudiocodec.dtbo` exist? is the name
spelled right in `config.txt`?

```bash
pinctrl get 2,3,18,19,20,21    # the six pins must read a0
```

### 5b. Is the module really running at 48 kHz?

The ReSpeaker is the **I2S clock master** — its firmware decides the real sample rate and
ALSA accepts any number you ask for without complaining. Laki expects 48 kHz
(`STREAM_SR = 48000` in `laki.py`).

```bash
time arecord -D hw:0,1 -f S16_LE -c 2 -r 48000 -d 3 /tmp/t48.wav
```

- `real ≈ 3 s` → module is 48 kHz ✅ nothing to flash, skip step 6
  (on laki-04: 3 s asked, 3.08 s real)
- `real ≈ 9 s` → module is 16 kHz → step 6

```bash
sudo i2cdetect -y 1                                    # expect 18 (TLV320 codec) and 42 (XMOS)
sudo i2ctransfer -y 1 w3@0x42 0xF0 0xD8 0x04 r4@0x42   # 0x00 0x01 0x00 0x09 = firmware 1.0.9
```

### 5c. Are the data wires alive?

Laki stopped, quiet room (run this after step 7, the venv has to exist):

```bash
arecord -D hw:0,1 -f S16_LE -c 2 -r 48000 -d 2 /tmp/t.wav
~/laki/.venv/bin/python -c "import soundfile as sf,numpy as np;x,sr=sf.read('/tmp/t.wav',dtype='int16');a=x[:,0]/32768.;print('rms %.4f'%np.sqrt(np.mean(a**2)))"
```

Good wiring: **rms < 0.01**. Bad: 0.5–0.7 (full-scale white noise — the Pi is reading
random bits). Replace the GPIO20/GPIO21 wires. I2C, firmware version and clocks can all
look perfect while the data line is dead.

---

## 6. Update the ReSpeaker Lite firmware — only if step 5b said 16 kHz

laki-04's module was 48 kHz out of the box and was never flashed. Of the four modules in
this project only one ever needed it. **Measure before you flash.**

1. Download the 48 kHz firmware (the `raw.githubusercontent.com` link is mandatory):

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
   partition was not written (Seeed issue #6). **Never unplug during `Download`.**

4. **A real power cycle.** The module is fed by the Pi's 5V *and* by USB-C:
   `sudo poweroff` → cut the PSU → unplug the USB-C → unplug the 5V Dupont → wait 10 s.
   Then redo step 5b.

5. The firmware survives re-flashing the Pi's SD card — this is a once-per-module job.

> **If the flash "succeeds" but nothing changes** ([issue #6](https://github.com/respeaker/ReSpeaker_Lite/issues/6)):
> known bug, no fix from Seeed. On our module #2 a second flash followed by a true power
> cycle eventually took. Do **not** try the FACTORY flash (`-a 0`) — it is the only
> command that can brick the module, and the only factory image available is 16 kHz.
> **Plan B:** run Laki at 16 kHz, its internal engine is 16 kHz already:
> `cd ~/laki && cp laki.py laki.py.bak-48k && sed -i 's/^STREAM_SR = 48000/STREAM_SR = 16000/' laki.py`
> Do not propagate that change to birds whose module is 48 kHz.

---

## 7. Copy the code onto the Pi

From this folder on the PC (Git Bash), with the Pi reachable as `laki-04`:

```bash
cd .../Laki_git/Laki_2026/laki_receiver_PiW
ssh laki-04 'mkdir -p ~/laki'
scp -r bird.py laki.py laki.sh laki-receiver.sh laki.conf mosaic.py peers.txt \
       requirements.txt install_autostart.sh \
       patch_pattern.py patch_receiver.py \
       LAKI.md PARAMETERS.md \
       birds sounds backup-base-original \
       laki-04:~/laki/
ssh laki-04 'cd ~/laki && sed -i "s/\r$//" *.sh && chmod +x laki.sh laki-receiver.sh install_autostart.sh'
```

⚠️ The `sed -i 's/\r$//'` is **not optional**. `scp` from Windows carries CRLF line
endings and a shell script with them fails as `/bin/sh^M: bad interpreter`.

A receiver deliberately does **not** get: `laki-send.sh` (that is what makes
`install_autostart.sh` pick the receiver role), the `wake/` models (no wake word on
ARMv6), or `birds-all/`.

`laki.py` here is **already patched** — no need to run the `patch_*.py` scripts. They are
kept for reference and are idempotent (they refuse to run twice or if an anchor is
missing):

| patch | what it does |
|---|---|
| `patch_pattern.py` | the shared pattern is the **raw whistle** `sounds/laki_in.wav`, not a rendered file — which is what lets every bird use its own voice. This bird watches that file (every 1 s while listening, and at startup) and re-renders on change |
| `patch_receiver.py` | adds `--receiver`: no wake word, no training, button ignored, sings only on the sender's PLAY broadcast |

`patch_echo.py` is sender-only and is **not** applied here.

To go back to the untouched upstream code:
`cp ~/laki/backup-base-original/laki.py ~/laki/backup-base-original/laki.sh ~/laki/`

---

## 8. Python environment

The venv **must** be created with `--system-site-packages`: the `lgpio` wheel does not
build without swig, and the Debian package is already there.

```bash
ssh laki-04
python3 -m venv --system-site-packages ~/laki/.venv
~/laki/.venv/bin/pip install numpy scipy sounddevice soundfile
~/laki/.venv/bin/python -c "import numpy, scipy, sounddevice, soundfile; print('ok')"
```

⏳ **This takes 20–40 minutes on a Zero W v1** — piwheels serves armv6 wheels and there is
one core to unpack them on. It is normal. Start it and go do something else.

Note we do **not** use `requirements.txt` here: it pulls sherpa-onnx, onnxruntime and
scikit-learn, none of which a receiver needs and none of which exist for ARMv6.

Versions measured on laki-04: Raspbian 13 trixie **32-bit**, kernel 6.18.50, Python
3.13.5, numpy 2.5.3, scipy 1.18.1, sounddevice 0.5.6, soundfile 0.14.0, no sherpa-onnx.

---

## 9. This bird's voice — `laki.conf`

`laki.conf` is a plain shell file sourced by `laki-receiver.sh` at every start. This is
where each bird gets its own timbre. Edit it, stop the bird, start it again — the pattern
is **re-rendered at startup**, so you hear the new voice straight away without
re-whistling anything. Flags typed on the command line still win for that run.

laki-04's actual settings:

```sh
export LAKI_VOLUME=75          # output level %, 100 = 0 dB
export LAKI_PRIME_MS=400       # Zero W v1: 293 ms stall when playback starts, so keep more lead
export LAKI_LATENCY=0.3        # PortAudio buffer, s
FLAGS="$FLAGS --birdiness 0.3" # 0 faithful whistle .. 1 full bird
FLAGS="$FLAGS --reverb 0.12"   # wet amount 0..1
FLAGS="$FLAGS --dry 0.7"       # direct voice 0..1
FLAGS="$FLAGS --texture 0.25"  # bird grain 0..1
FLAGS="$FLAGS --bend 0.3"      # per-note bend, semitones
FLAGS="$FLAGS --shift -12"     # one octave below the whistle (remove the line = auto)
```

> **`LAKI_PRIME_MS=400` is mandatory on a Zero W v1.** At 200 (the default) the output
> crackles: the first playback step stalls ~293 ms while upsampling.

**`--shift` is the real pitch control** — semitones, negative goes down, `-12` is one
octave. Without it, automatic mode pulls the median towards `WHISTLE_REGISTER` (1200 Hz,
in `bird.py`) but **never downwards**. `--birdiness` only adds 3 semitones at most, so
raising it from 0.3 to 0.8 barely changes the pitch. Give each bird a different `--shift`
(`-12`, `-7`, `-5`, or none) and the flock sings in chords. Every parameter is documented
in `PARAMETERS.md`.

---

## 10. Link it to the sender

The receiver's side of this is trivial: it needs the **sender's** public key in its
`authorized_keys`, and nothing else. `peers.txt` on a receiver stays empty (it only holds
a comment line here) — a receiver never pushes to anyone.

Run this **on the sender**:

```bash
ssh laki
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519       # only if it has none
ssh-copy-id -i ~/.ssh/id_ed25519.pub laki_test_04@laki-04.local
ssh -o BatchMode=yes laki_test_04@laki-04.local "echo OK from \$(hostname)"
```

and add the bird to the sender's `peers.txt`, **by `.local` name, never by IP**:

```
laki_test_04@laki-04.local
```

An IP follows the **board**, not the SD card (we got bitten by exactly that), and it
changes with the router. `.local` is answered by avahi running on the birds themselves, so
it keeps working on a bare router with no DNS and no internet.

> `peers.txt` is read **once at start** — restart the sender after editing it:
> `ssh -t laki "sudo systemctl restart laki"`.

The PC-side helper `patches/setup_link.sh` (in the parent `Laki/` folder) does the whole
link in one idempotent command:

```bash
sh patches/setup_link.sh laki laki-04 laki_test_04@laki-04.local
```

⚠️ The third argument must be the **`.local` form**, identical to the line already in
`peers.txt` — the script does a `grep -qxF` before appending, so the right form adds no
duplicate and a short name or an IP does.

---

## 11. Run it

Receivers first, sender last — otherwise the sender pushes to birds that are not listening
yet.

```bash
ssh laki-04 'cd ~/laki && ./laki-receiver.sh'
```

Expected in the log:

```
mode: RECEIVER
output lead 400 ms                                  <- proof that laki.conf was read
RECEIVER: waiting for a peer's PLAY broadcast
```

Then, on the sender: button → whistle → button → accept. This bird logs:

```
pattern: laki_in.wav (3.0s) rendered in this bird's voice in 12s -> laki_out.wav
```

Say **"Lucky"** to the sender and the flock sings together (a few tens of ms apart).

Test it without whistling, from the PC:

```bash
ssh laki 'cd ~/laki && rsync -q --timeout=20 sounds/laki_in.wav laki_test_04@laki-04.local:~/laki/sounds/ && echo rsync OK'
ssh laki-04 'sleep 25; grep "pattern:" /tmp/laki.log | tail -1'
```

Other commands:

```bash
./laki-receiver.sh stop        # clean stop (SIGTERM)
./laki-receiver.sh --shift -5  # override laki.conf for this run
tail -f /tmp/laki.log
```

`./laki-receiver.sh button` answers that the button does nothing — that is correct, train
the sender instead.

> ⚠️ **Never `kill -9` / `pkill -9` laki.py.** It leaves the ReSpeaker in a wedged state
> that only a power cut fixes. Always `stop`, Ctrl-C, or `systemctl stop laki`.

---

## 12. Start at boot

```bash
ssh laki-04
sudo ~/laki/install_autostart.sh
```

The script detects the role by itself (no `laki-send.sh` → receiver), writes
`/etc/systemd/system/laki.service`, enables and starts it. It runs **`laki-receiver.sh`,
not `laki.py`** — that is what loads `laki.conf`, and without it the bird would come up
with default pitch and `PRIME_MS=200`. It also adds a random 10–25 s start delay so the
ReSpeaker and the Wi-Fi settle and the birds do not all hit the network in the same second
after a power cut.

```bash
ssh laki-04 'systemctl is-active laki; tail -20 /tmp/laki.log'
systemctl status laki
journalctl -u laki -f
sudo systemctl stop laki        # before hacking by hand; gives laki.py 25 s to close the ReSpeaker
sudo systemctl disable laki     # no autostart (dev)
```

Measured on laki-04: **~85 s** from service start to `waiting` (10–25 s random delay +
importing numpy/scipy on ARMv6), on top of the boot. After a power cut, count **2–3
minutes** before the flock answers.

If `./laki-receiver.sh` answers **"already running"**, the service still has it — `stop`
first.

---

## 13. What to expect from a Zero W v1

Measured on laki-04, against a Zero 2 W:

| operation | Zero W v1 |
|---|---|
| first import of `laki.py` (compiling .pyc) | 25 s |
| corpus, 12 wavs → 97 grains | 3.2 s |
| rendering a 4.6 s pattern, idle | 7.3 s |
| rendering the same pattern with the audio stream running | 18.7 s |
| python CPU at rest, 48 k duplex stream open | ~39 % of the single core |
| xruns while waiting (50 s) | 0 |
| xruns at startup if a pattern renders at the same time | 3 |
| playback on PLAY | 0 xruns, one `slow step 293 ms` at the start → hence `LAKI_PRIME_MS=400` |

**Verdict: a Zero W v1 makes a good receiver.** The limits: ~20 s to render a new pattern,
during which a PLAY still plays the *previous* one, and a few xruns at startup. That 20 s
is exactly what the sender's `LAKI_ECHO_DELAY` / `LAKI_ECHO_PEER_WAIT` pause covers.

---

## 14. Troubleshooting, in the order we actually needed it

| Symptom | Cause / fix |
|---|---|
| The 64-bit image will not boot | Zero W v1 is ARMv6 → **32-bit Raspberry Pi OS Lite** |
| `arecord -l` shows no GenericStereoAu | no reboot after `config.txt`; or `.dtbo` missing from `/boot/firmware/overlays/`; or the overlay name is misspelled |
| `dmesg \| grep -i pcm` → `no PCM clock` | BCLK on the wrong pin — it is **pin 12** (this Pi's own trap) |
| Capture is pure loud noise, `rms` 0.5–0.7 | dead or swapped GPIO20/GPIO21 data wires |
| A 3 s capture really takes 9 s | ReSpeaker module is in 16 kHz → step 6 |
| `import scipy` fails after the venv build | `libopenblas0` / `libgfortran5` missing (piwheels armv6 links against them) |
| pip seems stuck for half an hour | normal on ARMv6, let it finish |
| Output crackles | `LAKI_PRIME_MS` too low — 400 on a Zero W v1 |
| Log does not show `output lead 400 ms` | `laki.conf` was not read → the service is running `laki.py` instead of `laki-receiver.sh` |
| This bird stays silent on "Lucky" | same Wi-Fi as the sender? running `laki-receiver.sh` and not `laki.sh`? does the log show `rendered`? |
| It sings the *previous* melody | it is still rendering the new one (~20 s), or the rsync did not arrive |
| Sender logs `peers: ... failed` for this bird | it is off the Wi-Fi, or its host key changed after a re-flash → `ssh-keygen -R laki-04.local` **on the sender** |
| SSH stops working ~10 min after boot | Wi-Fi powersave — the `wifi-powersave-off.conf` file is missing |
| `/bin/sh^M: bad interpreter` | CRLF from a Windows `scp` → `sed -i 's/\r$//' *.sh` |
| `HOST IDENTIFICATION HAS CHANGED` | card was re-flashed → `ssh-keygen -R laki-04` on the PC |
| Pi unresponsive after plugging the ReSpeaker | unplug the ReSpeaker and test the Pi alone |
| `lsusb` shows nothing | normal in operation — USB-C is only used for flashing |
| `Waiting for cache lock` during apt | automatic update running, wait 1–2 min |

**Moving to another network:** nothing here reaches the internet. Code, venv, `laki.conf`,
SSH keys, the systemd service, the `.local` names and the UDP PLAY broadcast (link-local,
port 5005) all survive untouched. Add the new Wi-Fi once per Pi, **before you leave**:
`sudo nmcli con add type wifi ifname wlan0 con-name venue ssid "NEW_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "password" connection.autoconnect yes connection.autoconnect-priority 20`
— ⚠️ never `nmcli device wifi connect …` over SSH, it drops the session. Then watch out
for router **AP/client isolation**, which lets the Pis reach the internet but not each
other. Full details in `../laki_Send_Pi2W/README.md` §13.

---

## 15. What is in this folder

| Path | What |
|---|---|
| `laki.py` | the bird — **patched** (pattern + `--receiver`). 48 kHz I2S stream, 16 kHz engine. No echo patch: that is sender-only |
| `bird.py` | synthesis: pitch tracking, grains, reverb, `WHISTLE_REGISTER` |
| `mosaic.py` | grain corpus built from `birds/*.wav` |
| `laki.sh` | the original launcher, left untouched |
| `laki-receiver.sh` | **receiver launcher** — sources `laki.conf`, runs `laki.py --receiver $FLAGS`. Also `stop` |
| `laki.conf` | this bird's voice: `--shift -12` and `LAKI_PRIME_MS=400` (§9) |
| `peers.txt` | empty by design — a receiver pushes to nobody |
| `install_autostart.sh` | writes and enables `laki.service` (§12) |
| `patch_pattern.py`, `patch_receiver.py` | the two patches, already applied to `laki.py`; idempotent |
| `backup-base-original/` | untouched upstream `laki.py`, `laki.sh`, `bird.py`, `mosaic.py`, `peers.txt` — the way back |
| `birds/` | 12 hummingbird wavs + `_corpus_16000.npz`, the grain cache (regenerated if deleted) |
| `sounds/laki_in.wav` | the raw whistle received from the sender |
| `sounds/laki_out.wav` | that melody rendered in **this** bird's voice — what PLAY plays |
| `sounds/laki_out_default.wav` | the fallback song before any pattern arrives |
| `boot/genericstereoaudiocodec.dtbo` | the I2S overlay for `bootfs\overlays\` (§2b) |
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
