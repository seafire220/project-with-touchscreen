# Does the whole product fit together?

Status: 2026-11-18. A walk through the product the owner describes (like
SyBran's CODE27): the buyer adds a character, edits its personality and
memory, and chats with it by voice; it shows its feelings and moves as it
talks; its memory grows over time. Each step says what exists, how it was
checked, and what is missing. Hardware comes last, once this list is done.

## Step by step

| Step | What exists | Checked | Missing |
|---|---|---|---|
| Set up the device | Wi-Fi from the phone (hotspot, then the home network), a password, then the buyer's own keys on the settings page | Unit tests, the virtual device and its browser test | A run on a real board (later) |
| Get a character | From a picture: `studio/make_character.py` on a laptop (command line). From a Live2D-format model folder: upload its zip on the settings page | Picture pipeline on test pictures; import on eight model folders | **A one-click app** for pictures (roadmap item 6); **a default character** in the box (needs commissioned original art) |
| Edit its personality | Free-text persona with a template and greeting; voice per character; feelings matched to a model's own expressions | Web tests | **A guided form** (name, personality, how it speaks, its relationship to the owner, likes and dislikes, greeting) for owners who do not want to write a prompt |
| Memory | The last 400 turns; notes about the owner that the language model rewrites every 6 turns (up to 4,000 characters), shown and editable on the settings page | Unit tests | **Memory that lasts**: the notes fill up and older conversations are never recalled. Proposed: a dated summary of each conversation kept in an archive and searched by the owner's words (no extra model call), the matches given to the model with the notes |
| Chat by voice | Press the button (or speak, with an echo-cancelling sound card); local speech recognition (free); language models from OpenAI, Anthropic, Groq, OpenRouter, Google Gemini or any compatible service, streamed; timers, alarms, web search | Unit tests; real core with real stage; a real model (below) | Done: a free on-device voice is the default (see below and `16-measurements.md`); cloud voices remain as upgrades |
| Feelings and movement | Seven moods following the reply's emotion tags; eighteen gestures the character chooses or its mood starts; a model's own expressions mapped to feelings; feelings linger a few seconds after a reply | Stage and core tests; end-to-end check with the real core and stage (`core/tests/stack_check.py`) | Calibration per character, recorded human motion, drawn arm poses (roadmap items 4 and 6) |

## A real conversation

Five turns with a real language model (Google Gemini 3.5 Flash Lite on the
owner's free-tier key) through the device's own conversation code, with an
original test persona (Mika: cheerful, teasing, likes astronomy and baking).

| The owner said | Mika's feeling and movement | What Mika said (shortened) |
|---|---|---|
| Hi Mika! I just got home from work. | happy; wave, hands on hips | "Welcome home! You survived another shift! Now go put your feet up..." |
| It was a rough day, my boss yelled at me. | sad; look down, lean in | "Oh no, that's awful! ... Do you want to vent about it?" |
| You always cheer me up. You're the best. | embarrassed; look away, laugh, sway | "Oh, um, well, obviously! I mean, thank you..." |
| Any fun facts about Saturn? | happy; bounce | Two facts about its rings and density |
| Set a timer for 10 minutes for my cookies. | happy | A real 10-minute timer was set |

What this shows: the pieces fit. Replies are short, spoken and in
character; the emotions fit what is said; gestures fit too, though the
model asked for two or three in some replies, so asked-for gestures now
queue and play in turn instead of cutting each other short. Larger free
Gemini models were overloaded at the time (timeouts and "high demand"
errors), which buyers on free tiers will also meet: the device already
says so and goes back to rest.

## Verdict, and the order to finish it

In software the product fits together: a character can be added, edited,
talked to, and it reacts with feelings and movement in step with its
speech. What stands between this and a product, in order:

1. ~~**A free local voice**~~: done (2026-11-18): a Piper voice with 904
   speakers runs on the device through sherpa-onnx, with phonemes from
   espeak-ng, and is the default; 24 clear voices, chosen by a survey of all
   904, are offered on the settings page.
2. **A guided personality form** on the settings page.
3. **Memory that lasts**: the conversation archive with recall.
4. **Characters from pictures without the command line** (the one-click
   app, with the drawing workflow's parts) and **a default character**.
5. Then the motion polish (calibration, recorded motion) and head turns,
   and only then the boards.
