# Motion: a generic skeleton every character is fitted to

Status: 2026-11-18. Design (roadmap item 4, decision D-045). First steps
built: the smoothing primitives, the wider controls with rest-aware mapping,
and the new idle and speech motion (see "Built so far" at the end). Written after the owner looked at a friend's VTubing app,
in which a full-body character moves smoothly with an outstretched arm, and
suggested that the trick may be a generic animation skeleton that every
uploaded model is fitted to.

## What such apps do

The friend's app was seen only in a screenshot: a 3D character in a studio
scene, with panels for tracking (camera and microphone), avatar, expressions
("rules and hotkeys"), tuning ("smoothing and curves"), scenes, recording,
profiles, and a debug view (frame rate, GPU, timings). Its inner workings are
not known; the published VTubing tools it resembles work as follows.

**3D apps use a standard humanoid skeleton.** A VRM model must name its
bones from a fixed list: hips, spine, head, upper and lower arms, hands,
upper and lower legs and feet are required; chest, upper chest, neck,
shoulders, eyes, jaw, toes and finger joints are optional, each with a fixed
parent. Because every model has the same named bones, one tracker, one
animation library and one set of expressions drive any model, and secondary
motion (hair, clothes) comes from spring bones the model carries.

**2D apps use the standard parameter list as the skeleton.** Live2D
publishes standard parameter names and ranges: head angles (`ParamAngleX/Y/Z`,
-30 to 30), eyes (`ParamEyeLOpen`, `ParamEyeLSmile`, `ParamEyeBallX/Y`),
brows (`ParamBrowLY`, `...LX`, `...LAngle`, `...LForm`, and the right-hand
ones), mouth (`ParamMouthForm`, `ParamMouthOpenY`), `ParamCheek`, body
(`ParamBodyAngleX/Y/Z`, -10 to 10), `ParamBreath`, arms (`ParamArmLA`,
`ParamArmLB`, `ParamArmRA`, `ParamArmRB`, -30 to 30, "spread when +"), hands
(`ParamHandL/R`, -10 to 10), `ParamShoulderY` (shrug), hair sway, and a few
more. VTube Studio maps any input (face tracking, mouse, its own animations)
onto any model parameter by converting between an input range and an
output range, with smoothing set per parameter ("more smoothing is less
shaky but lags"). It combines sources in a fixed priority order, lowest
first: the model's default, the idle animation, face tracking, one-off
animations while they play, expressions while active, then physics; control
passes down the list when a source stops, and changes between sources fade
rather than snap. Expressions can overwrite a value, add to it or multiply
it.

**Trackers are turned into skeleton values by solvers.** Kalidokit (MIT,
now deprecated in favour of MediaPipe's own solutions) took MediaPipe's
face, hand and body landmarks and computed head and hand rotations, eye
openness, mouth shapes and spine and arm angles, for VRM and Live2D models
alike. Tracked motion is noisy, so it is filtered: the usual filter is the
1€ filter (Casiez, Roussel and Vogel, CHI 2012), a low-pass filter whose
cut-off rises with speed, so slow motion is smoothed and fast motion is not
delayed; it has two settings, a minimum cut-off (less jitter when lower) and
a speed factor (less lag when higher).

**Without tracking, motion has to be generated.** Character-animation
systems for talking agents stack independent controllers: idle pose, head
(nods, shakes, tilts, listening responses), blinks, eye saccades; research
models drive head and eye motion from speech and time involuntary blinks
from log-normal intervals. Hand-made state machines become repetitive
quickly, which is why recorded and statistically varied motion matters.

## What the stage does today

- Ten controls (`stage/src/mapping.rs`): mouth open, blink left/right, head
  yaw/pitch/roll, body yaw/pitch/roll, breath. Each is matched to a
  parameter by name (Inochi2D or Live2D style) and scaled to its range.
- Motion (`stage/src/behaviour.rs`): sums of fixed sine waves for head and
  body sway, scaled by the conversation state; a blink timer (2.2-6 s gaps);
  the mouth follows loudness; a small nod with loudness while speaking;
  first-order smoothing towards state-dependent targets.
- Direct settings from the core (`overrides.rs`) with easing, used for
  expressions and previews.
- Physics from the character file (Inox2D's or Ayagami's).
- No arms, gaze, brows, mouth shape, cheeks or shoulders; no motion clips;
  imported models' own motions and expressions are carried but not played.

Compared with the apps above, the controls are the right idea but too few,
the motion is too regular, and smoothing is the simplest kind.

## Design

### 1. The skeleton: Live2D's standard parameters, with calibration

Use the standard parameter list as our generic skeleton, as 2D apps do, and
extend the stage's controls to cover it: gaze (`ParamEyeBallX/Y`), brows,
mouth shape, eye smile, cheek, shoulders, arms (A and B, left and right),
hands, and hair sway as physics inputs. Each control has a fixed range in
the stage (-1 to 1 or 0 to 1), as today.

Every character gets a **calibration** saying, per control, which parameter
it drives, the parameter values at the control's ends and middle, and
whether the direction is reversed:

- Our own characters: the studio writes it (`visual/controls.json` in the
  package), since it made the rig and knows each parameter's meaning, range
  and the poses its drawings support (for example, how far an arm can swing
  before a gap shows).
- Imported Live2D-format models: guessed from standard names, the
  `EyeBlink` and `LipSync` groups in the model's index and the display names
  in its `.cdi3.json`; then shown on the settings page as sliders with a
  live preview, so the buyer can correct ranges and directions once.
- A model without a control (no arms, no brows) simply skips it; gestures
  that need it are not offered for that character.

### 2. Layers, as VTube Studio orders them

Each frame the stage combines sources per control, lowest first: the
character's neutral pose; **idle motion**; **speech-driven motion**;
**gestures** while they play; **expressions** while active (overwrite, add
or multiply); then physics in the character file. Changing source fades
over a short time instead of jumping.

### 3. Motion written once, in skeleton values

Idle loops, listening and thinking poses, and gestures are stored as curves
over controls (not over a model's parameters), in a small JSON format
modelled on Live2D's `.motion3.json` (keyframes with Bézier handles), so any
character plays them through its calibration. Three sources:

1. **Hand-made**: a starter set of 15-20 short clips: nod, double nod,
   shake, curious tilt, look away while thinking, lean in, small shrug,
   laugh, sigh, emphatic beat, and, for characters with drawn arm poses,
   wave, point, hand to chin.
2. **Recorded from people**: a studio tool that runs MediaPipe (Apache-2.0)
   on a webcam or video of someone talking or listening, solves head, gaze,
   brows, mouth and shoulder and arm angles (as Kalidokit did), filters
   them with the 1€ filter and saves clips. A few minutes of the owner
   talking would give idle and talking motion with real rhythm, which sine
   waves cannot.
3. **The model's own motions**: imported models often bring idle motions;
   they can play as the idle layer.

Idle motion picks clips with random order and timing, varies speed and size
a little, and crossfades between them, so it never loops visibly.

### 4. Motion from speech and from the conversation

- The stage already gets the voice's loudness about 50 times a second.
  Peaks in it (stressed syllables) trigger small nods and brow lifts, and
  the end of a sentence a settling motion; this replaces today's nod that
  simply follows loudness.
- The conversation's emotion tags (`[happy]` and the like, already used by
  the core) choose expressions and gestures; the language model can also
  ask for a gesture by name, as it asks for timers today.
- Listening: small gaze shifts towards the user and back, occasional nods;
  thinking: gaze up and away, a slower blink rate.
- Blinks: log-normal gaps, more after a gaze shift, fewer while speaking.

### 5. Smoothing and curves

Replace first-order smoothing with a **critically damped spring** for every
control (smooth start and stop, no overshoot unless asked for; speed limits
per control), and use the **1€ filter** for noisy inputs (loudness,
recorded motion). Settings per control live in one table, like a "tuning"
page: spring time, speed limit, filter cut-off and speed factor.

### 6. Arms and hands

Big arm gestures need drawn arm poses, which is the drawing workflow
(roadmap items 3 and 6): a deformed arm can only swing so far before the
picture shows a gap. The calibration records each character's safe range.
The gesture clips use arm controls only as far as that range allows, and
the drawn alternate poses are switched in (by opacity, as Live2D artists
do) for larger ones.

### 7. A 3D option, later

A VRM avatar would get all of this from its humanoid skeleton directly, and
the same controls map onto it (head and arm bones, expressions, look-at).
Not proposed now: our characters start from one 2D picture, and making a 3D
model from it is a different, much harder pipeline (`23-drawing-workflow.md`
covers the image-to-3D candidates).

## Building it

| Step | Files | Check |
|---|---|---|
| Wider controls and calibration | `stage/src/mapping.rs`, `behaviour.rs`; studio writes `visual/controls.json` | Unit tests; a gaze/brow/arm sweep on the test characters |
| Springs and the 1€ filter | new `stage/src/smooth.rs` | Step responses: no overshoot, settle time as set |
| Layers and fades | new `stage/src/motion.rs` | Switching sources never jumps (largest change per frame) |
| Clip format and player | `motion.rs`, `stage/motions/*.json` | Clips play the same on two characters with different ranges |
| Speech-driven beats | `behaviour.rs` | Nods land on loudness peaks in a recorded sentence |
| Recording tool | `studio/record_motion.py` (MediaPipe) | A recorded clip plays on a character and looks like the person |
| Calibration page for imported models | `core/companion/console` | A buyer can fix a reversed arm in under a minute |
| Debug view | settings page, from the stage heartbeat (fps, `update_ms`, `draw_ms`) | Shown live |

Judged by eye in side-by-side clips (old and new motion, same character),
since the existing checks have passed motion that looked wrong.

## Built so far (2026-11-18)

- `stage/src/smooth.rs`: the critically damped spring and the 1€ filter,
  with tests (no overshoot, steady at any frame time, speed limits; jitter
  removed without lag on fast moves).
- `stage/src/mapping.rs`: eight more controls on Live2D's standard names
  (gaze X and Y, left and right brow, mouth shape, left and right arm,
  shoulders); controls that run from -1 to 1 now rest at each parameter's
  default, so a model whose neutral pose is not the middle of its range
  rests correctly; a mapping file can set `"rest"`.
- `stage/src/behaviour.rs`: the eyes shift by state (look around when idle,
  at the user when listening, up and away when thinking, mostly at the user
  with glances away when speaking) and the head follows part of the way;
  posture drifts to a new resting pose every 2.5-6 s, so idle motion never
  repeats; loudness onsets while speaking bring a quick nod, a brow lift on
  strong ones and a small accent of one arm; a slight smile when idle or
  listening; shoulders rise with breath; blink gaps follow a log-normal
  spread, with a blink often on a long gaze shift; every movement goes
  through a spring. Holding still (`--still`) still stops all of it.
- Moods and gestures (2026-11-18, after the owner asked for prebuilt
  animations that follow the character's emotions): `stage/motions/library.json`
  holds seven moods (one per emotion the language model can tag) and
  eighteen gestures (nod, firm nod, shake, tilt, bow, bounce, laugh, sigh,
  sway, look away, look down, lean in, lean back, start in surprise, think,
  hands on hips, wave, shrug), written in control units. `stage/src/motion.rs`
  plays them: a mood blends in its face and posture and changes how lively
  the idle motion is and how strong the beats with speech are, and may start
  with an entry gesture (happy bounces, thinking looks up); gestures are
  added on top of the current motion and fade out when cut short; the mood
  starts its own gestures now and then (while listening, only small nods and
  tilts); a gesture is offered only to characters with every control it
  needs, and the stage lists them when it starts.
- The core sends `emotion` and `gesture` commands in step with each
  sentence, tells the language model only the gestures its character has,
  and has two settings: whether the character may choose gestures, and
  whether its mood starts gestures by itself. A splitter fix makes each tag
  apply to the sentence it comes before however the reply streams in (it
  used to give a sentence the last emotion in the buffer).
- Checked end to end (`core/tests/stack_check.py`): the real core against
  the real stage, with a reply tagged happy, thinking, surprised, happy and
  embarrassed, a wave and a nod: every mood played in order, both asked-for
  gestures played out, entry gestures played where nothing asked for was
  playing.
- Arms (2026-11-18): two more controls, the elbows (`arm_left_b`,
  `arm_right_b`, on `ParamArmLB` and `ParamArmRB`), so a gesture can raise a
  forearm or bend it back to the hip. On our own characters the studio
  (`studio/refine.py`) hangs each arm from a node at the shoulder that truly
  rotates, turns the forearm about the elbow inside it (stored every 10
  degrees, so the Live2D-format copy stays within 2 pixels), rounds both
  pieces off at the elbow so the joint stays closed, and solves each arm's
  own poses from its lengths and how it is drawn: a waving arm at A 0.5 and
  B 0.85, a hand on the hip at A 0.6 and B -0.9 (the hand placed on the
  body's outline a fifth of an arm above where it hangs, the elbow out).
  The gesture library uses those values: the wave raises the forearm and
  waves it at the elbow, hands on hips bends both arms (or the one that
  moves: a need can name alternatives, `"arm_left_b|arm_right_b"`), and the
  shrug opens the forearms. `studio/partsplit.py` paints the body in behind
  each arm first, where it carries on behind it (between visible body on
  both sides, and up to the body's outline drawn straight across where the
  arm hides it), and keeps an arm with the body when the picture does not
  show it hanging whole from the shoulder (broken up by hair in front, half
  hidden by long hair lying along it, very thin, raised, folded, or too
  short); where a strand of hair crosses an arm, the arm is completed under
  it so it moves whole. Measured on the owner's test
  pictures: the area left empty when the arms swing fell from 5,540 to 436
  square pixels on Alice, and the tear at the elbow when shoulder and elbow
  move together from 2,584 to 92; on the others the remaining empty area is
  the arm's own place where background shows through, as it should.
  Gestures checked by playing them through the stage's motion system
  (wave, hands on hips, shrug) on four characters.
- Movement settings (2026-11-18), the calibration page for any character:
  on the settings page, under the character, each kind of movement (head
  turn, nod, tilt, body turn, lean, sway, eyes, arms, elbows, shoulders,
  smile, and the face's details under "More") shows the parameter the
  stage chose for it; the owner can pick another of the character's
  parameters, switch it off, or reverse it, and *Test* moves that
  parameter end to end on the device's screen; the gestures can be tried
  there too. Saved per character (on the device only), written to
  `/var/lib/companion/current-map.json` for the stage (`--map`), which
  starts again with them. Settings that do not fit the character (a
  parameter it lacks) are reported and the automatic choice is used, so
  they can never stop it showing. Mapping a model's own expressions to our
  moods is the "Feelings" section beside it.
- Talking (2026-11-18, `26-animation-director.md` steps 1 and 2): the
  mouth takes a shape for each syllable's vowel (open "a" and "o",
  narrower "i" and "u", wider "i" and "e", rounder "o" and "u" on the
  mouth-shape control), and movements go with the words: nods on yes and
  thanks, a small shake on no, a tilt on questions, a wave on hello and
  goodbye, a laugh on "haha", raised brows on strong words, a look down on
  sorry. The core (`performance.py`) plans them from the words and marks
  in the audio where each syllable is heard; the stage (`speech.rs`)
  shapes the mouth and starts each movement as its mark arrives. When the
  language model leaves out its feeling tags, the feeling is guessed from
  the words.
- Not built yet: motion clips recorded from people, and the debug view.
  The fill behind the arms uses today's smooth colour fill; See-through's
  completed layers would draw it properly.

Our own characters have no gaze or brow parameters yet (the rigger does not
make them), so on them these controls do nothing until the studio adds them;
imported Live2D-format models usually have them.

## Sources

- VRM 1.0 humanoid bones: https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/humanoid.md
- VRM overview: https://vrm.dev/vrm1/
- Live2D standard parameter list: https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/
- VTube Studio, model settings (input and output ranges, smoothing): https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings
- VTube Studio, order of animations, tracking, expressions and physics: https://github.com/DenchiSoft/VTubeStudio/wiki/Interaction-between-Animations,-Tracking,-Physics,-etc.
- Kalidokit: https://github.com/yeemachine/kalidokit (README via https://cdn.jsdelivr.net/gh/yeemachine/kalidokit@main/README.md)
- 1€ filter: https://cristal.univ-lille.fr/~casiez/1euro
- Controllers for talking characters (ICT): https://ict.usc.edu/pubs/Building%20a%20Character%20Animation%20System.pdf
- Speech-driven head and eye motion, log-normal blink timing: https://graphics.cs.uh.edu/wp-content/uploads/papers/2012/2012-TVCG-headEyeMotionGenerator-preprint.pdf
