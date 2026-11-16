# Trial: the splitting method on five unfamiliar images

Date: 2026-11-16. Outcome: **none of the five gave an acceptable puppet.**
The method as it stood was fitted to the first test image.

## Protocol

The owner supplied five character images the method had never been run on.
Each went through the chain exactly as committed at `fff04ed` (split, rig,
stage), with no change to code or settings. The only per-image input was the
set of marks (skin, hair, eyes, mouth), placed by me from enlarged views, as
a user would click them. Results were judged by eye from the layers and from
stage frames at rest, mouth open, and eyes closed. Every result is kept.

The images depict existing commercial characters and are not stored in this
repository; they are described instead.

## Results

| # | Picture | What happened | Verdict |
|---|---|---|---|
| 1 | Full body, front-facing, black hair and black coat, transparent background, very small (188 × 529) | The hair selection ran into the coat and trousers and took nearly the whole figure, so the body would move with the head. Closed eyes left stray specks. | Fail |
| 2 | Full body, three-quarter view, head tilted, long shaded purple hair, dynamic pose | Almost no hair found: shading splits the hair into many colours. Closed eyes were drawn as pale ovals above the eyes; the open mouth appeared by the nose. A pink blotch sits on the nose at rest. | Fail |
| 3 | Thigh-up, painterly shading, hands clasped under the chin, plain grey background with no transparency | The whole rectangle, background included, became the character. Only the top of the hair was found. Closed eyes were heavy dark shapes; the open mouth appeared on the fingers. | Fail |
| 4 | Full body, head in near-profile looking down, narrow eyes, hand at the neck, heavy shading | Only part of the hair found. The open mouth is a wide toothy shape drawn across a closed smirk. The blink is barely visible, which happens to suit narrow eyes. | Fail |
| 5 | Full body, front-facing, big eyes, mouth drawn open, textured ink outlines, high ponytail | Almost no hair found: texture and gradient. The mouth does not close, because it is open in the artwork. The blink is acceptable. | Fail |

Speed was not a problem: under two seconds to split and under ten to rig,
without a graphics card, including the 1282 × 2000 image.

## What the automatic checks said

The stage's visual test passed 14 of 14 checks on all five. Those checks
confirm that something moves in the right area and returns to rest. They do
not measure whether the result looks right, and must not be read as quality
evidence. Layers also recombined to the original, or within about a hundred
edge pixels of it, in every case; fidelity of the still image was never the
problem.

## Causes

| Cause | Images | Nature |
|---|---|---|
| Hair found by one colour: fails when hair is shaded or textured, or matches the clothing | 1, 2, 3, 4, 5 | Fundamental to picking parts by colour from a click |
| The rigger's blink and mouth assume an upright, front-facing face | 2, 4, and partly 3 | Rigger limitation |
| Eye parts sorted by fixed brightness thresholds | 2, 3, 5 | Splitter weakness |
| No transparent background | 3 | Missing preparation step |
| Mouth drawn open, or covered by hands | 5, 3 | Not handled |
| Very small faces | 1, 2 | Input quality |

The first cause is the important one. Colour and position worked on cel art
with a distinct hair colour and cannot be stretched to cover shaded art.
Finding the parts needs something that understands the picture.

## Changes made after the trial

These were written with the five results in view, so the five images are now
development data and say nothing further about generality.

- `studio/prepare.py` removes a plain background, working in from the
  picture's edges, and refuses anything that is not a plain colour rather
  than guessing. On image 3 it removed the grey background (49% of the
  picture).
- `studio/flatsplit.py` refuses a picture with no transparency, and reports
  plain-language warnings when the result should not be trusted: hair that
  covers most of the character, almost no hair found, a tilted face, a very
  small face, eyes with no white, a mouth that looks open. All five images
  now raise at least one warning and the first test image raises none. The
  warnings do not yet recognise a face in profile (image 4).

Neither change makes any of the five work. They stop a bad result being
produced silently.

## What should replace colour-picking

The cutting-from-the-original principle held up: nothing was lost or
repainted in any image. What failed is deciding *which pixels are hair, face
and so on*. The proposal is to keep the cutting and replace the deciding:

1. **A model that labels the parts** of an anime character (hair, face,
   eyes, mouth, clothing, limbs) on the original pixels, without generating
   anything. Candidates to evaluate: the part-labelling half of See-through
   used on its own; smaller anime face and body parsing models; a
   general-purpose vision model on the user's own key returning outlines.
   Criteria: runs on an Apple Silicon laptop, licence permits commercial use,
   copes with shading and three-quarter views.
2. **The marks become corrections**, not the primary input: the model
   proposes, the user fixes by clicking.
3. **A background-removal model** for pictures on scenes rather than plain
   colours.
4. **Partial rigs.** A picture cut off at the waist, or with an arm hidden,
   simply lacks those parts. The stage already connects only the controls a
   puppet has and reports them; the animation system should read that list
   and skip what is missing.

Follow-up: item 1 has been done with an existing model; see
`11-part-labelling-model.md`.

## On richer movement

The owner wants larger gestures later: moving and crossing arms,
embarrassment with body movement. Two different mechanisms are needed, and
it is worth being clear which does what.

- **Bending the original** (what a puppet does) covers breathing, sway, head
  turn, blink, mouth, hair and cloth movement, and small arm movement once
  arms are separate layers. It cannot show anything the picture does not
  contain: an arm moved across the body uncovers body that was never drawn.
- **Alternative drawings** cover anything beyond that. Hand-made Live2D
  models do this too, swapping in a separately drawn arm or expression. Here
  the alternatives could be produced by an image-editing model on the user's
  key ("the same character with arms crossed") and switched in with a short
  cross-fade. The risk is the model drifting from the original design.

A character would then be a puppet for continuous motion plus an optional
set of alternative poses for big gestures, each gesture declared with the
parts it needs so that it is skipped when the character lacks them.
