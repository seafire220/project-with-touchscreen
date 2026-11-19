# VRM avatars: 3D characters beside the 2D ones

Status: 2026-11-19. Built and tested in software (unit tests, four real
avatars, the full conversation check). Not yet run on a Raspberry Pi.

## What it is

A buyer can add a **VRM avatar** (`.vrm`, the 3D humanoid format VRoid
Studio and most VTubing tools use) on the settings page, beside the 2D
characters made from pictures and imported Live2D-format models. It
talks, moves and feels exactly as those do: the same moods, gestures, idle
life, listening, lip sync, temperament and Animation tab. Only the drawing
differs.

The owner asked for an alternative to the 2D animation system: upload your
own VRM, have it matched to our default rig, and have it animated by our
prebuilt animations for speaking and moods, on a device with 1 to 2 GB of
memory. Two outside handoffs were read first:

- ChatGPT's brief (`VRM_ARM_animation_Gemini_handoff.pdf`) proposed a
  separate renderer with its own JSON IPC (Domovushka, or vrm-runtime with
  raylib), plugged in later.
- Gemini's notes (`28-gemini-vrm-handoff.md`) proposed a third backend
  inside the stage program instead, which is what was built here. Its code
  is not in the repository, so this was written from scratch. Its ideas
  that held up are used: memory profiles with texture caps, shrinking
  textures at import, and a first feelings map from the avatar's
  expressions.

## How it fits: one rig, three drawings

```
core (Python): conversation, voice, moods, gestures; checks and packs .vrm uploads
   |  the same JSON-lines socket, the same commands
stage (Rust): director, behaviour, motion library, speech
   |  the same controls (24-motion.md): head, body, breath, eyes, mouth shapes, brows, arms, elbows, shoulders
   +-- Inochi2D puppet      (characters made from pictures)
   +-- Live2D-format model  (Ayagami)
   +-- VRM avatar           (stage/src/vrm: humanoid bones and expressions, drawn in 3D)
```

The "default rig" is the stage's set of generic controls (D-045). A VRM
avatar offers the stage the same parameter names a Live2D-format model
does (`ParamAngleX`, `ParamEyeLOpen`, `ParamArmLA` and the rest), plus one
per expression (`Expr:happy`). So the mapping, the movement settings page,
Feelings and every clip in the motion library drive it with no change.
Underneath, `stage/src/vrm/rig.rs` turns the controls into bone turns.

