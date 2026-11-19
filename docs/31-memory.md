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

## What the model reads for each reply

In this order, the latest last, nearest what is said now:

1. **Your notes**, under "What they asked you always to remember". The model never changes these.
2. **Memories that matter now**:
   - the pinned ones;
   - the most important (4 and 5, up to ten);
   - up to eight that share words with what was just said.

   Rarer words count for more. Greetings, times of day and words of feeling ("love", "morning") don't count, and "baked" matches "baking".
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
| A greeting when you come back, and check-ins after long silences | Partly. It knows when you last talked and whether it is the day's first conversation, and asks after plans, but only once you speak. Speaking first is not done yet |
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

**With a real model, over eleven days.** Gemini 3.5 Flash Lite, a small, cheap model, ran with the device's memory code and system prompt. The person's lines were scripted; the character's replies, summaries, memories and diary were the model's own. The changes it showed were made (above), and on the final run:

| Day | Sam said | What happened |
|---|---|---|
| Mon 9, 19:00 | "I'm Sam … my driving test is this Friday, the 13th … my sister Kim is flying in from Perth … Bye!" | Ended by the goodbye. Summed up with six changes: "Their name is Sam", the test with its date, Kim in Perth, and a follow-up. Diary at 22:00 |
| Sat 14, 10:00 | "Good morning, Mika!" | **Mika: "Good morning, Sam! How did your driving test go yesterday, and how is it having Kim here from Perth?"** |
| | "I passed! First try …", "Kim took me out for pancakes" | Summed up: the test memory updated to "passed on the first try", the follow-up retired |
| Thu 19, 20:00 | "Big news: Kim moved to Darwin last week for a new job. … I'm a bit sad" | Mika: "Oh, wow! Darwin all the way from Perth?" Summed up: Kim's memory updated to Darwin (the answer above) |
| Fri 20, 18:00 | "Where does my sister live now, and when did I pass my driving test?" | **Mika: "She lives up in Darwin now! And you passed your driving test a week ago today, on Friday the thirteenth, and even nailed that parallel parking."** |

The diary was in Mika's voice and noticed the gaps ("Four whole days since we last talked. I missed Sam so much."). One detail was wrong: the last entry called the test "years ago", after the summing-up had titled that chat a "driving test anniversary". Small models embellish.

**A model on your own computer**: see below.

## Not done yet

- **Speaking first**: greeting you when you come into the room, or checking in after a long silence.
- **Matching by meaning**: today matching is by words, with their forms ("baked", "baking"); "my pup" won't find "their dog". A small on-device embedding model would add this.
- **Questions by date**: "what did we talk about last Monday?" isn't matched by its date.
- **More than one person**: memory assumes one person; telling voices apart isn't done.
- **Encryption at rest**: memory is protected by file permissions. Encrypting it would need a key the device can keep secret, a secure element or your password at start-up, which a Pi lacks.
- **Very small models**: memory is only as good as the model's summaries. The form is read forgivingly, but a 1B model will miss things a cloud model catches.
