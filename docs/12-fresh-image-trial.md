# Trial on five fresh images, and the third head-movement design

Date: 2026-11-17. Status: run and reviewed by eye here, on software
graphics; not yet judged by the owner; not run on device hardware.

The owner supplied five pictures the tools had never seen, and rejected the
second head-movement design: "it wasn't really head movement, but, rather,
just an awkward deformation of the eyes and mouth". As with every trial,
the pictures show existing commercial characters, so they and the frames
made from them stay out of this repository (D-024).

## The pictures

| | Picture | Size | Background |
|---|---|---|---|
| f1 | Boy in a green school uniform, full body | 736 × 1101 JPEG | white |
| f2 | Young man in a dark uniform, full body | 152 × 451 | transparent |
| f3 | Girl with long green hair in a white dress | 208 × 453 | transparent |
| f4 | Young man in a white shirt, half body, seen from behind, looking over his shoulder | 850 × 2000 | near-white |
| f5 | Girl in a white and red outfit, full body | 190 × 525 JPEG | white |

## Part 1: the chain as it was (commit 10cce75)

| | Parts found correctly | Result |
|---|---|---|
| f1 | yes | White fringe round the hair; blink left traces of the open eye; mouth opening 9 pixels |
| f2 | yes | Passable for a tiny picture |
| f3 | yes | No neck found; mouth label 2 pixels |
| f4 | yes, including the white shirt | **Failed**: background removal cut away the white shirt, though the labels marked it; no mouth; blink a dark bar |
| f5 | yes | No mouth found, so it could not talk |

The part-finding model was right on all five. Every failure was in the
steps after it.

## Part 2: what changed

1. **Head movement** (`studio/refine.py`, replacing `headturn.py`). A tilt
   now leans the whole head, hair included, as one rigid piece about a point
   in the neck; the neck bends to follow and long hair hangs. Turning and
   nodding slide the middle of the face over a rounded surface while the
   outline of the head stays; eyes, nose and mouth move as rigid pieces and
   never change shape.
2. **The neck continues under the face** in its own shadow colour, as wide
   as the jaw, so a moving head uncovers neck instead of a hole, a smear or
   the collar. A character with no visible neck gets a plain one.
3. **Closed eyes** are drawn as a smooth lid line in the eye's own lash
   colour and weight. The rigger's own closed eye was an upward arc (a happy
   squint) and became a thick bar when the eye's box was wrong.
4. **Open mouth**: a mouth sized to the face (dark inside, teeth, tongue),
   in the lip line's colour, hidden at rest; the drawn line fades as it
   grows. A mouth the model missed is found by colour where a mouth belongs,
   or a small one is added; both are reported.
5. **Eyes are one solid layer each**, and fringe hair the model marked as
   eye goes back to the hair. Only pixels that are part of a drawn feature
   are repainted on the face beneath.
6. **Background removal** keeps every pixel the labels mark as character,
   whatever its colour, and takes the background's colour out of blended
   edge pixels (the pale fringe round a JPEG).
7. **Renderer fix**: Inochi2D expects textures premultiplied by their
   transparency when loaded; the Rust renderer did not do it, so every
   half-transparent edge was drawn too bright (vendored patch 9).

`stage/tools/pose_sheet.py` now renders each character close up in nine
poses plus a motion sweep, because the automatic checks had passed puppets
that looked wrong.

## Part 2 results: all eleven pictures

Same chain, no per-picture settings: labels → background → cut → rig →
refine → stage.

| | Turn and nod | Tilt | Blink | Mouth | Remaining faults |
|---|---|---|---|---|---|
| Alice | good | good | good | good | — |
| t1 | good | good | good | good | small pale patch by the chin at full turn |
| t2 | works | good | good | barely visible | face partly in profile: a rectangular patch shows beside it at full turn |
| t3 | good | good | pale patch over one eye | good (mouth found by colour) | |
| t4 | works | good | good | good | profile face: rectangular patch at full turn |
| t5 | good | good | good | good | — |
| f1 | good | good | good | good | — |
| f2 | good | good | good | good | tiny source: soft |
| f3 | good | good | good | good | plain added neck |
| f4 | good | good | good | small (found by colour) | the shirt now survives background removal |
| f5 | good | good | good | good (found by colour) | tiny JPEG: faint lines round the eyes when magnified |

"Full turn" is the end of the control's range; the idle movement uses
about a quarter of it.

## What is still wrong

- Faces partly in profile (t2, t4) show the corner of the hidden neck fill
  beside the face at the extremes of a turn. The fill needs a rounded shape,
  or the turn a smaller range when only one side of the face is visible.
- Very small or heavily compressed pictures (f5: 190 × 525 JPEG) show faint
  seam lines round the eyes when magnified. A recommended minimum size, or
  an anime-specific upscaler before cutting, would address it.
- Mouths found by colour are in plausible places on all three pictures, but
  the rule has only been checked on these three.
- None of this has been judged by the owner or seen on the device's screen.
