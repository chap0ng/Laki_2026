# Laki — the connected bird (`laki.py`)

Replaces the student's `laki/src/laki_controller.py` + `laki_listener.py` +
`laki_whistler.py` with ONE process that keeps ONE duplex audio stream open for
the whole session (the student's design re-opened the device on every mode
switch and spawned `bird.py` as a subprocess).

## Hardware (since 2026-09-03: ReSpeaker Lite over I2S, not USB)

* Overlay `genericstereoaudiocodec` (Vytas' `~/genericstereoaudiocodec.dts`,
  `dtparam=i2s=on` in `/boot/firmware/config.txt`) → ALSA card
  `GenericStereoAu`: playback `hw:0,0`, capture `hw:0,1`, 2 ch, S16/S32.
* The ReSpeaker is I2S clock **master at 48 kHz**. ALSA accepts any nominal
  rate but the data flows at 48 k (a "4 s" capture at nominal 16 k takes
  1.35 s), so `laki.py` runs the whole engine at `NATIVE_SR = 48000` and
  decimates 1:3 for the 16 kHz wake-word model.
* No hardware mixer: `laki.py` applies its volume as a software gain on every
  output block (`LAKI_VOLUME`, default 75 % = −12.75 dB, same scale as the old
  softvol). `~/.asoundrc` (written by `setup-pi.sh`) still puts a softvol on
  `default` so `aplay`/`speaker-test` from the shell are attenuated too.
* Pi user is whatever `setup-pi.sh user@host` was run with (`laki_test` on
  the 2026-09-03 system); `laki.service` is templated accordingly.
* Steady state in LISTEN mode: ~40 % of one core, ~160 MB RSS (Zero 2 W).

## Interaction

| you                        | bird                                                  |
|----------------------------|-------------------------------------------------------|
| power on                   | READY cue (two rising notes) → listens for "Lucky"     |
| say **"Lucky"**            | whistles the stored phrase (+ tells peer birds to)     |
| press the button           | LISTENING cue (one up-chirp) → training mode           |
| whistle (any number of times) | answers each one; the *last* answer is the draft    |
| press the button again     | draft saved as the phrase → STORED cue (three falling notes), pushed to peers |
| press the button with no whistle recorded | NOTHING cue (low double note), phrase unchanged |

Phrase lives in `sounds/laki_out.wav`. Voice = Vytas' forest recipe
(`VOICE` dict at the top of `laki.py`, texture from `birds-all/`).

## Running on the Pi (`~/laki`)

```
./laki.sh            # run in the foreground; log on screen (+ /tmp/laki.log); Ctrl-C stops
./laki.sh button     # press the button, from a second terminal
./laki.sh stop       # stop a bird started elsewhere (SIGTERM, clean close)
```

Options after `./laki.sh`: `--wake sherpa|oww`, `--threshold X`, `--no-wake`, `--debug`.

Autostart on boot: `sudo cp ~/laki/laki.service /etc/systemd/system/ && sudo systemctl enable --now laki`
(`journalctl -u laki -f` for the log; `./laki.sh button` still works).

## Buttons (any of these, all at once)

* `./laki.sh button` over ssh (SIGUSR1)
* USB HID button — any key from an input device whose name contains
  `BUTTON_HID_NAME` (`hid 8808:6600`, the student's button; needs `usermod -aG input laki`)
* GPIO: BCM pin 17 shorted to GND with a jumper wire — the cheapest "button"
  until the real one arrives. Needs `.venv/bin/pip install gpiozero lgpio`.

## Wake word: why sherpa-onnx, not the student's openwakeword model

Tested on the Pi with macOS-TTS clips in 4 voices:

| clip                | student's `Lucky_Lucky.onnx` (openwakeword) | sherpa-onnx KWS, keyword `LUCKY` |
|---------------------|------------------|-------------|
| "lucky lucky"       | 0.43 – 1.00 ✓    | ✓           |
| "lucky"             | 0.00 – 0.03 ✗    | ✓ (4/4)     |
| "hey lucky"         | 0.00 – 0.13 ✗    | ✓           |
| "I feel so lucky today" | 0.00 ✓ (ignored) | fires (contains "lucky") |
| "tell me the weather" | 0.00 ✓          | silent ✓    |

* The double "Lucky Lucky" model does not fire on a single "Lucky" at all.
* sherpa-onnx keyword spotting (`sherpa-onnx-kws-zipformer-gigaspeech-3.3M`,
  in `wake/kws/`) takes keywords as plain text — no training. Change
  `WAKE_WORDS` in `laki.py` and restart. Cost of a one-word name: any sentence
  containing "lucky" triggers it. Tune `KWS_THRESHOLD` (0.1 loose … 0.5 strict).
* openwakeword stays available (`--wake oww`) if a custom single-word "Lucky"
  model is ever trained (Colab notebook in the openWakeWord repo, ~1 h; short
  words give more false triggers). Porcupine refuses "Lucky" as too short;
  Vosk-with-grammar and microWakeWord are the other options, not needed now.

## Several birds

* `peers.txt`: one ssh host per line (`laki@laki-2.local`). This Pi's key must
  be in their `authorized_keys`. When a phrase is stored it is rsync'ed to each
  peer's `~/laki/sounds/`; peers reload the file automatically.
* On wake, a UDP broadcast (`LAKI PLAY`, port 5005) makes every bird on the
  LAN whistle at once — each peer also runs `laki.py`, with or without its own
  wake word (`--no-wake` for the button-less ones if you want only the main
  bird to listen).

## Deps added to the Pi venv
`sherpa-onnx sentencepiece` (wake), `openwakeword onnxruntime scikit-learn requests tqdm`
(optional oww backend; openwakeword installed `--no-deps` because tflite-runtime
has no aarch64/py3.13 wheel).

## All parameters

See `PARAMETERS.md` (flags, environment variables, code constants).
