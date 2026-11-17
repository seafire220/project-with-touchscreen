"""Turning a streamed reply into speakable sentences, emotions and actions.

The language model is asked to mark feelings with a tag such as [happy] and
to ask for timers and alarms with tags such as [timer 5m tea] or
[alarm 07:30 wake up]. Tags are removed from what is spoken and returned
separately. The text is cut into sentences as it arrives so the voice can
start on the first sentence while the rest is still being written.
"""
import re

EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised", "embarrassed", "thinking")
GESTURES = ("nod", "shake", "bow", "tilt")

TAG = re.compile(r"\[([^\[\]]{1,80})\]")
SENTENCE_END = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+)")
CLAUSE_END = re.compile(r"([,;:—–])(\s+)")
MARKDOWN = re.compile(r"(\*\*|__|`+|^#+\s*|^\s*[-*•]\s+)", re.M)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")

# Start speaking sooner: if the first sentence runs long, break it at a comma.
FIRST_CLAUSE_AFTER = 70
# Very short pieces are joined to the next, so the voice is not asked for "Oh."
MIN_SPOKEN = 12


def parse_duration(text):
    """'5m', '90s', '1h30m', '2 minutes' -> seconds, or None."""
    text = text.strip().lower()
    total, found = 0, False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hours?|m|mins?|minutes?|s|secs?|seconds?)", text):
        seconds = float(amount) * (3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1)
        total += seconds
        found = True
    if not found and re.fullmatch(r"\d+", text):
        return int(text) * 60
    return int(total) if found and total > 0 else None


def parse_tag(body):
    """One tag's text -> ('emotion', name) or ('action', {...}) or None."""
    words = body.strip().split(None, 1)
    if not words:
        return None
    head = words[0].lower()
    rest = words[1] if len(words) > 1 else ""
    if head in EMOTIONS and not rest:
        return ("emotion", head)
    if head in GESTURES and not rest:
        return ("action", {"kind": "gesture", "name": head})
    if head == "timer":
        m = re.match(r"((?:\d+(?:\.\d+)?\s*[a-z]*\s*)+)(.*)", rest.strip(), re.I)
        if m:
            seconds = parse_duration(m.group(1))
            if seconds:
                return ("action", {"kind": "timer", "seconds": seconds, "label": m.group(2).strip()})
    if head == "alarm":
        m = re.match(r"(\d{1,2}):(\d{2})\s*(.*)", rest.strip())
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return ("action", {"kind": "alarm", "time": "%02d:%02d" % (int(m.group(1)), int(m.group(2))),
                               "label": m.group(3).strip()})
    if head == "cancel" and rest:
        return ("action", {"kind": "cancel", "label": rest.strip()})
    if head == "search" and rest:
        return ("action", {"kind": "search", "query": rest.strip()})
    return None


def clean_for_speech(text):
    text = MARKDOWN.sub("", text)
    text = EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


class Splitter:
    """Feed streamed text in; get (sentence, emotion, actions) pieces out."""

    def __init__(self):
        self.buffer = ""
        self.pending_emotion = None
        self.pending_actions = []
        self.first = True

    def _take_tags(self, text):
        def replace(match):
            parsed = parse_tag(match.group(1))
            if parsed is None:
                return match.group(0)
            kind, value = parsed
            if kind == "emotion":
                self.pending_emotion = value
            else:
                self.pending_actions.append(value)
            return ""
        return TAG.sub(replace, text)

    def _emit(self, raw):
        text = clean_for_speech(raw)
        emotion, actions = self.pending_emotion, self.pending_actions
        self.pending_emotion, self.pending_actions = None, []
        self.first = False
        return (text, emotion, actions)

    def feed(self, piece):
        """Add streamed text; return the pieces now complete."""
        self.buffer += piece
        # A tag may still be arriving: hold back an unclosed "[".
        open_at = self.buffer.rfind("[")
        if open_at != -1 and "]" not in self.buffer[open_at:] and len(self.buffer) - open_at < 80:
            ready, held = self.buffer[:open_at], self.buffer[open_at:]
        else:
            ready, held = self.buffer, ""
        ready = self._take_tags(ready)
        out = []
        while True:
            m = SENTENCE_END.search(ready)
            if not m and self.first and len(ready) > FIRST_CLAUSE_AFTER:
                m = CLAUSE_END.search(ready, FIRST_CLAUSE_AFTER // 2)
            if not m:
                break
            cut = m.end(1)
            sentence = ready[:cut]
            if len(clean_for_speech(sentence)) < MIN_SPOKEN:
                # Too short to say on its own: wait for the next sentence and say them together.
                nxt = SENTENCE_END.search(ready, m.end())
                if not nxt:
                    break
                cut, m = nxt.end(1), nxt
                sentence = ready[:cut]
            ready = ready[m.end():]
            piece_out = self._emit(sentence)
            if piece_out[0] or piece_out[1] or piece_out[2]:
                out.append(piece_out)
        if "\n" in ready:
            lines = ready.split("\n")
            for line in lines[:-1]:
                if line.strip():
                    out.append(self._emit(line))
            ready = lines[-1]
        self.buffer = ready + held
        return out

    def flush(self):
        """The rest, at the end of the reply."""
        text = self._take_tags(self.buffer)
        self.buffer = ""
        if clean_for_speech(text) or self.pending_emotion or self.pending_actions:
            return [self._emit(text)]
        return []


SPEECH_RULES = """Your words are spoken aloud by a voice, so:
- Reply in plain spoken sentences. No lists, headings, markdown or emoji.
- Keep replies short unless asked for detail: usually one to three sentences.
- You may show a feeling by putting one of these tags before a sentence:
  [happy] [sad] [angry] [surprised] [embarrassed] [thinking] [neutral]
- You may move with [nod] [shake] (your head) [bow] or [tilt] (your head, curious).
  Use them sparingly, where a person would.
- To set a timer, include a tag like [timer 5m tea]. For an alarm, [alarm 07:30 wake up].
  To cancel one, [cancel tea]. Say in words what you did as well.
- Tags are never read out."""

SEARCH_RULE = """- To look something up on the web, say briefly that you will check, then include a
  tag like [search weather in Brisbane today]. You will be given the results to answer from."""
