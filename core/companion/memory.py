"""What a character remembers, kept on the device and editable by the owner.

Per character:

  history.jsonl   the recent conversation, one numbered turn per line
  notes.md        lasting notes about the owner and the relationship, in
                  plain words; the owner can read and edit them in the console
  episodes.jsonl  a dated summary of each stretch of conversation, kept for
                  good, so the character can recall what was said months ago;
                  the owner can read, edit and delete them in the console
  state.json      the last turn already summarised

Notes and a new summary come from one language-model call every few turns,
and once a conversation has gone quiet (`device.memory_watch`). The notes are
given to the model at the start of every reply, with the most recent summary
and the older summaries whose words best match what the owner just said,
found on the device without the model. Nothing here is ever put in a
character package.
"""
import datetime
import json
import math
import os
import re
import threading
import time

from .store import write_atomic

KEEP_TURNS = 400
NOTES_LIMIT = 4000
KEEP_EPISODES = 3000         # years of daily conversation
EPISODE_LIMIT = 600          # characters in one summary
RECALL = 3                   # older summaries recalled for a reply, besides the most recent
SAME_CONVERSATION = 1800     # turns closer than this (seconds) to the last summary extend it

# Words too common to say what a conversation was about.
STOPWORDS = set("""a about after again all also am an and any are as at be because been before being but by can
could did do does doing don't for from had has have having he her here hers him his how i i'm if in into is it it's
its just know like me more most my no not now of off oh ok okay on once only or other our out over really said say
she so some such than that that's the their them then there these they this those through to too up us very was we
were what when where which while who why will with would yeah yes you you're your yours
remember remembered tell told talk talks talked talking think thought thing things something anything want wanted
going gonna got get make made let well sure maybe mean right good great nice much many lot little bit kind sort way
day time last first back still even ever never always sometimes person character conversation""".split())

UPDATE_PROMPT = """You keep a character's memory of the person they talk with.

Current notes:
{notes}
{earlier}
Recent conversation:
{conversation}

Write the updated notes: short plain sentences, one per line, each starting
with "- ". Keep lasting facts (names, likes, plans, important events, how the
person wants to be treated) and drop small talk. Merge with the current
notes; remove anything the person corrected. At most 30 lines.

Then, on one last line starting with "EPISODE: ", say in one to three
sentences what this whole conversation was about, as the character would
remember it: the topics, anything that happened or was planned, and how the
person felt.

Reply with the notes and that line only."""
EARLIER = "\nEarlier in this same conversation (already summed up): {summary}\n"


