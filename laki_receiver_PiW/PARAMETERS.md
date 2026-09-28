# Laki — parameters

Everything you can tune, where it lives, and what it does. Three layers:

1. **command-line flags** — per run, `./laki.sh <flags>` (forwarded to `laki.py`)
2. **environment variables** — per run, `LAKI_X=... ./laki.sh`
3. **constants in the code** — the defaults; edit `laki.py` (voice, wake, button)
   or `bird.py` (capture and analysis), then restart

Quick examples:

```
./laki.sh --shift -3 --reverb 0.2 --tail 1.0 --dry 0.6      # lower, roomier voice
./laki.sh --hum 0                                          # whistles only
LAKI_TRAIN_LEVEL=0.15 ./laki.sh                            # stricter training gate (default 0.08)
LAKI_VOLUME=60 LAKI_PRIME_MS=300 ./laki.sh                 # quieter, more output lead
./laki.sh --help                                           # the flags, from the script itself
```

### Command line (`./laki.sh <flags>`, all optional)

| flag | default | effect |
|---|---|---|
| `--birdiness X` | 0.3 | 0 = faithful whistle, 1 = full bird: faster phrasing (+20 % speed at 1), +3 semitones at 1, more breath noise and pitch drift |
| `--reverb X` | 0.12 | wet amount 0..1 |
| `--dry X` | 0.7 | direct-voice level 0..1 (lower = wetter mix; < 0.5 smears the melody) |
| `--stages N` | 1 | serial reverb passes 1-3 (more = more diffuse, echo-like) |
| `--tail S` | 0.6 | total reverb tail in seconds, split across stages |
| `--texture X` | 0.25 | bird-grain morph 0..1: 0 pure tone, 1 fully recoloured by grains from `birds/` |
| `--shift ST` | auto | semitones relative to your pitch (negative = lower). Auto lifts the reply's median to 1200 Hz but never lowers it |
| `--bend ST` | 0.3 | max per-note random pitch bend, semitones; each note eases toward a random offset |
| `--hum 0/1` | 1 | 1 = accept hummed input too (pitch floor 80 Hz, onset band 120-2500 Hz); 0 = whistles only (300 Hz floor, 600-4000 Hz band) |
| `--wake sherpa/oww` | sherpa | wake-word backend |
| `--threshold X` | 0.3 / 0.6 | wake detection threshold (sherpa: 0.1 loose .. 0.5 strict) |
| `--no-wake` | | skip the wake model (button and peers only; saves ~40 % CPU) |
| `--debug` | | print openwakeword scores > 0.1 |

### Environment variables (`LAKI_X=... ./laki.sh`)

| variable | default | effect |
|---|---|---|
| `LAKI_VOLUME` | 75 | output level in %, softvol-style dB scale (100 = 0 dB, 75 = −12.75 dB, 1 = silent soak) |
| `LAKI_TRAIN_LEVEL` | 0.08 | absolute whistle-band level a capture must exceed in training (each capture logs its `level`) |
| `LAKI_LATENCY` | 0.3 | PortAudio buffer depth in seconds, both directions |
| `LAKI_PRIME_MS` | 200 | output lead kept ahead of the DAC (rebuilt after any underrun); raise if `xrun` lines appear |

### Constants at the top of `laki.py`

| name | default | effect |
|---|---|---|
| `VOICE` | see flags | the voice defaults the flags override |
| `WAKE_WORDS` | LUCKY, HEY LUCKY | sherpa keywords, plain upper-case text |
| `KWS_THRESHOLD` / `WAKE_THRESHOLD` | 0.3 / 0.6 | same as `--threshold` |
| `WAKE_COOLDOWN` | 3.0 s | minimum time between two wake triggers |
| `BUTTON_GPIO` | 17 | BCM pin of the button (to GND, internal pull-up) |
| `BUTTON_DEBOUNCE` | 0.4 s | lockout between accepted presses |
| `BUTTON_GPIO_HOLD` | 0.03 s | pin must stay low this long to count |
| `BUTTON_HID_NAME` | hid 8808:6600 | USB button device name substring |
| `CLEAN.gap_ms` | 80 | unvoiced holes shorter than this are bridged (breath) |
| `CLEAN.min_note_ms` | 40 | voiced islands shorter than this are dropped |
| `CLEAN.pitch_ms` / `loud_ms` | 30 / 40 | pitch and loudness smoothing windows |
| `STALL_SECONDS` | 3.0 | a mic read blocked this long = device dead, exit |
| `UDP_PORT` | 5005 | peer broadcast port |

### Constants in `bird.py` (capture and analysis)

| name | default | effect |
|---|---|---|
| `SILENCE_HOLD` | 0.70 s | silence that ends a phrase (gaps shorter than this stay inside one phrase) |
| `MAX_PHRASE` | 5.0 s | hard cap on capture length |
| `ONSET_FACTOR` | 6.0 | capture starts at noise floor × this (or `LAKI_TRAIN_LEVEL`, whichever is higher) |
| `RELEASE_FACTOR` | 1.5 | below noise floor × this counts as silence |
| `NOISE_FLOOR_MIN` / `MAX` | 0.002 / 0.020 | clamp on the calibrated room noise |
| `PREROLL` | 6 blocks | audio kept before the onset (≈100 ms at 16 k) so the attack isn't clipped |
| `FMIN` / `HUM_FMIN` / `FMAX` | 300 / 80 / 4000 Hz | pitch search range (whistle / hum mode) |
| `WHISTLE_REGISTER` | 1200 Hz | where auto `--shift` places the reply's median pitch |
| `YIN_THRESHOLD` | 0.15 | voicing strictness (lower = stricter, fewer false notes) |
| `FRAME` | 1024 (set by laki.py) | analysis frame, 64 ms at 16 k; shorter = faster tracking, noisier pitch |
