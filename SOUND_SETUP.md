# SOUND SETUP — connect to a bird and tune its voice

A step-by-step guide for someone who has never touched this installation.
No programming needed. You will type a few lines into a black window; every line
you need is written out below, ready to copy.

**Before you start, ask Pool Numérique for three things:**

1. the **Wi-Fi name and password** of the installation → `--Ask pool numerique--`
2. the **password of the birds** → `--Ask pool numerique--`
3. which bird you want to change (`laki-01`, `laki-02`, `laki-03` or `laki-04`)

> ⚠️ Your computer must be connected to the **same Wi-Fi as the birds**.
> Nothing below works otherwise. There is no internet on that network — that is
> normal, the installation does not need any.

---

# Part 1 — Connect to a bird

## Step 1. Open a terminal

| your computer | what to open |
|---|---|
| **Windows** | press `Windows`, type `powershell`, press Enter |
| **Mac** | press `Cmd + Space`, type `terminal`, press Enter |
| **Linux** | `Ctrl + Alt + T` |

A window with text appears. This is where everything happens.

## Step 2. Connect

Type this and press Enter. Replace `04` with the bird you want:

```bash
ssh laki_test_04@laki-04.local
```

The user name always matches the bird: `laki_test_02` for `laki-02`,
`laki_test_03` for `laki-03`, and so on. (laki-01's user is `laki_test`, with no
number.)

**The first time only**, it asks:

```
Are you sure you want to continue connecting (yes/no)?
```

Type `yes` and press Enter.

Then it asks for the password:

```
laki_test_04@laki-04.local's password:
```

Type the password from Pool Numérique and press Enter.

> 👁️ **Nothing appears while you type the password.** No dots, no stars, nothing.
> This is normal and deliberate. Keep typing and press Enter.

When it works, the line on the left changes to something like:

```
laki_test_04@laki-04:~ $
```

**You are now inside the bird.** Everything you type from here runs on the bird,
not on your computer.

## If it does not connect

| what you see | what to do |
|---|---|
| `Could not resolve hostname` | Try the number instead of the name: `ssh laki_test_04@192.168.1.24` (laki-01 is `.21`, laki-02 `.22`, laki-03 `.23`, laki-04 `.24`). If that fails too, your computer is not on the right Wi-Fi. |
| `Connection timed out` | The bird is off, or you are on the wrong Wi-Fi. Check it is powered: the green light should flicker. |
| `Permission denied` | Wrong password. Ask Pool Numérique again. |
| `HOST IDENTIFICATION HAS CHANGED` | The bird's card was replaced. Run `ssh-keygen -R laki-04.local` on your computer, then connect again. |

> After a power cut, give the birds **2 to 3 minutes** before expecting an answer.

---

# Part 2 — Change how a bird sounds

## Step 3. Go to the bird's folder

Type this and press Enter:

```bash
cd ~/laki
```

Nothing visible happens. That is correct — you have just moved into the folder
where everything lives. To see what is there:

```bash
ls
```

## Step 4. Open the sound file

Every sound setting of a bird lives in **one single file**, called `laki.conf`.
Open it with:

```bash
nano laki.conf
```

A simple text editor fills the window. Move around with the **arrow keys** —
the mouse does not work here.

## Step 5. Change a value

The lines that control the sound look like this:

```sh
export LAKI_VOLUME=75
FLAGS="$FLAGS --birdiness 0.1"
FLAGS="$FLAGS --reverb 0.2"
FLAGS="$FLAGS --shift -12"
```

To change one, move the cursor to the number and edit it. **Change one thing at a
time** — it is much easier to hear what a single change did.

Anything after a `#` is a comment: it explains the line and changes nothing.
To switch a line **off**, put a `#` at the start of it.

## Step 6. Save and quit nano

Three keystrokes, in this order:

1. `Ctrl + O` → it asks `File Name to Write: laki.conf` → press **Enter**
2. `Ctrl + X` → quits

(On a Mac this is the `Ctrl` key, **not** `Cmd`.)

## Step 7. Apply the change and listen

```bash
sudo systemctl restart laki
```

It asks for the password again (same one, still invisible as you type).

Wait **about 90 seconds**. The bird reloads, re-sings the melody it already knows
with its new voice, and goes back to waiting.

> 🎧 You do **not** need to whistle again. The melody is re-rendered with the new
> voice at every restart, so the change is audible immediately.

To watch it come back:

```bash
tail -f /tmp/laki.log
```

You will see lines appear. When you read
`RECEIVER: waiting for a peer's PLAY broadcast`, the bird is ready.
Press `Ctrl + C` to stop watching (this stops the *watching*, not the bird).

---

# Part 3 — What you can change

All of these go in `laki.conf`. The most useful ones are at the top.

| setting | default | what it does |
|---|---|---|
| `--shift` | varies | **the pitch.** In semitones. `-12` is one octave down, `+12` one octave up. **This is the big one.** |
| `--birdiness` | 0.1 – 0.3 | 0 = a faithful whistle, 1 = a full bird: faster, breathier, less human |
| `--reverb` | 0.12 – 0.2 | how much room. 0 = dry, 1 = drowned |
| `--tail` | 0.6 – 0.9 | how long the reverb lasts, in seconds |
| `--dry` | 0.65 – 0.7 | how much *direct* voice. Below 0.5 the melody gets smeared |
| `--texture` | 0.1 – 0.25 | 0 = pure tone, 1 = fully recoloured with real bird grain |
| `--bend` | 0.2 – 0.3 | how much each note wanders in pitch. Higher = more alive, less precise |
| `--stages` | 1 | reverb passes, 1 to 3. More = more echo-like |
| `LAKI_VOLUME` | 75 | loudness in %. 100 is maximum |

