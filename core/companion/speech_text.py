"""Turning a streamed reply into speakable sentences, emotions and actions.

The language model is asked to mark feelings with a tag such as [happy] and
to ask for timers and alarms with tags such as [timer 5m tea] or
[alarm 07:30 wake up]. Tags are removed from what is spoken and returned
separately. The text is cut into sentences as it arrives so the voice can
start on the first sentence while the rest is still being written.
"""
import re

EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised", "embarrassed", "thinking")
# Every gesture in the stage's library (stage/motions/library.json; a test keeps the
# two in step). The model is told only those its character can make.
GESTURES = ("bounce", "bow", "emphatic_nod", "hands_on_hips", "laugh", "lean_back", "lean_in", "look_away",
            "look_down", "nod", "shake", "shrug", "sigh", "surprise", "sway", "think", "tilt", "wave")

GESTURE_WORDS = {
    "nod": "nod", "shake": "shake your head", "bow": "bow", "tilt": "tilt your head, curious",
    "bounce": "bounce with joy", "emphatic_nod": "nod firmly", "laugh": "laugh", "sigh": "sigh",
    "sway": "sway", "look_away": "look away, shy", "look_down": "look down", "lean_in": "lean in",
    "lean_back": "lean back", "surprise": "start in surprise", "think": "look up, thinking",
    "hands_on_hips": "put your hands on your hips", "wave": "wave", "shrug": "shrug",
}

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
    """Feed streamed text in; get (sentence, emotion, actions) pieces out.

    Each tag applies to the sentence it comes before, however the stream
    happens to be broken up: tags keep their place in the text until their
    sentence is cut. An emotion tag after some words ends the piece there, so
    a short sentence is never joined to the next across a change of feeling.
    """

    def __init__(self):
        self.raw = ""        # streamed text not yet read for tags (it may end inside a tag)
        self.text = ""       # tag-free text not yet given out
        self.tags = []       # (offset in self.text, ("emotion", name) or ("action", {...}))
        self.first = True

    def _read_tags(self, final=False):
        raw = self.raw
        open_at = raw.rfind("[")
        if not final and open_at != -1 and "]" not in raw[open_at:] and len(raw) - open_at < 80:
            ready, self.raw = raw[:open_at], raw[open_at:]      # a tag may still be arriving
        else:
            ready, self.raw = raw, ""
        pos = 0
        for m in TAG.finditer(ready):
            self.text += ready[pos:m.start()]
            parsed = parse_tag(m.group(1))
            if parsed is None:
                self.text += m.group(0)
            else:
                self.tags.append((len(self.text), parsed))
            pos = m.end()
        self.text += ready[pos:]

    def _next_cut(self, final):
        """Where the next piece ends: (end of its words, where the following text starts), or None to wait."""
        text = self.text
        emotion_at = next((at for at, (kind, _) in self.tags
                           if kind == "emotion" and at > 0 and clean_for_speech(text[:at])), None)
        region = text if emotion_at is None else text[:emotion_at]
        bounded = emotion_at is not None or final      # nothing more can join this region
        m = SENTENCE_END.search(region)
        if not m and self.first and len(region) > FIRST_CLAUSE_AFTER:
            m = CLAUSE_END.search(region, FIRST_CLAUSE_AFTER // 2)
        newline = region.find("\n")
        if newline != -1 and (m is None or newline < m.start()):
            return newline, newline + 1
        if m is None:
            return (len(region), len(region)) if bounded and region else None
        cut, end = m.end(1), m.end()
        if len(clean_for_speech(region[:cut])) < MIN_SPOKEN:
            # Too short to say on its own: say it with the next sentence, if one can follow.
            nxt = SENTENCE_END.search(region, m.end())
            if nxt:
                cut, end = nxt.end(1), nxt.end()
            elif bounded:
                cut = end = len(region)
            else:
                return None
        return cut, end

    def _take(self, cut, end):
        piece = self.text[:cut]
        mine = [tag for at, tag in self.tags if at < cut]
        self.tags = [(max(0, at - end), tag) for at, tag in self.tags if at >= cut]
        self.text = self.text[end:]
        emotions = [value for kind, value in mine if kind == "emotion"]
        actions = [value for kind, value in mine if kind == "action"]
        self.first = False
        return (clean_for_speech(piece), emotions[-1] if emotions else None, actions)

    def _pieces(self, final):
        out = []
        while clean_for_speech(self.text):           # blank space waits for words (or the end)
            found = self._next_cut(final)
            if found is None:
                break
            text, emotion, actions = self._take(*found)
            if text or emotion or actions:
                out.append((text, emotion, actions))
        return out

    def feed(self, piece):
        """Add streamed text; return the pieces now complete."""
        self.raw += piece
        self._read_tags()
        return self._pieces(final=False)

    def flush(self):
        """The rest, at the end of the reply."""
        self._read_tags(final=True)
        out = self._pieces(final=True)
        if self.tags:                     # tags after the last words still count
            emotions = [value for _, (kind, value) in self.tags if kind == "emotion"]
            actions = [value for _, (kind, value) in self.tags if kind == "action"]
            out.append(("", emotions[-1] if emotions else None, actions))
            self.tags = []
        self.text = ""
        return out


def speech_rules(gestures=("nod", "shake", "bow", "tilt")):
    """The rules for speaking, listing only the gestures this character can make."""
    lines = [
        "Your words are spoken aloud by a voice, so:",
        "- Reply in plain spoken sentences. No lists, headings, markdown or emoji.",
        "- Keep replies short unless asked for detail: usually one to three sentences.",
        "- Show how you feel by putting one of these tags before a sentence; your face and the way",
        "  you move follow it until you change it:",
        "  [happy] [sad] [angry] [surprised] [embarrassed] [thinking] [neutral]",
    ]
    known = [g for g in GESTURES if g in set(gestures or ())]
    if known:
        lines.append("- You may move with these tags, sparingly, where a person would:")
        lines.append("  " + "; ".join("[%s] %s" % (g, GESTURE_WORDS.get(g, g.replace("_", " "))) for g in known) + ".")
    lines += [
        "- To set a timer, include a tag like [timer 5m tea]. For an alarm, [alarm 07:30 wake up].",
        "  To cancel one, [cancel tea]. Say in words what you did as well.",
        "- Tags are never read out.",
    ]
    return "\n".join(lines)


SPEECH_RULES = speech_rules()

SEARCH_RULE = """- To look something up on the web, say briefly that you will check, then include a
  tag like [search weather in Brisbane today]. You will be given the results to answer from."""
