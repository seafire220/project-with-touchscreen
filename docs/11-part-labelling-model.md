# Finding the parts with an existing model

Date: 2026-11-16. Outcome: an existing open model does the job my
colour-based script could not. Adopted.

## Why

The trial in `10-generalisation-trial.md` showed that finding a character's
parts by colour from marked points fails on shaded or textured hair and on
hair that matches the clothing. The owner asked for an existing project to
be used instead of extending that script.

## What was looked at

| Project | What it does | Licence | Runs on a Mac? | Verdict |
|---|---|---|---|---|
| **See-through body-part model** (`24yearsold/l2d_sam_iter2`) | Labels 19 body parts of an anime character on the original pixels. A fine-tune of SAM-HQ. Published separately from the rest of See-through. | Apache-2.0, code and weights; its model card states commercial use is permitted | Not tried. It is a standard PyTorch model with no graphics-card-specific code in its loading path, and ran here on a CPU | **Adopted** |
| See-through full pipeline | Splits a picture into up to 23 layers and repaints the hidden areas | Apache-2.0 code | No statement found. Documented for NVIDIA cards with 8–16 GB | Not needed for now; it is the route that lost ornaments in the owner's earlier attempt |
| anime-part-split (tsunehimatoi) | Splits into Live2D-style layers with each part repainted | Unknown | Unknown | Could not be inspected: access-restricted |
| Segment Anything, SAM 3 | Outlines whatever is clicked or named | Apache-2.0 / own licence | Yes | General-purpose; the fine-tune above is the anime-specific version of it |
| anime-segmentation (SkyTNT) | Character against background only | Apache-2.0 | Yes | Useful later for busy backgrounds |
| Anime-Face-Segmentation | Seven classes, face area only | Unchecked | Yes | Too coarse |
| Anzhc YOLO models | Face, eye and head detection | Unchecked; YOLO tooling is commonly AGPL | Yes | Licence risk |
| layerdivider | Layers by colour clustering | Unchecked | Yes | Same weakness as the script it would replace |
| Qwen-Image-Layered | Any picture into a few generic layers, repainted | Apache-2.0 | Too large to be practical | Not anime-aware |

A curated index, `stimQQ/awesome-image-to-layer`, was used to check for
anything missed.

## Test

The body-part model was run on the owner's six test images on a 4-core CPU,
unmodified, with no per-image settings.

| Measure | Result |
|---|---|
| Time | About 20 seconds per picture, plus 5 to load. Weights are 1.3 GB |
| Hair | Found correctly on all six, including the black-haired character in a black coat, shaded purple hair, a textured blonde ponytail, and long hair in front of armour |
| Hair ornaments | Labelled as headwear on the three characters that have them |
| Face, eyes | Found on all six, including the near-profile face |
| Mouth | Found on five; missed on the one with a very small closed smile |
| Neck | Found on all six |
| Arms and hands | Found on all six as one class covering sleeves and hands |
| Clothing | Found; the split between upper and lower garments is ragged on long coats and robes |
| Background | Ignored without being told to, on the one picture that has one |
| Mistakes seen | A sword hilt behind one character's head was labelled hair |

## What changed in the tools

- `studio/parts_model.py` runs the model and saves its labels.
- `studio/partsplit.py` cuts the picture along those labels. As before,
  every pixel is copied from the original or filled from its neighbour;
  nothing is generated. It now also cuts a neck (extended up under the chin)
  and left and right arms, and reports which parts were found and what the
  character can therefore do (blink, speak, move each arm, and so on), so a
  character missing a part is rigged with what it has.
- `studio/flatsplit.py` stays only as a fallback that needs no model.

## Result through the whole chain

Label, cut, rig, head-turn step, stage, on the six images:

| Image | Structure | Blink | Mouth |
|---|---|---|---|
| Armoured, long blonde hair | Correct | Acceptable | Opens; interior crude |
| Black hair, black coat | Correct | Acceptable | Acceptable |
| Purple hair, three-quarter view | Correct | Acceptable | Opens in the right place; too large |
| Scarf, hands under chin | Correct | **Bad**: a heavy black bar across both eyes | None: no mouth was labelled |
| Near-profile, red hair | Correct | **Bad**: a dark smear across the eye area | Acceptable |
| Blonde ponytail, pink dress | Correct | Good | Does not close: drawn open |

"Structure" means hair, face, neck, arms and body are separate layers in the
right places. That was wrong on five of six before and is right on all six
now. The remaining failures are in the closed-eye and open-mouth artwork the
rigger synthesises, and in my sorting of each eye into white, iris and lash.

These six images have now been used to choose and check this approach, so
they are development data. A claim of generality needs fresh images.

## Not yet known

- Speed and correctness on the owner's Apple Silicon Mac.
- Behaviour on non-anime styles, chibi proportions, animals, or several
  characters in one picture.
- Whether the rigger moves the newly separated arms sensibly; only the head,
  blink and mouth were reviewed.

## Next

1. Closed eyes and mouths drawn from the character's own lash line and lip
   colours, instead of the rigger's generic shapes.
2. The owner runs `parts_model.py` on their Mac to confirm it works there
   and how long it takes.
3. A fresh set of images, run without changes, as the real test.

## Sources

- Body-part model: https://huggingface.co/24yearsold/l2d_sam_iter2
- See-through: https://github.com/shitagaki-lab/see-through
- ComfyUI wrapper: https://github.com/jtydhr88/ComfyUI-See-through
- Curated index: https://github.com/stimQQ/awesome-image-to-layer
- anime-part-split: https://huggingface.co/tsunehimatoi/anime-part-split
- anime-segmentation: https://github.com/SkyTNT/anime-segmentation
- Anime-Face-Segmentation: https://github.com/siyeong0/Anime-Face-Segmentation
- Anzhc YOLO models: https://huggingface.co/Anzhc/Anzhcs_YOLOs
- CartoonSegmentation: https://github.com/CartoonSegmentation/CartoonSegmentation
