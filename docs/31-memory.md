# Memory: conversations, lasting memories and a diary

The character remembers the way a person does:
- each conversation as a whole: when it was, what it was about, and how you seemed;
- the lasting things it knows about you, which change as your life does;
- a diary, in its own words.

Everything stays on the device. The code is `core/companion/memory.py`; the owner sees and edits all of it on the settings page's **Memory** tab.

| Layer | What it holds | Kept |
|---|---|---|
| This conversation | Its words, word for word; a long one's early part as a running summary | Until it ends |
| Conversations | Each one's title, summary, how you seemed, when, and why it ended; every word in an archive | The latest 5,000 summaries (about four years of daily talks); every word always |
| Lasting memories | One sentence each, with a category, an importance (1 to 5), when learnt and last changed, and a date for plans | Up to 600; the least important go first |
| The diary | An entry for each day you talked, in the character's voice | Always |
| Your notes | What you ask it always to remember | Until you change them |

## Where one conversation ends and the next begins

| What happens | The conversation | Why |
|---|---|---|
| 20 minutes without a word | ends | The next words are a new start |
| A goodbye ("bye", "good night", "talk later", "gotta go" …) | ends three minutes later | "Oh, one more thing!" within three minutes carries it on |
| A new day: a pause of five minutes or more across 4 am | ends | Chatting at 1 am still belongs to the night before; the morning starts afresh |
| The owner presses **Start a new conversation** | ends at once | Like CODE27's *Reset Context* |

The next word begins the next conversation.

Turns are numbered as well as timed, because a device without a clock battery can boot with the wrong time. A clock that jumps back neither ends a conversation nor muddles its turns.

A conversation that is over is summed up in the background within a minute, never while the character is talking. That includes one cut short by a restart or a change of character.

## Inside a conversation: condensed as it goes

The model gets the conversation word for word. In a long one, the early part is condensed as it goes. The owner's "turns word for word" setting is 12 by default. Once there are 12 more turns than that which haven't been summed up, all but the latest 12 are folded into a running summary, which the model gets as "Earlier in it: …".

So the model always has the gist of the whole conversation and its latest words exactly, with nothing falling between the two. This happens between replies, as a separate call.

## After a conversation: summed up, and what it learnt

One call to the owner's language model gives the conversation:
- a title, a summary and the person's mood;
- the changes to the lasting memories.

The model is shown:
- the memories that may matter: those sharing the conversation's rarer words, and the important ones, each with its number, category and date;
- which of them are plans whose day has come;
- the conversation itself.

It answers in a fixed form. This is a real answer, from the check below:

```
TITLE: Kim's move to Darwin
SUMMARY: Sam shared that their sister Kim moved from Perth to Darwin last week for a new job.
Sam expressed feeling a bit sad that Kim is now so far away, and I reassured them.
MOOD: Sad
UPDATE #4 | Their sister is named Kim and lives in Darwin.
```

| Change | Meaning |
|---|---|
| `ADD category \| importance \| sentence \| date or -` | Something new and lasting: names, people, likes, plans with their dates, how they want to be treated, promises |
| `UPDATE #n \| sentence` | What was said wins over what was remembered: Kim lived in Perth, now Darwin |
| `FORGET #n \| why` | No longer true, or they asked it to forget. The memory is retired, not deleted: the owner sees it under *No longer true* and can restore it |
| `FOLLOW UP date \| what to ask` | Something to ask about from a date |

A memory that says nearly the same as one already kept (three quarters of their words shared) updates that one instead of adding another.

