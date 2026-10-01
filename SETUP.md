# SETUP — build a Laki bird from nothing

The short version. Roughly 1 h of work plus waiting. If something goes wrong,
the long guides have the full detail and a troubleshooting table:
`laki_receiver_PiW/README.md` (receiver) or `laki_Send_Pi2W/README.md` (sender).

Credentials and Wi-Fi are **`--Ask pool numerique--`** — nothing in the code
depends on them.

---

## 0. What you need

| item | note |
|---|---|
| Raspberry Pi **Zero 2 W** (sender) or **Zero W v1** (receiver) | a Zero W v1 can only be a receiver |
| microSD card + 5 V micro-USB supply | into the **PWR** port, not the data one |
| **ReSpeaker Lite** with pins soldered | it is the I2S clock master |
| speaker 5 W / 4 Ω | screw terminal on the ReSpeaker |
| 8 Dupont wires | I2S + I2C |
| a push button (sender only) | receivers ignore it |

---

## 1. Flash the card

Raspberry Pi Imager → **Raspberry Pi OS Lite**.

> ⚠️ **Zero W v1 → 32-bit. Mandatory.** It is ARMv6; the 64-bit image will not
> boot. Zero 2 W → 64-bit is fine.

In Imager's **OS customisation** panel set:

- hostname: `laki-0X`
- username `laki_test_0X`, password `--Ask pool numerique--`
- Wi-Fi name and password: `--Ask pool numerique--`, and **set the Wi-Fi country**
- **Enable SSH**, and paste your public key

Leave the card in the PC afterwards.

---

## 2. Prepare the card from the PC

Windows only mounts the small FAT partition, `bootfs`. That is enough.

**2a. `config.txt`** — put the Pi in I2S slave mode. Back it up first, then make
sure it contains:

```ini
dtparam=i2c_arm=on
dtparam=i2s=on
dtoverlay=genericstereoaudiocodec
#dtparam=audio=on          # off: the ReSpeaker is the sound card
```

> ⚠️ The overlay name must be **exactly** `genericstereoaudiocodec`, no `.dtbo`.
> A typo is ignored silently and you simply get no sound card.

**2b. the overlay** — copy
`laki_receiver_PiW/boot/genericstereoaudiocodec.dtbo` into `bootfs/overlays/`.

**2c. `user-data`** (optional, saves an apt round) — add the packages the bird
needs, plus a file that stops the Wi-Fi dropping out after 10 minutes:

```yaml
packages:
  - python3-venv
  - libportaudio2
  - libsndfile1
  - rsync
  - alsa-utils
  - i2c-tools
  - libopenblas0
  - libgfortran5

write_files:
  - path: /etc/NetworkManager/conf.d/wifi-powersave-off.conf
    content: |
      [connection]
      wifi.powersave = 2
```

> `libopenblas0` and `libgfortran5` are **not optional**: the ARMv6 numpy/scipy
> wheels link against them. Without them the venv builds fine and then
> `import scipy` fails.
>
> **No internet on site?** Then this step cannot work and neither can `pip`.
> There is a ready-made offline kit — ask Pool Numérique for
> `laki-03-offline-kit`, which installs a whole receiver from the SD card with
> one command.

---

## 3. Wiring

**Power the Pi off first.** The ReSpeaker runs on **5 V, never 3.3 V**.

| Raspberry Pi | physical pin | ReSpeaker |
|---|---|---|
| 5V | 2 or 4 | 5V |
| GND | 6, 9, 14, 20, 25, 30, 34, 39 | GND |
| GPIO18 · PCM_CLK | **12** | I2S_BCLK |
| GPIO19 · PCM_FS | 35 | I2S_LRCLK |
| GPIO20 · PCM_DIN | 38 | I2S_DIN_XIAO |
| GPIO21 · PCM_DOUT | 40 | I2S_DIN_SEC |
| GPIO2 · SDA | 3 | SDA |
| GPIO3 · SCL | 5 | SCL |
| GPIO17 | 11 | button leg 1 (sender only) |
| GND | any free | button leg 2 |

> The two traps we actually hit: **BCLK is pin 12** (count from the corner of the
> header), and **dead I2S data wires** give perfect clocks and pure noise. Both
> are checked in step 5.

---

## 4. First boot and the code

First boot takes 5–10 minutes on a Zero W v1. `Connection refused` meanwhile is
normal. Then, from your PC:

```bash
ssh laki_test_0X@laki-0X.local
```

