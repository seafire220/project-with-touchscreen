#!/usr/bin/env python3
"""Label the body parts of an anime character picture.

Runs the See-through body-part model (SAM-HQ fine-tuned for 19 anime body
parts; code and weights Apache-2.0, commercial use permitted) and writes its
masks to a file for partsplit.py. The model only labels pixels; it does not
repaint or generate anything.

Needs, outside this repository:
  * a checkout of https://github.com/shitagaki-lab/see-through
    (tested at commit fc4440d), passed with --see-through;
  * the weights file `checkpoint-18000.pt` (1.3 GB) from
    https://huggingface.co/24yearsold/l2d_sam_iter2, passed with --weights;
  * the packages in requirements-model.txt.

Tested on a 4-core CPU: about 20 seconds per picture and 5 seconds to load.
It should be much faster on a graphics card or on Apple Silicon ("mps"),
but neither has been tried.

Usage: parts_model.py IMAGE OUT.npz --see-through DIR --weights FILE [--device auto|cpu|mps|cuda]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

PARTS = ["hair", "headwear", "face", "eyes", "eyewear", "ears", "earwear", "nose", "mouth", "neck",
         "neckwear", "topwear", "handwear", "bottomwear", "legwear", "footwear", "tail", "wings", "objects"]


def pick_device(name, torch):
    if name != "auto":
        return name
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_model(see_through_dir, weights, device):
    import torch
    sys.path.insert(0, os.path.join(see_through_dir, "common"))
    from modules.semanticsam import SemanticSam
    model = SemanticSam(class_num=len(PARTS))
    state = torch.load(weights, map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    result = model.load_state_dict(state, strict=False)
    if result.missing_keys or result.unexpected_keys:
        raise RuntimeError("the weights do not match the model (%d missing, %d unexpected)"
                           % (len(result.missing_keys), len(result.unexpected_keys)))
    return model.to(device).eval()


def label(model, image):
    """Return a 19 x height x width boolean array for a PIL image."""
    import torch
    rgba = image.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat.alpha_composite(rgba)
    with torch.inference_mode():
        scores = model.inference(np.asarray(flat.convert("RGB")))[0]
    return (scores > 0).to("cpu", dtype=torch.bool).numpy()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("out")
    parser.add_argument("--see-through", required=True, help="path to a See-through checkout")
    parser.add_argument("--weights", required=True, help="path to checkpoint-18000.pt")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    args = parser.parse_args(argv[1:])
    import torch
    device = pick_device(args.device, torch)
    model = load_model(args.see_through, args.weights, device)
    masks = label(model, Image.open(args.image))
    np.savez_compressed(args.out, masks=masks, parts=np.array(PARTS))
    found = {PARTS[i]: int(m.sum()) for i, m in enumerate(masks) if m.any()}
    print("device %s; parts found: %s" % (device, ", ".join(sorted(found, key=found.get, reverse=True))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