**Reading what the model wrote** is forgiving, because small models drift from the form. Every one of these was seen from a real model and is handled:
- markdown;
- an echoed placeholder (`FOLLOW UP YYYY-MM-DD 2026-11-13`);
- the category repeated (`UPDATE #2 plans and events: …`);
- a stray date field (`… new job. -`, `… (2026-11-13)`, which becomes the memory's date);
- a colon instead of a bar;
- a missing importance.

Guards keep a small model's mistakes out:
- A memory that is only a category's name, the form's own words, or a single word is left out.
- At most eight new memories and eight updates are taken from one conversation, so a model stuck in a loop can't flood the list.
- A new memory is read field by field, whatever the order or labels.
- An update of a memory the model was never shown is kept as something new.
- A forget whose reason plainly names a different memory is not carried out.
- Plans whose day has come are always shown to it, so a conversation can settle them.
- The memory work runs at a low temperature (0.3), careful rather than lively.

A plain paragraph instead of the form becomes the summary. No answer at all leaves the person's own first words, so the conversation can still be found.

A failed call is reported on the settings page and tried again 15 minutes later.

## Lasting memories

| Category | For example |
|---|---|
| about them | Their name is Sam |
| their people | Their sister is named Kim and lives in Darwin |
| likes and dislikes | They love oolong tea |
| work and study | They are studying nursing |
| plans and events | They had their driving test on 2026-11-13 and passed on the first try |
| health and wellbeing | They are vegetarian |
| our relationship | They like it when I tease them a little |
| about me | I said my favourite season is autumn (so the character stays consistent) |
| other | |

**Importance:**

| Level | Meaning |
|---|---|
| 5 | Who they are: name, family |
| 4 | What matters a lot to them |
| 3 | Useful |
| 2 | Minor |
| 1 | Trivial |

Pinned memories are always in mind. When 600 are kept, the least important and longest unchanged go first; pinned ones stay.

**Plans come back.** A plan or event with a date comes up by itself once its day has passed. The next conversation's first reply is told: "Plans whose day has come; ask how they went, once, early in this conversation". It keeps coming up until the person says how it went, which changes the memory after that day. It comes up at most twice, and within a fortnight.

The model can also ask to follow something up from a date. In the real run, Mika's first words on the Saturday after the driving test were "Good morning, Sam! How did your driving test go yesterday, and how is it having Kim here from Perth?"

## The diary

Each day you talked, the character writes an entry in its own voice, 80 to 160 words. It writes from 9 pm, once things have been quiet for half an hour, or else the next day. It is given:
- the day's conversations (titles and summaries);
- what it learnt that day;
- its previous entry;
- how many days had passed since you last talked.

It writes about you, not to you, and only from what it heard: it can't see you.

The next day's first conversation gets the latest entry, so the character can pick up where it left off. An entry more than a week old isn't news, and is left out.

## Speaking first (an option, off unless turned on)

With **Device → Speak first** on, the character greets you when you come back after a while, like CODE27's greetings and check-ins. It uses what it remembers:
- how long it has been;
- plans whose day has come.

From a real model, four days after Sam mentioned their driving test: "Good morning, Sam! It is so good to see you again. How did your driving test go on Friday, and was it wonderful seeing Kim after she flew in from Perth?"

**How it knows someone is there:** a second or more of speech-like sound in the room. A cough or a door isn't enough. It goes only by how loud the room is: nothing is recorded, recognised or sent anywhere, and nothing at all happens with the option off.

**When it greets:**
- only after you have been apart for a while (3 hours by default; or an hour, 8 hours, or a day);
- at most once in that time;
- never in quiet hours (10 pm to 8 am by default);
- never while it is talking, listening or thinking.

Afterwards it listens for 30 seconds, so you can simply answer. If nobody does, it stops listening, as before.

The model is told: "Nothing has been said yet. You hear someone nearby, most likely them, after about 4 days without talking. Speak first: greet them warmly and briefly…". The greeting is kept as a turn where only the character spoke.

**A limit:** a television left talking can count as someone there. That's one more reason for the gap and quiet hours, and why the option is off by default.

## What the model reads for each reply

In this order, the latest last, nearest what is said now:

1. **Your notes**, under "What they asked you always to remember". The model never changes these.
2. **Memories that matter now**:
   - the pinned ones;
   - the most important (4 and 5, up to ten);
   - up to eight that share words with what was just said.

   Rarer words count for more. Greetings, times of day and words of feeling ("love", "morning") don't count, and "baked" matches "baking".

   They also match **by meaning**: "my pup chewed my shoes" finds "They have a dog called Biscuit" (see below).
3. **Earlier conversations that may matter now**: up to three whose title and summary share words with what was said.
4. **On a conversation's first reply, plans whose day has come.**
5. **When you last talked, and about what**: "Your last conversation with them was on Thursday evening (3 days ago), "Shopping list": …".
   - If it ended under two hours ago, its last few turns come as messages.
   - If this is the day's first conversation, it is told so, with the latest diary entry.
   - Within a conversation, it gets when this one began and the summary of its early part instead.
6. **The conversation itself**, as chat messages.

**Room.** Everything fits within what the model can read at once. The total is (its context length − the reply) × 3.2 characters, less the persona and rules, between 2,000 and 60,000 characters. A third goes to the text above and the rest to the conversation.

When it doesn't fit, things are dropped in this order:
1. older conversations;
2. plans to ask about;
3. memories, the newest first;
4. the last conversation;
5. the notes.

The newest exchange is always kept. A cloud model (taken as 32,000 tokens) gets the full 60,000 characters. A model on your own computer with an 8,192-token context gets about 18,000.

Here is what the model was given on a Sunday morning, from a synthetic week on the virtual device, when the person said "Good morning! Kim loved the lasagne on Saturday":

```
What they asked you always to remember:
Please don't bring up my old job.

What you remember about them (bring things up only when they fit):
- [about them] They prefer to be called Sam
- [health and wellbeing] They are vegetarian
- [their people] Their sister Kim lives in Perth and visits on Saturday (Saturday 21 November 2026, yesterday)
- [likes and dislikes] They are making lasagne with ricotta and spinach

Earlier conversations that may matter now:
- on Wednesday evening (4 days ago), "Cooking for Kim": Kim is visiting on Saturday; Sam plans to cook her a vegetarian lasagne.

Plans whose day has come; ask how they went, once, early in this conversation:
- how Kim's visit went

Your last conversation with them was on Thursday evening (3 days ago), "Shopping list": Sam found a lasagne recipe for Kim's visit; it needs ricotta, so I gave them a shopping list.
This is the first time you have talked today.
From your diary (2026-11-19): Sam found the recipe for Saturday and I made them a shopping list. I love how much care they put into Kim's visit. I hope the lasagne turns out perfectly; I'll ask them how it went.
```

## Matching by meaning

Words alone miss a lot: "my pup", "a cuppa", "I visited Nan" share no words with "a dog called Biscuit", "oolong tea" or "their grandmother". So the device also turns what was said, and every memory and conversation, into vectors, and finds those whose meaning is close.

**The model** is Model2Vec's potion-base-8M (MIT, Minish Lab; distilled from BAAI's bge-base-en-v1.5). It is a table of one vector per word piece, averaged over a text. No neural network runs:
- the device reads it with numpy alone (`core/companion/meaning.py`), and its vectors are the same as the official library's;
- a remark takes under a tenth of a millisecond;
- about 15 MB of memory.

