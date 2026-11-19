"""How well a language model keeps the character's memory: eleven days of scripted conversations.

    python core/tools/memory_check.py [--data /var/lib/companion] [--model NAME] [--out FOLDER]

Uses the language model the device is set up with (its saved settings and keys in DATA, cloud or on
the owner's own computer), or another model of the same service with --model. A person called Sam
talks with a character called Mika four times over eleven days:
1. their name, a driving test on Friday the 13th, and a sister flying in from Perth;
2. the morning after the test: they passed;
3. the sister has moved to Darwin;
4. "where does my sister live now, and when did I pass my driving test?"

The device's own memory code does everything between the conversations, as on the device: ending them,
summing them up, keeping memories, the diary. The check prints each conversation, the summaries, the
memories and the diary, and whether the key moments came out right:
- the character asks how the test went;
- the memories say Kim lives in Darwin;
- the last answer has Darwin and the 13th.

Nothing is kept: the memory is made in a temporary folder (or OUT, to look at it after).
"""
import argparse
import asyncio
import datetime
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import providers  # noqa: E402
from companion.conversation import CHARS_PER_TOKEN, system_prompt  # noqa: E402
from companion.memory import Memory  # noqa: E402
from companion.store import Store  # noqa: E402

PERSONA = ("You are Mika, a cheerful and curious companion who lives in a small screen on the desk of the person "
           "you talk with. You are warm and a little playful, and you speak in short, natural sentences, because "
           "your words are spoken aloud. You care about them and remember what matters to them.")
GESTURES = ("nod", "shake", "bow", "tilt", "wave")
YEAR, MONTH = 2026, 11
TALKS = [
    (9, 19, ["Hi Mika! I'm Sam, by the way.",
             "My driving test is this Friday, the 13th. I'm really nervous about parallel parking.",
             "My sister Kim is flying in from Perth to cheer me on.",
             "Anyway, I have to go and cook dinner. Bye!"]),
    (14, 10, ["Good morning, Mika!",
              "I passed! First try, and the parallel parking was perfect.",
              "Kim took me out for pancakes to celebrate.",
              "See you later!"]),
    (19, 20, ["Hey Mika. Big news: Kim moved to Darwin last week for a new job.",
              "I'm a bit sad she's so far away now.",
              "Good night!"]),
    (20, 18, ["Mika, quick question: where does my sister live now, and when did I pass my driving test?"]),
]


def at(day, hour, minute=0):
    return datetime.datetime(YEAR, MONTH, day, hour, minute).timestamp()


async def say(memory, llm, heard, t):
    """One turn, as the device takes it: what the memory gives, the reply, the turn kept."""
    base = system_prompt(PERSONA, "", gestures=GESTURES)
    tokens = getattr(llm, "context", None) or 32000
    reply_tokens = getattr(llm, "max_tokens", 400) or 400
    room = max(2000, min(int((tokens - reply_tokens) * CHARS_PER_TOKEN) - len(base) - len(heard) - 1500, 60000))
    remembered, past = memory.context(heard, now=t, room=room)
    system = system_prompt(PERSONA, remembered, now=datetime.datetime.fromtimestamp(t), gestures=GESTURES)
    reply = ""
    async for piece in llm.stream(system, past + [{"role": "user", "content": heard}]):
        reply += piece
    spoken = " ".join(re.sub(r"\[[^\]]*\]|\*[^*]*\*", "", reply).split())
    memory.add_turn(heard, spoken, now=t)
    return spoken


async def run_check(llm, memory_llm, folder, show=print):
    """The eleven days with these models (the second for the memory work). Returns the checks: name -> passed."""
    memory = Memory(folder)
    replies = {}
    for day, hour, lines in TALKS:
        start = at(day, hour)
        show("\n== %s" % datetime.datetime.fromtimestamp(start).strftime("%A %d %B %H:%M"))
        for k, heard in enumerate(lines):
            reply = await say(memory, llm, heard, start + 60 * k)
            replies[(day, k)] = reply
            show("  Sam:  %s\n  Mika: %s" % (heard, reply))
        end = start + 60 * len(lines)
        for t in (end + 600, datetime.datetime.fromtimestamp(start).replace(hour=22).timestamp()):
            if t > end:
                done = await memory.process(memory_llm, now=t, name="Mika", persona=PERSONA)
                if done["summed"] or done["diary"]:
                    show("  [memory: %d summed up, %d memories changed%s]" % (
                        done["summed"], done["memories"], ", diary written" if done["diary"] else ""))
    show("\n== Conversations")
    for s in memory.sessions():
        show("  %s, ended by %s: %s: %s (%s)" % (datetime.datetime.fromtimestamp(s["start"]).strftime("%a %d %b"),
                                               s.get("why"), s.get("title"), s.get("summary"), s.get("mood")))
    show("== Memories")
    for m in memory.memories():
        show("  [%s, %d%s] %s" % (m["category"], m["importance"], ", " + m["when"] if m.get("when") else "", m["text"]))
    show("== Diary")
    for d in memory.diary():
        show("  %s: %s" % (d["day"], " ".join(d["text"].split())))
    known = " ".join(m["text"] for m in memory.memories()).lower()
    last = replies.get((20, 0), "").lower()
    checks = {
        "asks how the test went": bool(re.search(r"\btest\b", replies.get((14, 0), "").lower())),
        "remembers Kim lives in Darwin": "darwin" in known and "kim" in known,
        "answers Darwin": "darwin" in last,
        "answers the 13th": bool(re.search(r"13|thirteenth", last)),
        "wrote a diary": len(memory.diary()) >= 3,
    }
    show("\n== Checks")
    for name, ok in checks.items():
        show("  %s  %s" % ("PASS" if ok else "FAIL", name))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", default="/var/lib/companion", help="the device's data folder (its settings and keys)")
    parser.add_argument("--model", help="another model of the same service")
    parser.add_argument("--out", help="keep the memory made here, to look at")
    args = parser.parse_args()
    store = Store(os.path.join(args.data, "config"))
    settings = store.settings()
    if args.model:
        settings["llm"]["model"] = args.model
    from companion.device import MEMORY_MAX_TOKENS, MEMORY_TEMPERATURE
    llm = providers.build_llm(settings, store)
    careful = providers.build_llm(settings, store)            # as the device does its memory work
    if isinstance(getattr(careful, "temperature", None), (int, float)):
        careful.temperature = min(careful.temperature, MEMORY_TEMPERATURE)
    if isinstance(getattr(careful, "max_tokens", None), int):
        careful.max_tokens = max(careful.max_tokens, MEMORY_MAX_TOKENS)
    print("Model: %s (%s)" % (settings["llm"].get("model"), settings["llm"].get("provider")))
    with tempfile.TemporaryDirectory() as scratch:
        folder = args.out or scratch
        checks = asyncio.run(run_check(llm, careful, folder))
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
