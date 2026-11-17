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

## One-time setup

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

## Making a character

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
- Arms crossed in front of the body stay part of the body and do not move.
- No visible neck: a plain one is added under the face.

## What the character can do

Each package lists its abilities (blink, speak, head turn, hair sway, each
arm, legs) and the settings page shows what it cannot do. Blinking and the
open mouth are drawn from the character's own colours and stay hidden until
used, so a character at rest looks exactly like its picture.

## Use of pictures and voices

Only use pictures and voices you have the right to use. The device ships with
no characters made from other people's work, and a package never contains
API keys or memories.