It is chosen for a 1 GB board. Vectors are made once per memory and conversation, kept in `vectors.npz`, and dropped with what they stand for.

**On 30 remarks whose memory shares few or no words with them** (`core/tests/test_meaning.py`):

| | Right memory given to the model | Extra memories per remark | Per reply |
|---|---|---|---|
| Words alone (before) | 9 of 30 | 0 | 0.3 ms |
| Words and meaning | 27 of 30 | about 1; at most 2 for small talk | 0.7 ms |

Among the models tried, a transformer (all-MiniLM-L6-v2) did slightly better in a raw ranking: 30 of 30 in its top three, against 29. But it needs a neural network runtime and about 25 times the computing, so the static model was chosen.

How it combines with words:
- **Memories:** up to four close in meaning (at least 0.18 alike, and within 0.15 of the closest) are added to the word matches, the pinned and the important ones.
- **Conversations:** ranked by words and meaning together.

Without the model's files (`/var/lib/companion/models/meaning`, shipped in the image or brought by an update), memory matches by words alone, as before.

## The Memory tab

| Section | What the owner can do |
|---|---|
| **Start a new conversation** | Ends the one going on; it is summed up as usual |
| **Always remember** | Your notes, kept in mind in every conversation |
| **What it remembers about you** | Grouped by category, with stars for importance. Add one (with a date for a plan); pin, change or forget any. *No longer true* lists retired ones, to restore or forget |
| **Conversations** | Newest first, with title, summary and mood. **Show words** shows every word of it; **Change** edits the summary (your words stand); **Forget** removes it and every word of it |
| **Diary** | Change or remove any entry |
| **Forget everything** | Clears that character's memory |