**Normalised humanoid.** Every VRM is in a T-pose at rest, but its bones'
own axes differ from model to model. Poses are written once in the
normalised humanoid VRM 1.0 defines (the T-pose with every bone's axes
along the world's). A rotation given there turns the bone by that much in
world terms on top of its parent's, whatever the model's own axes. VRM 0.x
avatars, which face the other way, are turned round first.

| Control | VRM avatar |
|---|---|
| Head turn, nod, tilt | head (two thirds) and neck (one third) |
| Body turn, lean, sway | spine, chest and upper chest, shared |
| Breath | the chest lifts a little; the shoulders too |
| Shoulders | both shoulder bones up |
| Arm (A) | the upper arm out from the side (rest: hanging, 11 degrees out) |
| Elbow (B) | folding back (B < 0): hand to the hip; small B: forearm forward (a shrug's open hands); large B: forearm up beside the head, palm to the viewer, fingers open (a wave) |
| Eyes | the eye bones, within the avatar's own look-at ranges; or its look expressions |
| Blink | blinkLeft and blinkRight (else blink) |
| Mouth | the vowel shapes aa, ih, ou, ee, oh from the speech timing; aa for a plain opening |
| Smile, eye smile, brows, sad brows | a VRoid Studio face's own parts (`Fcl_MTH_Fun`, `Fcl_EYE_Joy_L/R`, `Fcl_BRW_*`); otherwise a little of the relaxed or happy expression |
| Blush | an expression or shape named for one (blush, cheek, shy, 照れ, 頬) |
| Moods (through Feelings) | the avatar's own happy, sad, angry and surprised, shown a little softer than full (a full "happy" closes many avatars' eyes for as long as the mood lasts) |

Fingers rest slightly curled, as a relaxed hand does. Expressions follow
VRM's override rules (an expression that hides blinking hides it), except
that the mouth is never silenced: speech always shows at half or more.

The same clips play on 2D and 3D characters, so their directions match: a
positive turn faces the viewer's right, a positive tilt leans the head's
top to the right, on both (checked side by side).

**Hair and clothes** swing with VRM's spring bones (`VRMC_springBone` and
VRM 0.x's `secondaryAnimation`), pushed out of the body's collider spheres
and capsules. They settle for a second before the first frame.
**Constraints** (`VRMC_node_constraint`: rotation, roll and aim) keep
twist bones and accessories with the bones they follow.

## Drawing (`stage/src/vrm/render.rs`)

OpenGL ES 3.0, the same context the 2D drawings use (with a depth buffer
added for 3D).

- **Skinning on the graphics chip.** Each skin's joint matrices are sent as
  a small texture every frame, so avatars with hundreds of bones (the
  samples have 132 to 357) work on chips that allow few uniforms.
- **Face shapes on the processor**, only for meshes whose shape weights
  changed, from sparse deltas (a face's targets each touch few points).
- **MToon's toon look**: lit and shade colours split at a soft line
  (shading shift and toony), a rim of light, emission, inverted-hull
  outlines (world or screen width), cut-out and see-through materials in
  their order. VRM 0.x MToon settings are converted to 1.0's.
- **Framing**: a VRM frames itself from its bones. `--shot upper` (head to
  mid-thigh, the default) shows the face large and the arms' gestures;
  `bust` and `full` are the others. The camera pulls back a little (at
  most a third) while a hand is raised out to the side, so a wave stays on
  the portrait screen.

## Memory

| Profile | For | Textures kept up to |
|---|---|---|
| L1 | 1 GB boards | 1024 pixels a side |
| L2 | 1.5 GB or more | 2048 |

The stage chooses by the board's memory (`--profile auto`); the import
does the same. Textures are scaled down **once, at import**, so the device
never decodes a huge picture again. The stage loads only the textures it
draws with, and drops the processor's copies of meshes and pictures once
the graphics chip has them.

Measured here (a desktop, software drawing at 720 x 1280; peak memory
includes the software renderer's own buffers, which a Pi's graphics chip
holds separately):

| Avatar | Format | Bones | Textures (L1) | Peak memory, L1 |
|---|---|---|---|---|
| Seed-san (VirtualCast) | VRM 1.0 | 132 | 33 MB | 167 MB |
| VRM1_Constraint_Twist_Sample (pixiv) | VRM 1.0 | 357 | 42 MB | 175 MB |
| Alicia Solid (Dwango) | VRM 0.x | 272 | 27 MB | 164 MB |
| AvatarSample_B (VRoid Project) | VRM 1.0, VroidStudio export | 339 | 65 MB | 215 MB |

All four are under the stage's 300 MB limit. Posing (bones, springs, face)
takes under 0.1 ms a frame; drawing is the cost. Frame rates on a Pi are
still to be measured (`15-hardware-test-plan.md`); compressed textures
(ETC2, which every OpenGL ES 3 chip reads) would cut texture memory by
four if needed.

## Import (`core/companion/vrm.py`, `package.from_vrm`)

Upload a `.vrm` on **Characters → Add a character**. The device:

1. checks it: a glTF binary with VRM information (1.0 or 0.x), the fifteen
   bones VRM requires, its data in the one file, at most 160 MB, and no
   API key in its text;
2. scales its textures down for the device (PNG stays PNG, JPEG stays
   JPEG) and re-packs the file;
3. reads its maker's terms (who may use it, commercial use, the licence
   address) into the package. The settings page shows them under the
   character, with a warning if only its maker may use it;
4. uses its own thumbnail as the preview, and makes a first feelings map
   (happy, sad, angry and surprised to the expressions of the same names;
   embarrassed and thinking to expressions whose names suggest them),
   which the owner can change in Feelings;
5. installs it as a character like any other, with the usual persona
   template to fill in.

The terms are shown, not enforced. As with Live2D-format models, the
person who imports an avatar is responsible for having the right to use it
(`28-user-guide.md`). User-uploaded avatars give us no right to
redistribute them.

## Tested

- `stage/src/vrm/tests.rs` (12 tests, on a stick-figure avatar built in the
  test, in both VRM versions):
  - reading both versions;
  - facing the viewer with the arms down;
  - turn and nod directions;
  - the wave and the hand on the hip;
  - blinking and mouth shapes;
  - an expression that blocks blinking;
  - the eyes' range;
  - hair that swings but keeps its length and stays out of the head;
  - refusing damaged files;
  - sparse and strided data.
- `core/tests/test_vrm.py` and the upload and display tests (on a made-up
  avatar):
  - packaging both versions;
  - shrinking textures while keeping the mesh data;
  - refusing missing bones, external data and keys;
  - licence notes;
  - expressions and feelings;
  - the device showing the VRM drawing;
  - uploading on the settings page.
- Four real avatars (above), played through all 19 gestures, 11 idle
  actions, 7 moods and the states with `stage/tools/clip_sheets.py`, which
  now takes `.vrm` files. All 37 clips play on all four with no stand-ins,
  because a VRM offers every control. Brows move only on VroidStudio faces;
  other avatars' brows stay still, since VRM has no standard brow
  expression. The sample models stay out of the repository.
- The full conversation check (`core/tests/stack_check.py`, real core and
  stage, the on-device voice) on two (VRoid 1.0 and Alicia 0.x): every
  mood in order, the asked-for wave and nod, looking up as the person
  starts speaking, nodding in their pauses, gestures with the words, idle
  actions alone.
- The stage builds for the Pi (aarch64).

## Not done yet

- **On a Pi**: frame rate, memory and loading time, per the test plan.
- **VRM Animation (`.vrma`) clips**: motions from other tools played on
  any avatar. The motion library covers speaking, moods and idle life.
- **Parts of MToon left out**: matcap, UV animation, normal maps and
  outline-width textures. The look is close without them, and they cost
  memory.
- **A device setting for the shot** (upper, bust, full). It is a stage
  option today.
- **Character Studio** taking a `.vrm` for its personality step before
  sending. Today a `.vrm` goes straight to the device's settings page.
