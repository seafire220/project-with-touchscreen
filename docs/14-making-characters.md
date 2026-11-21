# Making a character from a picture

Status: the chain runs here on Linux (CPU only). It has not been run on a
Mac yet; the steps below are what should work there, marked *unchecked*.

The device cannot make characters itself: the part-finding model needs about
5 GB of memory (decision D-031). A laptop makes the `.char` file and you add
it to the device through its settings page.

## What the laptop needs

- Python 3.10 or newer.
- About 6 GB of free memory while the part-finding model runs, and 3 GB of
  disk for the model and libraries.
- No graphics card is needed: one picture takes about 30 seconds on four
  ordinary processor cores. On an Apple Silicon Mac the model can use the
  Mac's graphics (`--device mps`), *unchecked*.

## The easy way: Character Studio

Character Studio is the character maker: a program for a laptop or desktop computer (**Windows, Mac or
Linux**) that shows its page in the browser and runs on that computer only (`studio/app.py`). Adding and
managing characters afterwards is done on the device's own settings page, in any browser.

**You need** Python 3.10 or newer (3.12 or 3.13 is best; from [python.org](https://www.python.org/downloads/),
or Homebrew on a Mac), about 6 GB of free space, and the internet the first time. Get the project's files
(on GitHub: **Code → Download ZIP**, then unzip it), then start the studio:

| Computer | Start it |
|---|---|
| **Windows 10 or 11** | Double-click `studio\start.bat`. If Python is missing it says so: install it from python.org, ticking **Add python.exe to PATH**, and double-click again |
| **Mac** (Apple silicon: M1 or newer) | Double-click `studio/start-mac.command`. The first time, macOS may refuse a file from the internet: Control-click it, choose **Open**, then **Open** again |
| **Linux** | Run `studio/start.sh` |

A window shows what it is doing; closing that window stops the studio. All three run `studio/launch.py`,
which the first time sets up the studio's own Python environment in your home folder
(`.character-studio`; `CHARACTER_STUDIO_HOME` chooses another): PyTorch built for that computer, the
rigger and the model's libraries (a few GB, several minutes). PyTorch comes for the computer's graphics:
an NVIDIA card on Windows or Linux, the Mac's own graphics on Apple silicon, otherwise the processor, which
also works (about 30 seconds a picture on four cores). Later starts take seconds. No `git` is needed.

The page then offers to download the part-finding model once (about 1.3 GB, from its authors' pages).
After that:

1. Drop a picture in and give the character a name. A character card (the
   PNG files other AI-companion apps share, with the character's
   personality inside) brings its name and personality too: the picture
   becomes the drawing and the card who they are.
2. Watch the steps; a preview of the character moving appears when it is
   made (drawn on this computer; the device moves more smoothly).
3. Check what it can do. If an arm moved wrongly in the preview (a coat's
   side taken for an arm, say), untick it and make it again.
4. Say who the character is (the same questions as the device's settings
   page), or leave that for later.
5. Send it to the device: its address (`companion.local`, or the address the
   device shows) and the settings-page password, which is used for that one
   upload and not kept. Or save the `.char` file and add it on the device's
   settings page.

**Checked** (2026-11-21): on Linux here, a first run of `launch.py` in an empty folder, the model download
from the page, a character made with the real part-finding model, and sending it into the device's real
settings-page API. On **Windows, macOS and Linux** on GitHub's computers, every time the studio changes
(`.github/workflows/studio.yml`): the same first-run setup as a buyer's computer, the studio's tests with
that environment (a drawn test figure made into a character, rigged and packaged), and the studio started
and answering. See the latest run under **Actions → Character Studio on Windows, macOS and Linux**. The
first run (2026-11-21) passed on all three: each installed PyTorch 2.15 and the studio in two to four
minutes, passed 99 tests, and started. (Two tests need things only a developer's computer has, the device's
screen program and a photo of a face, and wait for those.) GitHub's Macs have no graphics in their virtual
machines, so the Mac's graphics were not tried there; on a real Apple-silicon Mac PyTorch uses them.

**Older computers.** An Intel Mac gets no new PyTorch (its last is 2.2, for Python 3.12 or older), so the
studio may not install there: use Apple silicon, Windows or Linux. A Mac on macOS 13 or older gets an older
PyTorch, which should work, *unchecked*. An older NVIDIA card is served by the CUDA 12.6 build the studio
asks for on Windows; on Linux, if PyTorch says the card is too old, set
`CHARACTER_STUDIO_TORCH_INDEX=https://download.pytorch.org/whl/cu126` and delete
`~/.character-studio/venv` to set up again.

## From the command line

### One-time setup

```bash
python3 -m venv ~/character-maker
```

```bash
source ~/character-maker/bin/activate
```

```bash
pip install -r studio/requirements.txt -r studio/requirements-model.txt
```

The rigger, image2live2d (Apache-2.0), is installed from its source at the
version that was tested:

```bash
pip install "git+https://github.com/Wzhang3912/image2live2d@714e7cc"
```

The part-finding model comes from the See-through project (Apache-2.0).
Fetch its code and the model weights (1.3 GB):

```bash
git clone https://github.com/shitagaki-lab/see-through ~/see-through
```

```bash
huggingface-cli download 24yearsold/l2d_sam_iter2 --local-dir ~/see-through-weights
```

### Making a character

```bash
python studio/make_character.py picture.png --name "Aria" \
    --see-through ~/see-through --weights ~/see-through-weights/checkpoint-18000.pt
```

This writes `aria.char`. Add it on the device's settings page under
**Characters**. The tool prints notes about anything it could not do, for
example:

```
wrote aria.char (2.6 MB)
  note: the mouth was found by its colour, not by the model; check that it moves in the right place
  cannot: arm left
```

Edit the persona (who the character is, how it speaks, its greeting) on the
settings page, or write it in a file beforehand and pass `--persona file.md`.
The greeting is the text under a `## Greeting` heading.

## Which pictures work

Best:

- One character, whole body or at least head and shoulders, facing the
  viewer or turned slightly.
- At least 800 pixels tall. Small pictures work but look soft, and heavily
  compressed small JPEGs show faint lines round the eyes when enlarged.
- A transparent or plain one-colour background. Busy backgrounds are refused
  for now (no background-removal model is included yet).
- Eyes open and mouth closed or slightly open.

Works, with limits:

- Faces partly in profile: turning the head shows a small patch beside the
  face at the far ends of a turn.
- Arms hanging at the sides move: each turns at the shoulder and bends at
  the elbow, and the body is painted in behind them, so the character can
  wave, put one or both hands on its hips and shrug. An arm that is mostly
  hidden (behind long hair), very thin in the picture, raised (a hand at
  the chin) or crossed in front of the body stays part of the body and does
  not move; the tool's notes say which, and gestures that need it are not
  offered. Check the preview: the part-finding model sometimes marks a coat's
  sides as arms.
- No visible neck: a plain one is added under the face.

## Also in the Live2D format (optional)

Add `--live2d` to put a Live2D-format copy of the character in the package
as well (`visual/live2d/`: `model.moc3`, `model.model3.json`, textures,
physics and motions):

```bash
python studio/make_character.py picture.png --name "Aria" --live2d \
    --see-through ~/see-through --weights ~/see-through-weights/checkpoint-18000.pt
```

The copy is converted from the finished puppet, movement for movement
(`studio/live2d_export.py`), so it moves the same as the Inochi2D version,
including the improved head movement. The tool replays both versions
against each other and prints the largest difference: a few pixels at
most (under 4 on the test characters), in poses that combine a full body
turn with a full head turn. Players that read this format, such as
Ayagami, can then show the character. No Live2D software is used or needed.

Read `19-live2d-format-licensing.md` before selling or sharing characters in
this format. The device itself still plays the Inochi2D version.

## What the character can do

Each package lists its abilities (blink, speak, head turn, hair sway, each
arm, legs) and the settings page shows what it cannot do. Blinking and the
open mouth are drawn from the character's own colours and stay hidden until
used, so a character at rest looks exactly like its picture.

## Gestures of your own, from a video

Every character gets the device's gestures and idle actions. To add one
of your own, or to make one look more like a real person, film it:

1. Film yourself (or someone who agreed to it) facing the camera, in good
   light, head and shoulders or the upper body in view, doing the gesture
   once and starting and ending still. A phone video is fine.
2. Install what the tool needs once, in the studio's Python (set up by
   `studio/start.sh`):

```bash
~/.character-studio/venv/bin/pip install -r studio/requirements-motion.txt
```

3. Make the gesture, and save it on the device (it asks for the
   settings-page password):

```bash
~/.character-studio/venv/bin/python studio/record_motion.py my-video.mp4 --name little_dance --words "do a little dance" --send companion.local
```

The first run downloads MediaPipe's face and body landmark models (about
10 MB). Use `--start` and `--end` (seconds) to take part of a longer
video, and `--kind idle` for something the character does by itself when
nobody is talking. `--out little_dance.json` writes the gesture to a file
instead.

On the device's settings page, the Animation tab plays it on the screen
(*Try it on the device*). Change its tracks there if needed, then save
it. A new gesture with `--words` can be asked for by the conversation. The
character moves as the video shows: a head turned towards the right of the
picture turns the character towards the right of its screen. The lean
towards or away from the camera is not read.

## Use of pictures and voices

Only use pictures and voices you have the right to use. The device ships with
no characters made from other people's work, and a package never contains
API keys or memories.
