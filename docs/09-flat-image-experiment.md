# Experiment: a flat image to a rigged puppet without repainting

Date: 2026-11-16. Status: first result on one image. Promising, not proven.

## Question

The owner's earlier attempt stalled at turning a flat picture into layers:
the tool used (See-through) needs an NVIDIA graphics card, and on the one
image tried it lost ornaments and changed clothing. Can the layers instead
be cut from the original picture, with nothing repainted, on an ordinary
laptop?

## Method

1. **Split** (`studio/flatsplit.py`, new). The user marks a few points on
   the picture: one on the face skin, one on the hair, the two eyes and the
   mouth. Parts are then found by colour and position:
   - flat areas of paint are told apart from outlines by thickness;
   - hair is the paint matching the marked hair colour plus the outlines
     along it, kept where joined to the mark, plus anything it encloses
     (hair ornaments);
   - the face is the area the marked skin spans; inside it, the marked eye
     areas are divided into white, iris and lash by brightness, and the mouth
     is taken from its marked area;
   - everything else is the body.
   Where one part hides another, the hidden part is extended a short way
   underneath using the neighbouring colour. No pixel is generated.
2. **Rig** (image2live2d, existing, Apache-2.0). The layers go to the
   open-source rigger used in the earlier attempt, which builds meshes, the
   blink, mouth, head, body and breathing controls, and hair physics.
3. **Play** (`stage/`). The result is loaded by the stage and driven through
   its normal commands.

All three steps ran on a cloud machine with no graphics card. Splitting takes
about a second and rigging about four.

## What had to be fixed to make the chain work

Found by running it, not by reading:

| Problem | Fix |
|---|---|
| The stage's file reader rejected the rigger's files for omitting optional metadata | Reader made tolerant |
| The rigger blinks by fading closed-eye art in and open-eye art out; the renderer ignored that kind of instruction | Opacity bindings implemented in the renderer |
| The renderer skipped any control sitting at zero, so a blush layer meant to be off was showing | Every control is now applied every frame |
| Hair strands separated by outlines were treated as unconnected pieces | Outlines join the part they border before connection is judged |
| An eyelash touching the fringe was taken as a hair outline | Marked eye and mouth areas take priority |

The renderer changes are listed in `stage/vendor/PATCHES.md`.

## Result on the owner's test image

A full-body character with plate armour, a cape, a tiara and waist-length
hair hanging in front of the body. The image depicts an existing commercial
character, so it and its renders are not stored in this repository; the
owner has them.

| Aspect | Outcome |
|---|---|
| Fidelity | The layers put back together reproduce the original exactly. Armour, cape, tiara and hair are all present and unaltered. This is the failure the earlier attempt hit, and it does not occur here. |
| Blink | Works. The rigger's synthesised closed eyes are thick upward arcs, which reads as a cheerful expression and does not match the art's line weight. |
| Mouth | Opens and closes with speech loudness. The synthesised interior is crude at this size. |
| Head turn and tilt | Head, hair and tiara move together; the long hair stays continuous. A small dark mark appears beside the cheek in some poses. |
| Hair | Has physics and sways with head movement. |
| Body | Breathing and sway work. Arms, legs, cape and skirt do not move independently, because the body is one layer. |
| Stage visual test | All checks pass. |

## What this does and does not show

Using the status words adopted from the earlier project's brief:

| Stage of proof | State |
|---|---|
| Implemented | Yes |
| Executed end to end | Yes, on one image |
| Visually reviewed | By me, from still frames and a short animation. Not yet accepted by the owner. |
| Works on unfamiliar artwork | **No.** Tried on five further images with no acceptable result; see `10-generalisation-trial.md`. |
| Works without hand-placed marks | Not attempted. |
| Runs on the owner's Mac | Not tried; nothing in it needs a graphics card. |

Reasons to expect trouble on other images, none yet tested: painterly or
gradient-shaded art without flat colours; hair the same colour as clothing or
skin; faces in profile or three-quarter view; hands or props across the face;
very small faces.

## Follow-up: the head moved like a detached piece

The owner reviewed the animation and found the head motion wrong: it moved
as a separate block and smeared what was behind it. The cause was the
rigger's head turn, which rotates the whole head group as one flat card. With
waist-length hair in that group, the card's hinge sat near the waist.

Hand-made Live2D and Inochi2D puppets never move the head bodily. Each
part's mesh is bent so that features slide across the face as if over a
ball, the far side narrows, and the chin stays joined to the neck.
`studio/headturn.py` now rewrites a rigger puppet to do this: one shared
displacement field, taken from a ball centred on the head, warps every head
part for turning and nodding; tilting leans the head about the base of the
neck; and all of it fades out below the chin so long hair bends rather than
swings. Blink, mouth, breathing and hair physics are left alone.

On the test image the head now stays in place while the features move
within it. Remaining flaws at the extremes: the chin line can show a doubled
contour against the hair, and the lower face compresses when looking down.
Not yet reviewed by the owner.

## Known defects to work on

1. Closed-eye and mouth-interior art come from the rigger's generic
   synthesis. Better: derive them from the character's own lash line and lip
   colours.
2. The body is one layer. Splitting off the cape, skirt and arms by colour
   region would let the rigger add cloth movement and arm articulation.
3. The dark mark beside the cheek when the head turns: the fill under the
   edge of the hair needs to follow the face outline.
4. Marks are typed into a file. They need a click-on-the-picture screen, and
   automatic first guesses.
5. Full-colour (non-palette) and anti-aliased art has only been exercised by
   the synthetic test figure.

## Next

- Owner reviews the animation and stills.
- Run the unchanged method on several images the method has never seen,
  keeping every failure, before changing anything further.
- Compare against See-through on the same images once a graphics card is
  available, since the two approaches fail differently.

## Reproducing

```
pip install -r studio/requirements.txt
python studio/flatsplit.py IMAGE.png MARKS.json layers/
python -m image2live2d layers/ -o rigged.inp         # image2live2d at commit 714e7cc
python studio/headturn.py rigged.inp character.inp   # in-place head turn
stage/target/release/stage character.inp
cd studio && python -m unittest                       # 25 tests, no artwork needed
```
