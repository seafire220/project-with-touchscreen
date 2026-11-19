# Animation tested on all eleven test characters

Status: 2026-11-19. Every gesture, idle action, mood and state played on the
real stage for each of the owner's eleven test pictures, then the full
conversation check (real core, real stage, the on-device voice). Before this,
the finished animation system had been checked end to end on one character
only (f2); the others had been used for the picture-to-character steps and,
for four of them, the first arm work.

The pictures stay out of the repository (D-024); the sheets of frames were
sent to the owner privately. Characters are named by their test labels.

## How

1. Each picture was built into a character package the way Character Studio
   builds it (`studio/make_character.py`, with the Live2D-format copy the
   device plays).
2. `stage/tools/clip_sheets.py` played the whole motion library on the
   stage program the device runs: the 19 gestures and 11 idle actions, each
   captured at its largest moment, head to hips; the 7 moods; listening,
   thinking and speaking; a head close-up through a blink, the mouth
   opening, each mood, head turns and nods, and looking around; and six
   moments through the wave, hands on hips, shrug, stretch, yawn and
   nodding off. It also records what the stage said it played, including
   the stand-in for a gesture a character cannot make.
3. `core/tests/stack_check.py` ran the real core against the real stage
   with the on-device voice: the time of day, a person speaking in
   stretches with pauses, a reply tagged with five moods, a wave and a nod,
   then twelve seconds alone.
4. Every sheet was looked at by eye.

## What was wrong, and what was changed

**Arms.** Nine arms on seven characters were cut to move on their own. Only
three came out well (t1's right arm and both of f2's), and Alice's left was
acceptable apart from the smear noted below. The others came apart or swung
wrongly:

| Character | Picture | What happened |
|---|---|---|
| t2 | Long robe and hair; one hand showing below them | Only the forearm and hand had been cut; the hand drifted off the arm |
| t3 | Hands folded at the chin | The sleeves swung out without hands, and a loose piece flew off on its own |
| t4 | One hand on the hip | Waving swung the bent arm out sideways, and the wristband stayed hanging at the elbow |
| t5 | One arm under a short cape | Only the forearm had been cut; the glove slid out with a dark streak behind it |
| f1 | Hands in pockets | Waving lifted a sleeve with no hand, with part of the jacket attached |
| f3 | Wide bell sleeves | The sleeves swung as large white blocks |
| Alice (right) | Arm under shoulder armour | Only the forearm showed, so "hands on hips" put the hand out to the side |

`studio/partsplit.py` now measures each arm against the face before letting
it move: it must start within 1.2 face heights below the chin, be at least
2.4 face heights long and no wider than the face, and its end must differ in
colour from its middle (a hand or a glove). Small separate pieces of an arm
stay with the body. These numbers separate the good arms from the bad ones
on all eleven pictures except two (below). An arm that fails stays with the
body; the gestures that need it play stand-ins: a greeting instead of a wave,
leaning back instead of hands on hips, a head tilt instead of a shrug.

**The shrug.** It needed a shoulders control, which no character made from a
picture has, so it always played as a tilt. It now plays on the forearms
(elbows in, hands turned out) when there are no shoulders to raise.

**A kept work folder.** Building again into the same work folder reused the
earlier build's layers, so an arm switched off came back. The build now
clears the folder first. Character Studio always uses a new folder, so it
was not affected.

## Results after the changes

| Character | Arms that move | Gestures | Face: blink, mouth, moods, head | Conversation check |
|---|---|---|---|---|
| Alice | Left | All play; wave and hands on hips on the left arm | All work; the "embarrassed" blush is a soft rectangle | Passed |
| t1 | Right | All play | All work | Passed |
| t2 | None | All play; arm gestures as stand-ins | All work | Passed |
| t3 | None | All play; arm gestures as stand-ins | All work; the mouth (found by colour) opens beside the hands | Passed |
| t4 | Right (should be none) | Hands on hips fine; the wave still looks wrong | All work | Passed |
| t5 | None | All play; arm gestures as stand-ins | All work | Passed |
| f1 | Both (should be none) | The wave still lifts a sleeve with no hand | All work | Passed |
| f2 | Both | All play, including the new shrug | All work | Passed |
| f3 | None | All play; arm gestures as stand-ins | All work | Passed |
| f4 | None (head and shoulders) | All play; arm gestures as stand-ins | Blink, moods and head work; the mouth opening is faint (face half turned and in shadow) | Passed |
| f5 | None | All play; arm gestures as stand-ins | All work | Passed |

On every character the stage played all 37 clips (or their stand-ins) with
no errors. In the conversation check, every character played the five moods
in order, the asked-for wave and nod (or stand-ins), looked up as the person
started speaking, nodded in their pauses, and made gestures of its own from
its mood. Gestures chosen from the words came on 9 of the 11, and an idle
action in the twelve seconds alone (looking around, a glance, humming and
swaying) on 9 of the 11; both are left to chance and a budget, so a short run
does not always have one.

## Still to do

1. **Hands in pockets (f1) and an arm drawn bent with the hand on the hip
   (t4)** still pass the automatic check. Neither colour, shape nor the
   MediaPipe body-pose model (which found arms on 9 of the 11 pictures)
   told them apart from good arms reliably. Until then Character Studio's
   review shows the wave before the character is sent, and **Keep this arm
   still** fixes it in one click. The bent arm also needs the elbow cut
   made along the arm, not straight across, so the hand stays with the
   forearm.
2. **The fill behind a moving arm** is a smooth colour fill, which shows as
   a soft smear where the arm was (Alice, f2). Completing the hidden body
   properly needs the drawing workflow (`23-drawing-workflow.md`).
3. **No eyebrows** on characters made from pictures: the brow flash plays as
   a nod, and the brows in moods do nothing (`24-motion.md`).
4. **The blush** painted by the rigger for "embarrassed" is a soft-edged
   rectangle on some faces.
5. **Faint mouths** where the face is half turned or shaded (f4).

## Repeating the test

```bash
python3 stage/tools/clip_sheets.py CHARACTER.char OUT_DIR
```

```bash
cd core && COMPANION_TEST_VOICE=VOICE_FOLDER python3 tests/stack_check.py ../stage/target/release/stage UNPACKED/visual/live2d/model.model3.json OUT_DIR
```