## Files on the device

In `/var/lib/companion/memory/<character>/`:

| File | Holds |
|---|---|
| `history.jsonl` | The latest 400 turns, each marked with its conversation |
| `archive/YYYY-MM.jsonl` | Every turn, a file a month |
| `sessions.jsonl` | The conversations that have ended |
| `memories.jsonl` | The lasting memories, retired ones included |
| `diary.jsonl` | The diary |
| `notes.md` | Your notes |
| `state.json` | The conversation going on, and what has been done |
| `vectors.npz` | One vector per memory and conversation, for matching by meaning |

Memory kept by the first version, before 2026-11-19, is carried over once:
- its notes, which the model wrote, become memories;
- its summaries become ended conversations;
- turns not yet summed up become the conversation going on.

## Privacy

- Memory never leaves the device in a character package or an export, and is never written to the logs.
- **Device → Reset everything** removes it.
- What the model reads for a reply goes to the language model you chose, with what you said. A model on your own computer keeps it in your home.
- Memory files are protected by the device's file permissions, not encrypted (see below).

## Compared with CODE27

From CODE27's website and manual, November 2026:

| CODE27 | Here |
|---|---|
| Memory items with content, category, and created and updated dates; learnt automatically; editable and deletable | The same, plus importance, pinning, dates for plans, plans that come back, and retired memories that can be restored |
| A nightly diary in the character's voice | The same, from 9 pm or the next day |
| Chat history with dates | Every conversation titled, summed up, with your mood; its words on request |
| *Reset Context* | *Start a new conversation* |
| A greeting when you come back, and check-ins after long silences | Done, as an option: it greets you when it hears someone after a while apart, mentioning the time apart and asking after plans |
| Bring your own model: "coming soon" | Done: cloud services, or a model on your own computer (`28-user-guide.md`) |
| Stored with AES-256 encryption | Not encrypted at rest (below) |

## Tested

**Unit tests**, `core/tests/test_memory.py` (30):
- where conversations end, and a clock that goes back;
- the archive, and forgetting a conversation whole;
- what the model reads within a conversation and in a new one;
- carried-over last words, and a summary that's late;
- which memories come up;
- plans that come back, and the summing-up prompt naming them;
- a small room;
- 3,000 conversations and 500 memories, still quick;
- summing up, updating and retiring;
- a long conversation condensed, and the owner's word-for-word setting;
- the diary once a day;
- a plain or empty answer;
- forgetting while summing up;
- the owner's changes, and the limit of 600;
- carrying over the first version;
- reading every answer form a real model wrote;
- dates and times in words.

**Other tests:**
- `test_web.py`: every Memory tab request, including retiring and restoring, and that memory never leaves in an export.
- `test_conversation.py`: the model is reminded of a matching earlier conversation.
- The Memory tab, checked in a browser with a synthetic week.

**With a real model, over eleven days.** Gemini 3.5 Flash Lite, a small, cheap model, ran with the device's memory code and system prompt, through the eleven days of `core/tools/memory_check.py`. That tool runs the same days against the model a device is set up with, so anyone can see how well their own model keeps memory before relying on it:

```bash
python3 core/tools/memory_check.py --data /var/lib/companion
```

