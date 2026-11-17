"""What a character remembers, kept on the device and editable by the owner.

Two parts, per character:

  history.jsonl   the recent conversation, one turn per line
  notes.md        lasting notes about the owner and the relationship, in
                  plain words; the owner can read and edit them in the console

Notes are brought up to date by the language model every few turns. They are
given to the model at the start of every reply. Nothing here is ever put in
a character package.
"""
import json
import os
import threading
import time

from .store import write_atomic

KEEP_TURNS = 400
NOTES_LIMIT = 4000

UPDATE_PROMPT = """You keep a character's memory of the person they talk with.

Current notes:
{notes}

Recent conversation:
{conversation}

Write the updated notes: short plain sentences, one per line, each starting
with "- ". Keep lasting facts (names, likes, plans, important events, how the
person wants to be treated) and drop small talk. Merge with the current
notes; remove anything the person corrected. At most 30 lines. Reply with the
notes only."""


class Memory:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.history_path = os.path.join(folder, "history.jsonl")
        self.notes_path = os.path.join(folder, "notes.md")
        self._lock = threading.Lock()
        self.turns_since_update = 0

    def recent(self, turns):
        """The last `turns` exchanges as chat messages, oldest first."""
        lines = self._lines()[-turns:]
        messages = []
        for line in lines:
            try:
                turn = json.loads(line)
            except ValueError:
                continue
            if turn.get("user"):
                messages.append({"role": "user", "content": turn["user"]})
            if turn.get("reply"):
                messages.append({"role": "assistant", "content": turn["reply"]})
        return messages

    def _lines(self):
        try:
            with open(self.history_path, encoding="utf-8") as f:
                return [l for l in f.read().splitlines() if l.strip()]
        except OSError:
            return []

    def add_turn(self, user, reply, interrupted=False):
        turn = {"t": round(time.time()), "user": user, "reply": reply}
        if interrupted:
            turn["interrupted"] = True
        with self._lock:
            lines = self._lines() + [json.dumps(turn, ensure_ascii=False)]
            write_atomic(self.history_path, "\n".join(lines[-KEEP_TURNS:]) + "\n")
        self.turns_since_update += 1

    def history(self):
        out = []
        for line in self._lines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

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
        for path in (self.history_path, self.notes_path):
            if os.path.exists(path):
                os.remove(path)
        self.turns_since_update = 0

    def update_prompt(self, turns=12):
        lines = []
        for m in self.recent(turns):
            lines.append("%s: %s" % ("Person" if m["role"] == "user" else "Character", m["content"]))
        return UPDATE_PROMPT.format(notes=self.notes() or "(none yet)", conversation="\n".join(lines) or "(none)")

    async def update_notes(self, llm):
        """Ask the language model to fold the recent conversation into the notes."""
        prompt = self.update_prompt()
        text = ""
        async for piece in llm.stream("You maintain concise notes.", [{"role": "user", "content": prompt}]):
            text += piece
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith("- ")]
        if lines:
            self.set_notes("\n".join(lines[:30]) + "\n")
        self.turns_since_update = 0
        return len(lines)
