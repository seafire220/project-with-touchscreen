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
| Get a character | From a picture: Character Studio on a laptop (`studio/start.sh`: drop a picture in, watch a preview of it moving, fill in who it is, send it to the device), or `studio/make_character.py` on the command line. From a Live2D-format model folder: upload its zip on the settings page | Picture pipeline on test pictures; the studio's tests and a browser run into the virtual device; import on eight model folders | A run on the owner's own laptop; **a default character** in the box (needs commissioned original art) |
| Edit its personality | A guided form (name, personality, story, its relationship to the owner, likes and dislikes, how it speaks, what it never does, greeting) that writes the persona, or free text for those who prefer it; voice per character; feelings matched to a model's own expressions | Web tests | Done |
| Memory | The last 400 turns; notes about the owner (up to 4,000 characters); and a dated summary of each conversation, kept for years. One model call every 6 turns, or once a conversation has been quiet for 10 minutes, updates the notes and that conversation's summary. Each reply is given the notes, the latest summary and up to three older summaries that share the owner's rarer words (found on the device, no extra model call). Notes and summaries are shown, editable and deletable on the settings page | Unit and web tests; a real model (below) | Done. Later, if needed: matching by meaning as well as by words (a small on-device embedding model) |
| Chat by voice | Press the button (or speak, with an echo-cancelling sound card); local speech recognition (free); language models from OpenAI, Anthropic, Groq, OpenRouter, Google Gemini or any compatible service, streamed; timers, alarms, web search | Unit tests; real core with real stage; a real model (below) | Done: a free on-device voice is the default (see below and `16-measurements.md`); cloud voices remain as upgrades |
| Feelings and movement | Seven moods following the reply's emotion tags; eighteen gestures the character chooses or its mood starts; a model's own expressions mapped to feelings; feelings linger a few seconds after a reply | Stage and core tests; end-to-end check with the real core and stage (`core/tests/stack_check.py`) | Arms done for characters made from pictures (waves, hands on hips, shrugs), and movement settings for any character, imported ones included (which of its parameters each movement uses, tested live; 2026-11-18). Still to do: motion recorded from people (roadmap item 4) |

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
2. ~~**A guided personality form**~~: done (2026-11-18).
3. ~~**Memory that lasts**~~: done (2026-11-18), see below.
4. **Characters from pictures without the command line**: Character Studio
   (2026-11-18) does it on a laptop; the drawing workflow's completed parts
   are still to come. **A default character** needs commissioned art.
5. Then the motion polish (calibration, recorded motion) and head turns,
   and only then the boards.

## Memory over weeks, with a real model

The device's own memory code (`core/companion/memory.py`) with Google
Gemini 3.5 Flash Lite and the Mika persona. Three short conversations were
held as if 40 days ago, 12 days ago and yesterday, each summed up by the
device's usual update call; then three new remarks were made.

| Summary the model wrote (dated by the device) |
|---|
| 9 October 2026: "The person shared their excitement about starting a sourdough starter named Bubbles and asked for advice on its vinegar smell, while also enthusiastically sharing plans for an April trip to Kyoto to see the temples." |
| 6 November 2026: "...getting a new telescope and successfully spotting Jupiter's moons on the first try, and then expressed enthusiasm for observing the Orion Nebula next." |
| yesterday: "...an awful day at work because their manager Dave unexpectedly moved up a deadline... planned to decompress by playing video games..." |

| The owner said | Recalled | Mika said |
|---|---|---|
| Guess what, Bubbles finally made a proper loaf! | 9 October, yesterday | "Bubbles actually made it! Look at you, master baker, turning a jar of bubbly goop into a real honest-to-goodness loaf of bread." |
| Remind me, where was I going in April? | 9 October, yesterday | "You are heading to Kyoto in April to see all the gorgeous temples!" |
| What should I point my telescope at tonight? | 6 November, yesterday | "You should definitely try finding the Orion Nebula tonight!..." |

The summaries came back in the asked-for form, and each remark brought
back the right conversation. The run also showed the model writing a
stage direction of its own ("[smile]"), which the voice would have read
out. Invented directions in brackets or asterisks now become the matching
feeling or gesture ("[smile]" → happy, "*giggles*" → laugh,
"*puts hands on hips*" → hands on hips) or are left unsaid; emphasis such
as "*really*" keeps its word.

How it works, in brief:

- **When**: one call to the owner's language model every 6 turns, and once a
  conversation has gone quiet for 10 minutes (so short chats count, and so do
  the last turns before a restart or a change of character). The same call
  updates the notes. A conversation that continues within 30 minutes of its
  summary extends that summary rather than starting a new one.
- **Recall**: words are reduced to rough stems ("baked", "baking" → "bak"),
  common words are ignored, and rarer shared words count for more. Reading
  3,000 summaries (years of daily use) takes one pass when they change;
  recall then takes under 50 ms per reply.
- **Privacy**: everything stays on the device in the character's memory
  folder; notes and the recalled summaries are sent to the owner's chosen
  language model with each reply, as the notes already were. Nothing goes
  into exported character packages. "Forget everything" deletes the notes,
  summaries and conversation; single summaries can be changed or forgotten.

