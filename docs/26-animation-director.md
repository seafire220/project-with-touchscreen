# Animation: how it works now, and a richer design (the director)

Status: 2026-11-18. Part 1 describes the animation system as built
(`stage/src/behaviour.rs`, `motion.rs`, `speech.rs`, `mapping.rs`,
`stage/motions/library.json`, `core/companion/conversation.py`,
`performance.py`, `speech_text.py`). Part 2 is a design for a richer
system. Its first two steps, mouth shapes and movements that go with the
words, are built, and Part 1 describes them. `24-motion.md` covers the
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
3. **Gesture layer.** Nineteen keyframed clips (nod, firm nod, shake, tilt,
   bow, bounce, laugh, sigh, sway, look away, look down, lean in, lean
   back, start in surprise, think, hands on hips, wave, raised brows,
   shrug) are added on
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

- **How far the mouth opens** follows the loudness of the voice. As the
  core plays each sentence's audio, it measures the loudness every 20 ms
  and sends it, timed to when the sound will be heard. The mouth opens in
  about 35 ms and closes in about 70 ms.
- **The mouth's shape** follows the syllables. Before a sentence plays, the
  core (`performance.py`) splits it into syllables and finds each one's
  vowel from the phonemes espeak-ng gives for each word, or from the
  spelling if espeak-ng is missing. Each vowel maps to one of five shapes:
  open "a", half-open "e", wide "i", round "o" and small round "u". It then
  works out where each syllable is heard in the audio by counting
  phonemes. In a voice's speech each phoneme lasts about as long as any
  other (35 to 45 ms in the device's voice), so a syllable's place among
  the sentence's phonemes is close to its place in time. Clause ends with
  a pause after them anchor the count:
  - When the voice makes the whole sentence first (the device's own
    voice), the syllables are spread over the time the voice sounds. Each
    clause that has a pause before it starts where the sound starts again.
    A clause after a full stop nearly always has one; after a comma often
    not.
  - When the audio streams in (cloud voices), a clock counts phonemes at a
    usual pace while the voice sounds. At each pause it decides which
    clause starts there (a long pause most likely after a full stop),
    restarts the count there and corrects the pace. At a full stop it
    waits for the pause, so it never runs on into the next sentence.

  A mark is sent as each syllable is heard. The stage (`speech.rs`) scales
  the opening by the vowel: an "i" opens to 60% of an "a", a "u" to 55%.
  It also widens the mouth ("i", "e") or rounds it ("o", "u") on the
  mouth-shape control, in about 60 ms. Loudness still decides when the
  mouth opens and shuts, so it never moves without sound.
- **Beats.** When the loudness jumps (a stressed syllable: a rise of 0.18
  over its recent level, at most one every 0.28 s), the head gives a small
  quick nod, the brows lift on strong ones, and an arm makes a small
  accent, left and right in turn. The mood scales all of this.
- **Movements with the words.** The same plan picks a few movements from
  the sentence's words, with no extra call to the language model:

  | Words | Movement | Chance |
  |---|---|---|
  | A sentence starting "yes", "sure", "exactly"; "no problem" | nod | 90% |
  | "no", "not", "never", "don't" (not in a question, not "no problem") | small head shake | 75% |
  | A question | tilt on its last word | 65% |
  | "maybe", "I think", "not sure" | tilt, or sometimes a shrug | 60% |
  | "hello", "hi" at the start of the first sentence | wave | 85% |
  | "bye", "good night", "see you" | wave | 80% |
  | "haha", "hehe", "lol" | laugh | 90% |
  | "thanks", "thank you" | nod | 70% |
  | "sorry", "unfortunately" | look down | 60% |
  | "really", "amazing", "love", a word in capitals | brows raised | 55% |
  | "first", "next", "finally" (two or more) | a small nod on each | 80% |
  | A sentence ending "!" | small nod at its end | 40% |

  Each movement starts one syllable before its word, two for a wave,
  shrug or bow, so that it lands on the word. Each sentence gets at most
  two, or one if the language model asked for a gesture itself. At most
  one may be big (a wave, laugh, shrug, bow, lean in, or hands on hips).
  After a big one, the next two sentences get none, except a laugh. The
  chances mean the same sentence is not always performed the same way.
  Only gestures the character has are planned. A planned movement never
  cuts short one the language model asked for.
- **Feelings in step with the words.** The language model is told to put
  a feeling tag such as `[happy]` before a sentence. Each sentence's
  feeling is sent as its audio starts, so the face changes with the words.
  After the reply the feeling lingers for 6 s, then calms to neutral.

### When the tags are missing or wrong

The character must still look alive when the language model forgets its
tags, writes them its own way, or something fails:

- **Talking never depends on tags.** The mouth opens with the voice's
  loudness and the beats come from its stresses whatever else happens.
  The planned movements need no tags. The mood also keeps adding its own
  gestures now and then, unless the owner has turned that off.
- **No feeling tag in a reply.** Each sentence's feeling is guessed from
  its words: "sorry" or "miss you" give sad, "wow" or "no way" surprised,
  "love" or "awesome" happy, "hmm" or "maybe" thinking. A word counts 1, a
  phrase 1.5, and a "!" adds a little. Only a clear winner counts; a plain
  or mixed sentence keeps the feeling it had. Once the model tags anything
  in a reply, nothing more is guessed, so a tagged reply is never
  second-guessed.
- **Tags written other ways** still count:
  - labels and capitals: `[Emotion: Happy!]`, `[mood: thinking]`;
  - parentheses and angle brackets: `(smiles)`, `<sad>`;
  - stage directions: `*giggles softly*`, `*waves*`, `*puts hands on hips*`;
  - other words for the feelings: `[joyful]`, `[worried]`, `*nervously*`,
    `<Angrily>`;
  - an emoji, when there is no tag: 😊 happy, 😢 sad, 🤔 thinking. Emoji are
    never read out.

  Other words in square or angle brackets are dropped rather than read
  out (`[pause]`, `[citation needed]`, `[1]`).
- **Words that only look like tags are still said.** Emphasis keeps its
  words ("that was *really* good"). A feeling word stressed inside a
  sentence is said, not acted ("I'm *glad* you came", "let's *pause*
  here"). A remark in parentheses that is not a direction is said
  ("I missed you (a lot, honestly)").
- **When the plan fails**, for example on an unexpected error or a missing
  espeak-ng, the sentence is spoken with the loudness-only mouth and the
  beats. The error is written to the log and the reply carries on.
- **When the syllables cannot be found** (a very even voice, a whisper),
  a mark is placed anyway every 0.3 s of steady sound, so the shapes and
  movements keep going.
- **With an older stage or core**, the new messages are ignored and the
  character talks exactly as before.

### How bigger animations are chosen

Four ways, plus a safety net:

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
4. **The words themselves.** The plan described above adds nods, shakes,
   tilts, waves, laughs and raised brows where the words call for them.
5. **Stage directions the model invents** (`[smile]`, `*giggles*`) become
   the matching feeling or gesture instead of being read out.

### What it cannot do yet

- The mouth has five vowel shapes but no closed lips for "m", "b" and "p"
  or lip-on-teeth for "f" and "v". The mouth only closes when the sound
  drops. On characters made from a picture, the mouth-shape control lifts
  or lowers the corners, so "o" and "u" show mainly as a smaller opening,
  not a rounded one. Imported Live2D-format models with a proper mouth
  shape do better.
- Syllable times are estimated, not known. Measured against the exact
  timings of the device's voice (`core/tools/measure_syllable_marks.py`,
  12 sentences, 6 speakers, 3 speeds, 3,204 syllables):

  | Sound | Vowels within 0.1 s | Median error | 90% within |
  |---|---|---|---|
  | Made whole (the device's voice) | 79% (87% at its usual speaker and speed) | 0.05 s | 0.15 s |
  | Streamed (cloud voices) | 39% | 0.15 s | 0.58 s |
  | Streamed, before this change (loudness peaks) | 27% | 0.21 s | 0.80 s |

  Streamed marks drift within a long clause, because the voice's pace is
  only known at its pauses. Learning each voice's pace does not help: one
  voice varies 10 to 20% from sentence to sentence. Holding back each
  clause's sound until its pause, for sentences after the first, would
  make them as good as whole ones; that is not built.
- The planner knows words, not intent. It cannot tell a teasing "no" from
  a firm one, and it does not yet lean in on "you", point to itself on "I",
  or settle at the end of a phrase.
- A gesture plays the same way every time: no variations, no wind-up or
  hold, no left-right mirror.
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

*Built (2026-11-18), more simply:* the core marks each syllable in the
audio by counting phonemes between pauses (Part 1 has the details and
the measured accuracy), and the speaker sends each mark as it is heard.
Pinning to loudness peaks was tried and measured: it made things worse,
because in running speech the loudness does not rise once per syllable.
Movements start a syllable or two before their word. There are no phases
yet; they come with clips version 2. The rules for "you", "I" and phrase
ends are not built.

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

*Built (2026-11-18):* the five vowel shapes, on the openness and
mouth-shape parameters. They work with cloud voices too: the phonemes come
from the text, and the syllables are found in the streamed sound. Still to
do: closed lips, lip-on-teeth, and models with one parameter per vowel.

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

Example performance message, as designed:

```json
{"perform": {"length": 2.4, "feeling": "happy", "strength": 0.8,
  "events": [{"at": 0.30, "gesture": "wave", "stroke": true},
             {"at": 1.10, "brows": 0.6},
             {"at": 2.20, "nod": 0.4}],
  "mouth": [[0.00, "closed"], [0.08, "a"], [0.21, "i"], [0.30, "m"]]}}
```

As built, times are counted in syllables, not seconds, so nothing needs
to know the audio's length in advance. The feeling is still its own
`emotion` command:

```json
{"perform": {"syllables": "eaoiea", "events": [[0, "wave", 0.9], [4, "tilt", 0.6]]}}
{"syllable": 0}
{"syllable": 1}
```

Each event is a syllable, a gesture and a strength.

### Build order

| Step | What | Done when | Status |
|---|---|---|---|
| 1 | Mouth shapes from the phonemes the voice already makes | Side-by-side clips show the mouth rounding and closing on the right sounds; no lag against the audio | Built: five vowel shapes, rendered on the real stage (open "a" and "o", narrower "i" and "u", "i" wider); closed lips not yet |
| 2 | The speech planner, and gestures with phases that land on their word | Strokes land within 0.1 s of their word; nods on yes, shakes on no, tilts on questions in a scripted test reply | Built without phases. With the device's voice, 73% of word starts are marked within 0.1 s (90% within 0.16 s); streamed voices are looser (Part 1). The full core and stage, with the real voice, played a speech-caused look down on "sorry" |
| 3 | Channels, the scheduler and the budget | A nod plays through a wave; no channel ever snaps; gestures per minute stay in a set band over a ten-minute conversation | A per-sentence budget is built; the rest is to do |
| 4 | Drives (energy, boredom, sleepiness), idle actions and times of day | An hour of idling in fast-forward shows varied actions, no repeat within the cooldown, sleepy at night | To do |
| 5 | Listening and reactions | With a microphone, nods in the speaker's pauses; it looks up when speech starts | To do |
| 6 | Clips version 2, recorded clips (MediaPipe), the timeline page and the debug view | A recorded stretch and a recorded laugh play on three test characters; the debug view shows each layer live | To do |
| 7 | Temperament per character | Shy and confident test personas visibly move differently with the same reply | To do (the planner already takes an expressiveness) |

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