### About the pitch, because it is the subtle one

- `--shift -12` → one octave **below** the whistle
- `--shift -5` → a fourth below
- **no `--shift` line at all** → **automatic**: the bird places the melody in a
  natural whistling register on its own

`laki-03` is a special case: it has **no** `--shift` line and instead has
`export LAKI_SHIFT_OFFSET=1`. That means "automatic, **then** one semitone up" —
it keeps following laki-01 and sits just above it. If you write `--shift 1`
there instead, you turn the automatic mode off and get something quite different.

### Only on laki-01: the waiting sound

When you whistle a new melody into laki-01, it takes about **20 seconds** before
the flock can sing it: the recording has to travel to the three other birds, and
each of them needs ~17 s to rebuild it in its own voice. During that wait,
laki-01 repeats a short cue so the room knows something is happening — and when
the others are ready, all four sing your melody together.

Three cues are available. Change the name, save, restart (Steps 6 and 7):

```sh
export LAKI_WAIT_CUE=nest       # nest | question | tick | off
export LAKI_WAIT_EVERY=1.2      # seconds between two repeats
export LAKI_PEER_RENDER=18      # seconds given to the others before the chorus
```

| name | what it sounds like |
|---|---|
| `nest` | a little phrase — *bi boup … la la la … bi … la la … looo …* — low, soft, with pauses between the groups. About 5 s, then it repeats. **The default** |
| `question` | a short rising chirp, like a bird asking a question |
| `tick` | three tiny high clicks, a small mechanism at work |
| `off` | silence — the wait is the same length, just quiet |

You can listen to all of them as .wav files before deciding: they are in
`waiting-sound-propositions/` next to this guide.

If the chorus starts **before** the other birds are ready, raise
`LAKI_PEER_RENDER`. If you are impatient, lower it — but below about 18 the
slower birds will still be rendering and will miss the first chorus.

---

# Part 4 — The flock as it is tuned today

Changing one bird changes the chord. This is the current balance:

| bird | timbre | pitch | character |
|---|---|---|---|
| laki-01 | bright, light reverb | **automatic** | the one you whistle into |
| laki-02 | round, long tail | **−12** | the deep one |
| laki-03 | round, long tail | **automatic +1** | the high one |
| laki-04 | bright, light reverb | **−11** | deep, just beside laki-02 |

laki-02 and laki-04 are deliberately **one semitone apart**: they beat gently
against each other instead of singing in unison. If you move one, consider the
other.

---

# Part 5 — Try a change without saving it

Useful to test an idea before committing. This runs the bird by hand, with your
settings, for as long as you watch it.

```bash
sudo systemctl stop laki
cd ~/laki
./laki-receiver.sh --shift -5 --reverb 0.4
```

(On **laki-01**, the sender, the script is `./laki-send.sh` instead.)

You will hear the result. Press `Ctrl + C` to stop. Then put the bird back to
normal:

```bash
sudo systemctl start laki
```

Nothing was saved — `laki.conf` is untouched. If you liked it, go back to
Step 4 and write the values into the file properly.

---

# Part 6 — Rules, and what to do if it goes wrong

### Three rules

1. **Never unplug a bird while it is singing.** Shut it down properly:
   `sudo poweroff`, wait for the green light to stop, then cut the power.
2. **Never use `kill -9`** on anything. It leaves the sound card stuck and only
   a full power cut fixes it. Use `sudo systemctl stop laki`.
3. **Change one setting at a time.** Otherwise you will not know what did what.

### If a bird goes silent

```bash
systemctl status laki
```

- `active (running)` → it is alive and waiting; it only sings when laki-01 tells
  it to. Try saying **"Lucky"** near laki-01.
- anything else → restart it: `sudo systemctl restart laki`

### If you made a mess of laki.conf

Every bird keeps its original file. List the backups:

```bash
ls ~/laki/laki.conf*
```

Restore the one you want and restart:

```bash
cp ~/laki/laki.conf.bak-SOMETHING ~/laki/laki.conf
sudo systemctl restart laki
```

The original settings are also written down in this repository, in each bird's
folder (`laki-04/laki.conf` and so on), so nothing is ever lost.

### To leave the bird

```bash
exit
```

That closes the connection. The bird keeps running on its own — it starts by
itself at every power-up and restarts itself if it ever crashes.

---

## Quick reference

```bash
ssh laki_test_04@laki-04.local     # connect (password: --Ask pool numerique--)
cd ~/laki                          # go to the folder
nano laki.conf                     # edit the sound    (Ctrl+O, Enter, Ctrl+X to save)
sudo systemctl restart laki        # apply, wait ~90 s
tail -f /tmp/laki.log              # watch it come back (Ctrl+C to stop watching)
systemctl status laki              # is it alive
exit                               # leave
```