Copy the bird's folder from this repository into `~/laki`, plus the shared
assets:

```bash
# from this repository, on your PC
scp -r laki-0X/* laki_test_0X@laki-0X.local:~/laki/
scp -r laki_receiver_PiW/birds laki_receiver_PiW/sounds laki_test_0X@laki-0X.local:~/laki/
ssh laki_test_0X@laki-0X.local 'cd ~/laki && sed -i "s/\r$//" *.sh && chmod +x *.sh'
```

> ⚠️ The `sed -i 's/\r$//'` is **not optional** if you copied from Windows. A
> shell script with CRLF line endings fails as `/bin/sh^M: bad interpreter`.

---

## 5. Check the hardware before going further

```bash
arecord -l                                 # want: card 0: GenericStereoAu
pinctrl get 2,3,18,19,20,21                # the six must read a0
time arecord -D hw:0,1 -f S16_LE -c 2 -r 48000 -d 3 /tmp/t48.wav
```

- `real ≈ 3 s` → the module is at 48 kHz. Good, nothing to flash.
- `real ≈ 9 s` → the module is at 16 kHz. See §6 of the long receiver guide.

Then, after step 6, check the data wires are alive in a quiet room:

```bash
arecord -D hw:0,1 -f S16_LE -c 2 -r 48000 -d 2 /tmp/t.wav
~/laki/.venv/bin/python -c "import soundfile as sf,numpy as np;x,_=sf.read('/tmp/t.wav',dtype='int16');print('rms %.4f'%np.sqrt(np.mean((x[:,0]/32768.)**2)))"
```

**rms below 0.01 is good.** 0.5–0.7 means the Pi is reading random bits —
replace the GPIO20/GPIO21 wires.

---

## 6. Python environment

```bash
python3 -m venv --system-site-packages ~/laki/.venv
~/laki/.venv/bin/pip install numpy scipy sounddevice soundfile
~/laki/.venv/bin/python -c "import numpy, scipy, sounddevice, soundfile; print('ok')"
```

> `--system-site-packages` is required. ⏳ On a Zero W v1 this takes **20–40
> minutes** — ARMv6 wheels, one core. That is normal, go and do something else.
>
> Do **not** use `requirements.txt` on a receiver: it pulls sherpa-onnx,
> onnxruntime and scikit-learn, none of which exist for ARMv6 or are needed.

---

## 7. Start it at boot

```bash
sudo ~/laki/install_autostart.sh
```

It detects the role on its own: `laki-send.sh` present → sender, otherwise
receiver. It runs the **launcher script**, not `laki.py` directly, which is what
loads `laki.conf`.

> ⚠️ Make sure the unit says **`Restart=always`**, not `on-failure`. When the
> ReSpeaker stops clocking, `laki.py` stops in a way systemd reads as a clean
> exit, so `on-failure` never restarts it and the bird stays silent.
>
> ```bash
> grep ^Restart /etc/systemd/system/laki.service     # want: Restart=always
> ```

---

## 8. Link it to the sender

On the **sender**, give it the receiver's key and add it to `peers.txt`:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub laki_test_0X@laki-0X.local
echo 'laki_test_0X@laki-0X.local' >> ~/laki/peers.txt
sudo systemctl restart laki
```

> Always use the **`.local` name, never an IP**. An IP follows the board, not the
> card, and changes with the router. `.local` is answered by avahi on the birds
> themselves and keeps working on a bare router with no internet.
>
> `peers.txt` is read **once at startup** — restarting the sender is required.

---

## 9. Check the whole chain

```bash
# on the sender
cd ~/laki && rsync -q --timeout=20 sounds/laki_in.wav laki_test_0X@laki-0X.local:~/laki/sounds/ && echo "rsync OK"
# on the new bird, ~20 s later
grep "pattern:" /tmp/laki.log | tail -1
```

Expected: `pattern: laki_in.wav (3.0s) rendered in this bird's voice in 17s`.

Then whistle into the sender and say **"Lucky"**. The flock should answer.

---

## Two rules

1. **Never `kill -9` `laki.py`.** It leaves the ReSpeaker wedged and only a power
   cut fixes it. Use `./laki-receiver.sh stop`, Ctrl-C, or `systemctl stop laki`.
2. **After re-flashing a card**, clear the old SSH host key or the sender's rsync
   will refuse to connect: `ssh-keygen -R laki-0X.local` on the sender.
