#!/usr/bin/env python3
"""Turn one character picture into a character package for the device.

Runs the whole chain on this computer:

  1. find the body parts with the See-through model (parts_model.py),
     or read labels saved earlier (--labels);
  2. remove a plain background, keeping every labelled part (prepare.py);
  3. cut the picture into layers along the labels, and draw the closed
     eyes and open mouth it does not show (partsplit.py);
  4. mesh and rig the layers with the image2live2d rigger;
  5. improve head movement and mouth (refine.py);
  6. write NAME.char: the puppet, a preview, a persona to edit, and a report
     of what the character can and cannot do.

Copy the .char file to the device through its web page, or on a USB stick.

Usage:
  make_character.py IMAGE --name NAME [--out FILE.char] [--author TEXT]
                    [--persona FILE.md] [--labels MASKS.npz]
                    [--see-through DIR --weights FILE] [--device auto|cpu|mps|cuda]
                    [--keep DIR]
"""
import argparse
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "core"))

import partsplit  # noqa: E402
import prepare  # noqa: E402
import refine  # noqa: E402
from companion import package  # noqa: E402

PERSONA_TEMPLATE = """# {name}

You are {name}, a character who lives on a small screen on the user's desk
and talks with them by voice.

Describe {name} here: personality, background, likes and dislikes, and how
they treat the user. Keep it in the second person ("You are...").

## How you speak

Your replies are spoken aloud, so keep them short and natural: one to three
sentences unless asked for more. No lists, headings or emoji.

## Greeting

Hi, I'm {name}. What shall we talk about?
"""

DEFAULT_BEHAVIOUR = {
    "emotions": ["neutral", "happy", "sad", "angry", "surprised", "embarrassed"],
    "idle": {"liveliness": 1.0},
}


def preview(image, masks, size=512):
    """A square picture of the head and shoulders, for menus."""
    face = masks[partsplit.PARTS.index("face")] | masks[partsplit.PARTS.index("hair")]
    rgba = image.convert("RGBA")
    if not face.any():
        out = rgba.copy()
        out.thumbnail((size, size))
        return out
    ys, xs = np.nonzero(face)
    cx, cy = (xs.min() + xs.max()) / 2.0, (ys.min() + ys.max()) / 2.0
    side = 1.6 * max(xs.max() - xs.min(), ys.max() - ys.min())
    box = (int(cx - side / 2), int(cy - side * 0.4), int(cx + side / 2), int(cy + side * 0.6))
    canvas = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
    canvas.paste(rgba, (-box[0], -box[1]))
    return canvas.resize((size, size), Image.LANCZOS)


def find_labels(image, args):
    if args.labels:
        masks = np.load(args.labels)["masks"]
        return masks, "read from %s" % args.labels
    if not (args.see_through and args.weights):
        raise SystemExit("give --labels, or --see-through and --weights to run the part-finding model")
    import parts_model
    import torch
    device = parts_model.pick_device(args.device, torch)
    model = parts_model.load_model(args.see_through, args.weights, device)
    return parts_model.label(model, image), "found by the See-through model on %s" % device


def rig(layers_dir, out_path, name):
    run = subprocess.run([sys.executable, "-m", "image2live2d", layers_dir, "-o", out_path, "-n", name],
                         capture_output=True, text=True, cwd=os.path.dirname(out_path))
    if run.returncode != 0 or not os.path.exists(out_path):
        tail = (run.stdout + run.stderr).strip().splitlines()[-3:]
        raise RuntimeError("the rigger failed: %s" % " / ".join(tail))


def make(image_path, name, args, work):
    report = {"source": os.path.basename(image_path), "steps": []}
    step = report["steps"].append
    original = Image.open(image_path)
    original.load()
    masks, how = find_labels(original.convert("RGB"), args)
    step("parts " + how)
    image, notes = prepare.prepare(original, masks)
    for note in notes:
        step(note)
    layers, split_report = partsplit.split(image, masks)
    layers_dir = os.path.join(work, "layers")
    os.makedirs(layers_dir, exist_ok=True)
    for role, array in layers:
        Image.fromarray(partsplit.pad_square(array), "RGBA").save(
            os.path.join(layers_dir, "%02d_%s.png" % (partsplit.ORDER[role], role)))
    step("cut into %d layers" % len(layers))
    rigged = os.path.join(work, "rigged.inp")
    rig(layers_dir, rigged, name)
    step("rigged")
    with open(rigged, "rb") as f:
        puppet_bytes, refine_report = refine.finish(f.read())
    step("head movement and mouth refined")

    report["warnings"] = split_report["warnings"]
    report["capabilities"] = split_report["capabilities"]
    report["layers"] = split_report["layers"]
    report["refine"] = refine_report
    shot = io.BytesIO()
    preview(image, masks).save(shot, "PNG")
    persona = PERSONA_TEMPLATE.format(name=name)
    if args.persona:
        with open(args.persona, encoding="utf-8") as f:
            persona = f.read()
    manifest = {
        "format": package.FORMAT,
        "id": package.slug(name),
        "name": name,
        "kind": "puppet",
        "author": args.author or "",
        "licence": "Made from a picture supplied by the user, who is responsible for having the right to use it.",
        "created": datetime.date.today().isoformat(),
        "capabilities": split_report["capabilities"],
    }
    files = {
        "persona.md": persona,
        "voice.json": json.dumps({"note": "Choose the voice on the device. No keys are stored here."}, indent=1),
        "behaviour.json": json.dumps(DEFAULT_BEHAVIOUR, indent=1),
        "visual/puppet.inp": puppet_bytes,
        "preview.png": shot.getvalue(),
        "studio/report.json": json.dumps(report, indent=1),
    }
    return package.build(files, manifest), report


def main(argv):
    parser = argparse.ArgumentParser(description="Turn a character picture into a .char package.")
    parser.add_argument("image")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out")
    parser.add_argument("--author")
    parser.add_argument("--persona")
    parser.add_argument("--labels")
    parser.add_argument("--see-through")
    parser.add_argument("--weights")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--keep", help="keep the working files (layers, rigged puppet) in this folder")
    args = parser.parse_args(argv[1:])
    out = args.out or package.slug(args.name) + ".char"
    try:
        if args.keep:
            os.makedirs(args.keep, exist_ok=True)
            data, report = make(args.image, args.name, args, os.path.abspath(args.keep))
        else:
            with tempfile.TemporaryDirectory() as work:
                data, report = make(args.image, args.name, args, work)
    except (ValueError, RuntimeError) as error:
        print("cannot make this character: %s" % error, file=sys.stderr)
        return 1
    with open(out, "wb") as f:
        f.write(data)
    print("wrote %s (%.1f MB)" % (out, len(data) / 1e6))
    for warning in report["warnings"]:
        print("  note: " + warning)
    missing = [k for k, v in report["capabilities"].items() if not v]
    if missing:
        print("  cannot: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