It ends by passing or failing the key moments. The person's lines were scripted; the character's replies, summaries, memories and diary were the model's own. Six runs found the faults the changes above fix. The last run, on the final code:

| Day | Sam said | What happened |
|---|---|---|
| Mon 9, 19:00 | "I'm Sam … my driving test is this Friday, the 13th … my sister Kim is flying in from Perth … Bye!" | Ended by the goodbye. Summed up: the test with its date, Kim flying in from Perth, a question to ask after the test. Diary at 22:00 |
| Sat 14, 10:00 | "Good morning, Mika!" | **Mika: "Good morning, Sam! How did your driving test go yesterday, and how was it having Kim visit from Perth?"** |
| | "I passed! First try …", "Kim took me out for pancakes" | Summed up: the test memory became "they passed on the first try"; the question was rewritten with its answer, so it isn't asked again |
| Thu 19, 20:00 | "Big news: Kim moved to Darwin last week for a new job. … I'm a bit sad" | Summed up: Kim's memory became "moved to Darwin … after previously living in Perth" |
| Fri 20, 18:00 | "Where does my sister live now, and when did I pass my driving test?" | **Mika: "She lives in Darwin now, after moving there for her new job! And you passed your driving test on Friday the thirteenth, right on the first try."** |

The diary was in Mika's voice and noticed the gaps ("Four whole days is far too long to wait.").

What varied between runs:
- One run kept "Their name is Sam" as a memory and another didn't; the summaries had the name either way.
- Asked for dates rather than "last week", the model once guessed one (Kim moved "on 12 November").
- One diary entry called the test "years ago", after that chat had been titled a "driving test anniversary".

Small models embellish, and the owner can correct any of it on the Memory tab.

**A model on your own computer.** The same eleven days ran through the device's own Ollama client against a real Ollama (0.40), on a 4-core processor with no graphics card:

| Model | A reply | A memory step | How it kept memory |
|---|---|---|---|
| qwen2.5:3b (1.9 GB) | 4–8 s | 25–45 s | Poorly. Its summing-up repeated the form, left fields out, copied the form's own words back, and looped. It kept almost nothing true, and on the Friday said "My sister moved to Darwin recently … I don't have specific dates for when you passed your driving test". Held to a JSON schema (Ollama can do this), its answers were valid but still wrong ("Kim was coming to Perth"): the limit is the model, not the form |
| qwen2.5:7b (4.7 GB) | 4–17 s | 15–47 s | Mostly. It kept the test (then that it was passed) and Kim's move to Darwin, and answered the Friday question correctly: "Your sister Kim is in Darwin now for her new job. You passed your driving test on the first try on Friday, 13th". But it didn't ask how the test went, and its summaries and diary mixed up who did what ("Kim and I celebrated with pancakes"). Once it retired the wrong memory by number; that is now guarded |

Most of the guards above came from these runs, and the summing-up step is now the same whichever model does it.

**Advice.** Memory is only as good as the model's summing-up.
- A cloud model, even a small cheap one, keeps it well.
- On your own computer, use 7 to 8 billion parameters at least. Expect mistakes now and then; a look at the Memory tab helps.
- Larger models should do better, but weren't measured here (no graphics card).
- A 3-billion model can chat, but keeps poor memories.

`core/tools/memory_check.py` shows how your own model does.

## Not done yet

- **Knowing it is you**: speaking first goes by speech-like sound, so a television can set it off; telling voices apart would fix that.
- **Questions by date**: "what did we talk about last Monday?" isn't matched by its date.
- **More than one person**: memory assumes one person; telling voices apart isn't done.
- **Encryption at rest**: memory is protected by file permissions. Encrypting it would need a key the device can keep secret, a secure element or your password at start-up, which a Pi lacks.
- **Small models on your own computer**: memory is only as good as the model's summing-up (see Tested). A 3-billion model keeps poor memories, and a 7-billion one makes mistakes. Letting a bigger model on the same computer do the memory work, while a quick small one chats, would help; it isn't built.
