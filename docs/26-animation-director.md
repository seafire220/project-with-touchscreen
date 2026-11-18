# Animation: how it works now, and a richer design (the director)

Status: 2026-11-18. Part 1 describes the animation system as built
(`stage/src/behaviour.rs`, `motion.rs`, `mapping.rs`, `stage/motions/library.json`,
`core/companion/conversation.py`, `speech_text.py`). Part 2 is a proposed
design for a richer system, not built yet. `24-motion.md` covers the
generic skeleton and the fitting of characters to it, which both parts use.

## Part 1: how it works now

Two programs share the work. The **core** (Python) runs the conversation
and decides what the character feels and wants to do. The **stage** (Rust)
draws the character about 60 times a second and decides how it moves on
each frame. They talk over a local socket in short JSON commands such as
`{"emotion": "happy"}`, `{"gesture": "wave"}` and `{"mouth": 0.42}`.

### Every frame: layers added together

1. **Living layer** (`behaviour.rs`). The character breathes (a 3.6 s
   cycle). It blinks at natural, uneven gaps (a log-normal spread with a
   median of 3.4 s, often blinking during a long eye movement). Its eyes
   move by what it is doing: they look around when idle, at you when
   listening, up and to one side when thinking, and mostly at you when
   speaking, glancing away about a third of the time. Its resting posture
   drifts to a new pose every 2.5 to 6 s, and slow overlapping waves sway
   the head and body. Liveliness depends on the state: listening 0.55×,
   thinking 0.8×, idle 1×, speaking 1.25×. Listening adds a slight head
   tilt and smile. Everything passes through springs, so nothing jerks.
2. **Mood layer** (`motion.rs`, `library.json`). One of seven moods
   (neutral, happy, sad, angry, surprised, embarrassed, thinking) sets:
   - a resting face and posture (happy: a smile and raised brows);
   - how lively the living layer is (happy 1.3×, sad 0.5×);
   - how strong the beats with speech are (angry 1.5×, sad 0.6×);
   - how often it starts gestures of its own, and which ones (a weighted
     list).

   A change of mood blends in over about half a second.
3. **Gesture layer.** Eighteen keyframed clips (nod, firm nod, shake, tilt,
   bow, bounce, laugh, sigh, sway, look away, look down, lean in, lean
   back, start in surprise, think, hands on hips, wave, shrug) are added on
   top of everything else. Each starts and ends at zero, so it blends in
   and out. A new gesture cuts the old one short with a 0.25 s fade. A
   character is only offered the gestures it has the controls for.
4. **Expressions.** A Live2D-format model's own expression files are
   blended in for the mood, as chosen under *Feelings* on the settings
   page.
5. **Physics.** Hair and clothing swing after the head and body.
6. **Mapping.** The generic controls (head turn, nod, arms, elbows, smile
   and so on, each from -1 to 1) become the character's own parameters:
   automatically by their usual names, or as set under *Movement* on the
   settings page.

### While it talks

- **The mouth** follows the loudness of the voice. As the core plays each
  sentence's audio, it measures the loudness every 20 ms and sends it,
  timed to when the sound will be heard. The mouth opens in about 35 ms
  and closes in about 70 ms. This is openness only, with no separate
  shapes for "oo" or "ee".
- **Beats.** When the loudness jumps (a stressed syllable: a rise of 0.18
  over its recent level, at most one every 0.28 s), the head gives a small
  quick nod, the brows lift on strong ones, and an arm makes a small
  accent, left and right in turn. The mood scales all of this.
- **Feelings in step with the words.** The language model is told to put
  a feeling tag such as `[happy]` before a sentence. Each sentence's
  feeling is sent as its audio starts, so the face changes with the words.
  After the reply the feeling lingers for 6 s, then calms to neutral.

### How bigger animations are chosen

Three ways, plus a safety net:

1. **The language model asks.** It is told which gestures this character
   can make ("[wave] wave", "[hands_on_hips] put your hands on your hips")
   and to use them sparingly, where a person would. A tag plays as its
   sentence starts. Up to two asked-for gestures queue, so neither is cut
   short.
2. **A mood's entry gesture.** When a mood starts, happy bounces, surprised
   starts, embarrassed looks away and thinking looks up.
3. **The mood by itself.** When nothing is playing and at least 0.8 s has
   passed since the last gesture, the mood picks a gesture from its
   weighted list at random intervals (happy every 4 to 8 s, sad every 8 to
   15 s, half as often again when idle). While listening, it only nods and
   tilts, at 60% strength. The owner can turn this off.
4. **Stage directions the model invents** (`[smile]`, `*giggles*`) become
   the matching feeling or gesture instead of being read out.

### What it cannot do yet

- The mouth only opens and closes; it has no shapes for the sounds.
- The beats follow loudness, not meaning. The character does not shake
  its head at "no", nod at "yes", tilt at a question or count on a list.
- A gesture starts with its sentence, not on the word it belongs to, and
  plays the same way every time: no variations, no wind-up or hold, no
  left-right mirror.
- One gesture plays at a time. There is no idea of body parts being busy,
  so a nod cannot run while the arms wave on their own timing.
- Idle time is pleasant but generic. The character never stretches, hums,
  looks out of the window, or gets sleepy at night or bored after an hour.
- Listening is passive. The character does not nod at the rhythm of your
  speech or react when you start talking.
- Clips are written by hand in JSON, with no editor and no recorded
  movement.

## Part 2: a richer design, the director

The aim is a character that seems to pay attention: it moves with the
meaning and rhythm of what it says, reacts to you, and fills idle time the
way a person does, without repeating itself and without twitching. It must
still work on any character through the generic controls, and cost little
on the Raspberry Pi. Moving controls costs tens of numbers a frame, next to
nothing beside drawing.

### Body channels and layers

Every behaviour moves one or more **channels**: mouth, face (brows, eyes'
shape, cheeks), eyes (gaze), head, torso, left arm and right arm. Layers
from bottom to top:

1. **Base pose** for the mood (today's mood offsets).
2. **Living layer** (today's breathing, blinks, eye movements and drift).
3. **Idle actions**: longer clips for when nothing is being said (below).
4. **Speech layer**: mouth shapes, beats, and small meaning-based moves
   (below).
5. **Gestures**: the big clips, now with phases and variations.
6. **Reactions**: quick, high-priority responses such as a startle, or
   looking up when you start speaking.
7. **Face**: the mood's face, the model's own expressions, and brief
   micro-expressions.
8. **Physics**, as now.

A behaviour reserves the channels it uses while it plays. Lower layers fade
out on those channels and keep going on the rest: a wave holds the right
arm while the head still nods with the words. A higher-priority behaviour
can take a channel from a lower one, which then lets go through its own
retract phase rather than snapping back.

### The director: what plays, and when

The director is a small scheduler in the stage that runs every frame.

**What it listens to:**

- the state (idle, listening, thinking, speaking);
- each sentence as it starts: its text, feeling and strength, word
  timings, and any gestures asked for;
- the voice's loudness;
- whether you are speaking (with a microphone), and button presses;
- time since the last conversation, and the time of day;
- the character's temperament (below) and the owner's settings.

**What it keeps track of**, each a number that rises and falls slowly:

- **mood**: the feeling and its strength, lingering and fading as now;
- **energy**: raised by happy or excited replies, lower late at night;
- **attention**: how focused it is on you; high while you talk;
- **boredom**: grows through silence, and drops at once when you speak or
  press the button;
- **sleepiness**: follows the time of day and long idle spells.

**How it chooses.** Each candidate behaviour gets a score:

- how well it fits the mood and the state;
- how well it fits the moment (the start or end of a phrase, a question,
  a pause);
- freshness: anything played recently scores lower, and each clip has its
  own wait before it can play again;
- whether its channels are free, or can be taken;
- energy, and the temperament's expressiveness.

The director plays the best candidate if its score clears a threshold,
choosing among close scores at random so the character stays lively
without being erratic. A **budget** caps big gestures per sentence and per
minute, so it never flails.

Explicit requests still win. A gesture tag from the language model, or a
direct command from the settings page, plays unless the character
physically cannot do it.

### The speech planner: moving with the meaning

The core already has each sentence's text, and its phonemes from espeak-ng
for the voice. A planner turns these into a short timed score for the
stage, using rules from studies of how people gesture as they talk, with
no extra call to the language model:

- a stressed or emphasised word gets a beat, with brows lifted on strong
  ones;
- yes or agreement gets a nod; no or negation a small head shake;
- a question gets a slight head tilt and raised brows at its end;
- "maybe", "I think" or "I'm not sure" get a tilt or a small shrug;
- "you" leans slightly towards you; "I" or "me" brings a hand to the
  chest (if the arms move);
- a list ("first", "second", "and then") gets a beat on each item;
- laughter ("haha") gets a laugh; a greeting or goodbye gets a wave;
- the end of a phrase gets a small settling nod, and the long pause
  between sentences a blink.

Each rule fires with a chance scaled by energy and expressiveness, within
the budget. The language model's feeling tags and asked-for gestures come
first, and the planner only fills around them.

**Timing.** Gestures get phases: prepare, stroke, hold and retract. The
director starts the prepare phase early, so the stroke lands on its word
(people's gestures land on or just before the stressed syllable). The
voice engine (sherpa-onnx) hands back audio only, as far as I have seen,
so word times are estimated. Each clause's phonemes are spread over its
audio length, then pinned to the loudness: vowels fall where the sound is
loud, pauses where it is quiet. Within a tenth of a second is close enough
for gestures.

### Mouth shapes (visemes)

The same timed phonemes give mouth shapes:

- open "a";
- wide "i" and "e";
- rounded "u" and "o";
- closed lips for "m", "b" and "p";
- lip-on-teeth for "f" and "v".

Most characters have a mouth-openness and a mouth-shape parameter, and
the shapes map onto those two; models with one parameter per vowel use
those instead. Loudness still sets how far the mouth opens, so the mouth
always matches what is heard. Where the phonemes cannot be used (a cloud
voice), the mouth falls back to today's loudness only.

### Idle life

- **Idle actions**, chosen by the director as boredom and sleepiness rise:
  stretch, look out of the window (off-screen), look around the room, hum
  and sway, tidy its hair, a slow yawn, rub its eyes, and a glance at you
  as if to check you are still there.
- **Times of day**: livelier in the morning, calmer in the evening, and
  sleepy at night (slower blinks, yawns). After a long quiet spell at night
  it can doze, eyes closed with slow breathing, and it wakes with a small
  start and a smile when spoken to or when the button is pressed.
- **Coming back**: a greeting gesture and a brighter mood when someone
  returns after a long gap (on the first words or button press).

### Listening

With a microphone, while you speak:

- it looks at you and leans in a little;
- in your short pauses it gives small nods now and then (a listener's
  "mm-hm", without sound);
- it matches your energy a little: livelier movement when you speak
  excitedly.

When you start speaking, it looks up and its attention rises at once.
Without a microphone (push to talk), it holds the same attentive pose while
recording.

### Clips, version 2

Each clip gets:

- curves with easing, not only straight segments;
- named phase marks (prepare, stroke, hold, retract);
- the channels it uses;
- several takes per gesture, chosen at random so a wave is never quite
  the same twice;
- a mirror flag (the same wave with the other arm);
- a strength scale;
- needs with alternatives (as now), and **substitutes**: a character
  without arms waves with a head tilt, a smile and raised brows instead.

Three ways to make clips:

- **By hand**, in a timeline page (in Character Studio, or on the device's
  settings page) that plays each change live on the device.
- **Recorded from a person.** A webcam or phone video goes through
  MediaPipe's face and body landmarks (free and local). The landmarks
  become our controls (head angles, gaze, brows, mouth, shoulder and elbow
  angles), are smoothed with the 1€ filter already in the stage, and are
  cut into clips. This is the quickest way to natural idle actions and
  gestures.
- **Generated**: noise-based variation for the living layer, as now.

### Per character

- The movement settings (built) choose which parameter each control
  drives.
- A **temperament** for each character sets the defaults for energy,
  expressiveness, how often it gestures, and which idle actions suit it:
  a shy character fidgets and looks away; a confident one stands with
  hands on hips.
  - The persona form gets two sliders (lively to calm, reserved to
    expressive).
  - A character card's personality text can suggest starting values.
- Any gesture or idle action can be switched off for a character.

### What goes where

- **Core:** the speech planner (it has the text and phonemes). At the
  start of each sentence it sends one **performance** message: the
  sentence's length, the timed events (gesture strokes, nods, brow
  flashes, blinks) and the mouth shapes. It also sends events for when you
  start and stop speaking.
- **Stage:** the director, channels, layers, clips, drives and reactions,
  all frame-timed. It plays performances, and fills everything around them
  itself.
- **Library:** `library.json` grows into version 2 (phases, takes,
  channels, substitutes), with a converter from version 1.
- **Settings page:** temperament, a gesture and idle-action list with
  on/off switches, and a debug view (below).

Example performance message:

```json
{"perform": {"length": 2.4, "feeling": "happy", "strength": 0.8,
  "events": [{"at": 0.30, "gesture": "wave", "stroke": true},
             {"at": 1.10, "brows": 0.6},
             {"at": 2.20, "nod": 0.4}],
  "mouth": [[0.00, "closed"], [0.08, "a"], [0.21, "i"], [0.30, "m"]]}}
```

### Build order

| Step | What | Done when |
|---|---|---|
| 1 | Mouth shapes from the phonemes the voice already makes | Side-by-side clips show the mouth rounding and closing on the right sounds; no lag against the audio |
| 2 | The speech planner, and gestures with phases that land on their word | Strokes land within 0.1 s of their word; nods on yes, shakes on no, tilts on questions in a scripted test reply |
| 3 | Channels, the scheduler and the budget | A nod plays through a wave; no channel ever snaps; gestures per minute stay in a set band over a ten-minute conversation |
| 4 | Drives (energy, boredom, sleepiness), idle actions and times of day | An hour of idling in fast-forward shows varied actions, no repeat within the cooldown, sleepy at night |
| 5 | Listening and reactions | With a microphone, nods in the speaker's pauses; it looks up when speech starts |
| 6 | Clips version 2, recorded clips (MediaPipe), the timeline page and the debug view | A recorded stretch and a recorded laugh play on three test characters; the debug view shows each layer live |
| 7 | Temperament per character | Shy and confident test personas visibly move differently with the same reply |

**The debug view.** A page that shows, live, what each layer and channel
is doing, which behaviour the director picked and why (its score), and the
drives. It makes tuning quick, and it answers "why did it do that?".

**How it is judged:** side-by-side clips of the same reply, old and new,
judged by eye. Measured as well: repetition (the same gesture within its
wait), gesture rate, how close strokes land to their words, and frame time
on the Pi.

### Risks and open questions

- **Over-animation is worse than too little.** The budget, freshness
  scores and temperament are there to hold it back. Each step should be
  tuned by watching, not just by passing tests.
- **Timing is estimated.** The estimates should be checked against the
  audio. If a later voice engine reports word timings, use them.
- **Imported models vary.** Gestures on their arms mean whatever their own
  parameters do; the movement settings and substitutes cover most of that.
- **Recording clips from people** needs care with consent and rights:
  record only the owner, or people who have agreed.