class Memory:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.history_path = os.path.join(folder, "history.jsonl")
        self.notes_path = os.path.join(folder, "notes.md")
        self.episodes_path = os.path.join(folder, "episodes.jsonl")
        self.state_path = os.path.join(folder, "state.json")
        self._lock = threading.Lock()
        self._index_key = None          # the summaries' words, read again only when the file changes
        self._index = ([], [], {})

    # ----- the conversation
    def _lines(self):
        try:
            with open(self.history_path, encoding="utf-8") as f:
                return [l for l in f.read().splitlines() if l.strip()]
        except OSError:
            return []

    def history(self):
        out = []
        for line in self._lines():
            try:
                turn = json.loads(line)
            except ValueError:
                continue
            if isinstance(turn, dict):
                out.append(turn)
        return out

    def recent(self, turns):
        """The last `turns` exchanges as chat messages, oldest first."""
        messages = []
        for turn in self.history()[-turns:]:
            if turn.get("user"):
                messages.append({"role": "user", "content": turn["user"]})
            if turn.get("reply"):
                messages.append({"role": "assistant", "content": turn["reply"]})
        return messages

    def add_turn(self, user, reply, interrupted=False):
        # Turns are numbered, not only timed: a device without a clock battery can start with the wrong time.
        with self._lock:
            history = self.history()
            turn = {"n": (history[-1].get("n", 0) if history else 0) + 1, "t": round(time.time()),
                    "user": user, "reply": reply}
            if interrupted:
                turn["interrupted"] = True
            lines = self._lines() + [json.dumps(turn, ensure_ascii=False)]
            write_atomic(self.history_path, "\n".join(lines[-KEEP_TURNS:]) + "\n")

    def last_turn_time(self):
        history = self.history()
        return history[-1].get("t", 0) if history else 0

    # ----- notes
    def notes(self):
        try:
            with open(self.notes_path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def set_notes(self, text):
        text = (text or "").replace("\r\n", "\n")[:NOTES_LIMIT]
        write_atomic(self.notes_path, text)

    def clear(self):
        with self._lock:
            for path in (self.history_path, self.notes_path, self.episodes_path, self.state_path):
                if os.path.exists(path):
                    os.remove(path)

    # ----- summaries of earlier conversations
    def episodes(self):
        """Every summary, oldest first: {"id": last turn's number, "t": its time, "summary": text}."""
        out = []
        try:
            with open(self.episodes_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and isinstance(e.get("summary"), str) and isinstance(e.get("id"), int):
                        out.append(e)
        except OSError:
            pass
        return out

    def _write_episodes(self, episodes):
        write_atomic(self.episodes_path, "".join(json.dumps(e, ensure_ascii=False) + "\n"
                                                 for e in episodes[-KEEP_EPISODES:]))

    def add_episode(self, id, t, summary):
        summary = " ".join(summary.split())[:EPISODE_LIMIT]
        if summary:
            with self._lock:
                self._write_episodes([e for e in self.episodes() if e["id"] != id] +
                                     [{"id": int(id), "t": int(t), "summary": summary}])

    def edit_episode(self, id, summary):
        """Change one summary (the owner's wording wins); an empty one is forgotten. False if not found."""
        summary = " ".join((summary or "").split())[:EPISODE_LIMIT]
        with self._lock:
            episodes = self.episodes()
            found = any(e["id"] == id for e in episodes)
            if found:
                self._write_episodes([dict(e, summary=summary) if e["id"] == id else e
                                      for e in episodes if summary or e["id"] != id])
        return found

    def delete_episode(self, id):
        return self.edit_episode(id, "")

    def _episode_index(self):
        """The summaries, the words of each, and how many summaries have each word."""
        try:
            st = os.stat(self.episodes_path)
            key = (st.st_mtime_ns, st.st_size)
        except OSError:
            return [], [], {}
        if key != self._index_key:
            episodes = self.episodes()
            words = [set(_words(e["summary"])) for e in episodes]
            counts = {}
            for doc in words:
                for w in doc:
                    counts[w] = counts.get(w, 0) + 1
            self._index, self._index_key = (episodes, words, counts), key
        return self._index

    def recall(self, heard, limit=RECALL):
        """The most recent summary, and up to `limit` older ones whose words best match `heard`
        (rarer words count for more), oldest first."""
        episodes, docs, counts = self._episode_index()
        if not episodes:
            return []
        words = set(_words(heard))
        scored = []
        for i, doc in enumerate(docs[:-1]):
            shared = words & doc
            if shared:
                scored.append((sum(math.log(1 + len(episodes) / counts[w]) for w in shared), i))
        scored.sort(key=lambda x: (-x[0], -x[1]))          # best first; newer wins a tie
        return [episodes[i] for i in sorted(i for _, i in scored[:limit])] + [episodes[-1]]

    # ----- keeping notes and summaries up to date
    def _pending(self):
        """Turns not yet folded into the notes and a summary."""
        done = self._state().get("summarised", 0)
        return [turn for turn in self.history() if turn.get("n", 0) > done]

    def _state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    @property
    def turns_since_update(self):
        return len(self._pending())

    def _continues(self, pending):
        """The summary that the pending turns carry on from, if they belong to the same conversation."""
        episodes = self.episodes()
        if not pending or not episodes:
            return None
        last = episodes[-1]
        if last["id"] == self._state().get("summarised") and 0 <= pending[0].get("t", 0) - last["t"] < SAME_CONVERSATION:
            return last
        return None

    def update_prompt(self):
        """The request to the model: the current notes, the summary of this conversation so far
        (if it was summed up before), and the turns since the last update."""
        pending = self._pending()[-30:]
        earlier = self._continues(pending)
        lines = []
        for turn in pending:
            if turn.get("user"):
                lines.append("Person: %s" % turn["user"])
            if turn.get("reply"):
                lines.append("Character: %s" % turn["reply"])
        return UPDATE_PROMPT.format(notes=self.notes() or "(none yet)", conversation="\n".join(lines) or "(none)",
                                    earlier=EARLIER.format(summary=earlier["summary"]) if earlier else "")

    async def update_notes(self, llm):
        """Ask the language model to fold the conversation since the last update into the notes,
        and to sum it up for the summaries of earlier conversations (one summary per conversation:
        a later update of the same conversation replaces it). Returns the number of notes."""
        pending = self._pending()
        if not pending:
            return 0
        earlier = self._continues(pending)
        prompt = self.update_prompt()
        text = ""
        async for piece in llm.stream("You maintain concise notes.", [{"role": "user", "content": prompt}]):
            text += piece
        last = pending[-1]
        if last.get("n") not in {turn.get("n") for turn in self.history()}:
            return 0                          # the owner had the memory forgotten meanwhile
        lines, episode = parse_update(text)
        if lines:
            self.set_notes("\n".join(lines[:30]) + "\n")
        if episode:
            if earlier:
                self.delete_episode(earlier["id"])
            self.add_episode(last.get("n", 0), last.get("t", time.time()), episode)
        write_atomic(self.state_path, json.dumps({"summarised": last.get("n", 0)}))
        return len(lines)


EPISODE_LINE = re.compile(r"(?i)episode\s*[*_]*\s*:\s*[*_]*\s*(.*)")


def parse_update(text):
    """The notes ("- " lines) and the summary ("EPISODE: " line) in the model's answer, allowing for
    the ways models dress that line up ("**Episode:**", "- EPISODE:", "## Episode:")."""
    notes, episode = [], ""
    for line in text.splitlines():
        line = line.strip()
        found = EPISODE_LINE.match(re.sub(r"^[-*#_\s]+", "", line))
        if found:
            episode = found.group(1).strip().strip("*_").strip()
        elif line.startswith("- "):
            notes.append(line)
    return notes, episode


WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|')*")


def _words(text):
    """The words that say what a text is about, each reduced to a rough stem ("baking", "baked" -> "bak")."""
    out = []
    for w in WORD.findall((text or "").lower().replace("’", "'")):
        w = w.strip("'")
        if w.endswith("'s"):
            w = w[:-2]
        if w in STOPWORDS or len(w) < 3:
            continue
        out.append(stem(w))
    return out


def stem(w):
    """A very small stemmer, enough to match a word's plural and verb forms."""
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            if suffix == "es" and not w[:-2].endswith(("s", "x", "z", "ch", "sh")):
                continue                      # "bakes": only the "s" goes
            if suffix == "s" and w.endswith("ss"):
                break
            w = w[:-len(suffix)] + keep
            if suffix in ("ing", "ed") and len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
                w = w[:-1]                    # "running" -> "run", but "falling" -> "fall"
            break
    if w.endswith("y") and len(w) > 3:
        w = w[:-1] + "i"
    elif w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


def when(t, now=None):
    """A summary's date in words: today, yesterday, 3 days ago, or the date."""
    now = now or time.time()
    day = datetime.date.fromtimestamp(t)
    days = (datetime.date.fromtimestamp(now) - day).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return "%d days ago" % days
    return "%d %s" % (day.day, day.strftime("%B %Y"))
