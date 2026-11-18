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
GESTURES = ("bounce", "bow", "brow_flash", "emphatic_nod", "hands_on_hips", "laugh", "lean_back", "lean_in", "look_away",
            "look_down", "nod", "shake", "shrug", "sigh", "surprise", "sway", "think", "tilt", "wave")

GESTURE_WORDS = {
    "nod": "nod", "shake": "shake your head", "bow": "bow", "tilt": "tilt your head, curious",
    "bounce": "bounce with joy", "emphatic_nod": "nod firmly", "laugh": "laugh", "sigh": "sigh",
    "sway": "sway", "look_away": "look away, shy", "look_down": "look down", "lean_in": "lean in",
    "lean_back": "lean back", "surprise": "start in surprise", "think": "look up, thinking",
    "hands_on_hips": "put your hands on your hips", "wave": "wave", "shrug": "shrug",
    "brow_flash": "raise your eyebrows",
}

TAG = re.compile(r"\[([^\[\]]{1,80})\]")
# A tag, or words between single asterisks ("*giggles*"), which may be a stage direction.
# A tag in brackets; words between single asterisks ("*giggles*"), in parentheses ("(smiles)") or in angle
# brackets ("<happy>"), any of which may be a stage direction.
TOKEN = re.compile(r"\[([^\[\]]{1,80})\]|(?<!\*)\*([^*\n]{1,60})\*(?!\*)|\(([^()\n]{1,40})\)"
                   r"|<\s*/?\s*([A-Za-z][^<>\n]{0,40})>")
OPENERS = {"[": ("]", 80), "(": (")", 40), "<": (">", 40)}
# Words a model may put before the feeling in a tag: "[emotion: happy]", "[mood happy]".
LABELS = {"emotion", "feeling", "mood", "expression", "face", "gesture", "action", "emote", "tone"}
# A feeling from emoji, when a sentence has no tag (emoji are never spoken).
EMOJI_FEELINGS = {
    "happy": "😊😄😁😀🙂😃😆🥰😍😘🤗😺✨🎉🥳👍💖💕❤♥😋",
    "sad": "😢😭😞😔☹🙁💔😿😥😓",
    "angry": "😠😡🤬💢😤",
    "surprised": "😮😲😯🤯😱😳❗",
    "embarrassed": "😅🙈☺😬",
    "thinking": "🤔🧐",
}
EMOJI_LOOKUP = {ch: feeling for feeling, chars in EMOJI_FEELINGS.items() for ch in chars}
SINGLE_STAR = re.compile(r"(?<!\*)\*(?!\*)")

# Stage directions models write on their own, though asked to use only the tags above ("[smile]",
# "*giggles softly*"): the feeling or gesture each stands for, or None to leave it unsaid.
DIRECTIONS = {
    "smile": ("emotion", "happy"), "grin": ("emotion", "happy"), "beam": ("emotion", "happy"),
    "wink": ("emotion", "happy"), "excited": ("emotion", "happy"), "cheerful": ("emotion", "happy"),
    "playful": ("emotion", "happy"), "teasing": ("emotion", "happy"), "happily": ("emotion", "happy"),
    "blush": ("emotion", "embarrassed"), "flustered": ("emotion", "embarrassed"), "nervous": ("emotion", "embarrassed"),
    "shy": ("emotion", "embarrassed"), "shyly": ("emotion", "embarrassed"),
    "frown": ("emotion", "sad"), "cry": ("emotion", "sad"), "sniffle": ("emotion", "sad"), "pout": ("emotion", "sad"),
    "upset": ("emotion", "sad"), "sadly": ("emotion", "sad"),
    "annoyed": ("emotion", "angry"), "huff": ("emotion", "angry"), "glare": ("emotion", "angry"),
    "grumble": ("emotion", "angry"),
    "shocked": ("emotion", "surprised"), "scared": ("emotion", "surprised"), "startled": ("emotion", "surprised"),
    "curious": ("emotion", "thinking"), "confused": ("emotion", "thinking"), "hmm": ("emotion", "thinking"),
    "calm": ("emotion", "neutral"),
    "giggle": ("gesture", "laugh"), "chuckle": ("gesture", "laugh"), "snicker": ("gesture", "laugh"),
    "gasp": ("gesture", "surprise"), "ponder": ("gesture", "think"), "lean": ("gesture", "lean_in"),
    "jump": ("gesture", "bounce"), "hop": ("gesture", "bounce"),
    "hum": None, "clap": None, "hug": None, "look": None, "stretch": None, "yawn": None, "pause": None,
    "whisper": None, "cough": None, "clear": None, "sniff": None, "blink": None, "stare": None, "gaze": None,
    "turn": None, "point": None, "hold": None, "reach": None, "smirk": ("emotion", "happy"),
    # Other words for the feelings, which models use in tags of their own ("[joyful]", "*nervously*").
    "joy": ("emotion", "happy"), "joyful": ("emotion", "happy"), "glad": ("emotion", "happy"),
    "delighted": ("emotion", "happy"), "proud": ("emotion", "happy"), "warm": ("emotion", "happy"),
    "amused": ("emotion", "happy"), "loving": ("emotion", "happy"), "affectionate": ("emotion", "happy"),
    "content": ("emotion", "happy"), "enthusiastic": ("emotion", "happy"),
    "sadness": ("emotion", "sad"), "sorrow": ("emotion", "sad"), "disappointed": ("emotion", "sad"),
    "worried": ("emotion", "sad"), "concerned": ("emotion", "sad"), "sympathetic": ("emotion", "sad"),
    "anger": ("emotion", "angry"), "mad": ("emotion", "angry"), "frustrated": ("emotion", "angry"),
    "irritated": ("emotion", "angry"), "grumpy": ("emotion", "angry"),
    "amazed": ("emotion", "surprised"), "astonished": ("emotion", "surprised"), "afraid": ("emotion", "surprised"),
    "fear": ("emotion", "surprised"), "shock": ("emotion", "surprised"),
    "embarrassment": ("emotion", "embarrassed"), "bashful": ("emotion", "embarrassed"),
    "sheepish": ("emotion", "embarrassed"), "anxious": ("emotion", "embarrassed"), "awkward": ("emotion", "embarrassed"),
    "thoughtful": ("emotion", "thinking"), "pensive": ("emotion", "thinking"), "puzzled": ("emotion", "thinking"),
    "wonder": ("emotion", "thinking"), "serious": ("emotion", "neutral"), "relaxed": ("emotion", "neutral"),
    "soft": None, "gentle": None, "quiet": None, "sarcastic": None, "slow": None,
}
_VOCABULARY = set(DIRECTIONS) | set(GESTURES) | set(EMOTIONS) | {"in", "back", "away", "down", "on", "hands", "hips"}
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


def _base(word):
    """A word's dictionary form, as far as the stage directions need ("giggles" -> "giggle")."""
    candidates = [word]
    if word.endswith("ies"):
        candidates.append(word[:-3] + "y")
    if word.endswith("es"):
        candidates.append(word[:-2])
    if word.endswith("s"):
        candidates.append(word[:-1])
    if word.endswith("ing"):
        candidates += [word[:-3], word[:-3] + "e", word[:-4]]
    if word.endswith("ed"):
        candidates += [word[:-2], word[:-1], word[:-3]]
    if word.endswith("ily"):
        candidates.append(word[:-3] + "y")          # "angrily"
    if word.endswith("ly"):
        candidates += [word[:-2], word[:-2] + "e"]  # "nervously", "gently"
    return next((c for c in candidates if c in _VOCABULARY), word)


def stage_direction(body, starred=False):
    """A stage direction the model wrote on its own: ("emotion", name) or ("action", gesture) for
    what it stands for, ("drop", None) to leave it unsaid, or None if it is not one (words between
    asterisks that are only emphasis, as in "that was *really* good")."""
    if not starred and re.fullmatch(r"\s*\d{1,3}\s*", body):
        return ("drop", None)                 # a footnote mark, "[1]"
    words = [_base(w) for w in re.findall(r"[a-z]+", body.lower())]
    while words and words[0] in LABELS:
        words = words[1:]                     # "[emotion: happy]"
    if not words or len(words) > 6 or re.search(r"\d", body):
        return None
    joined = " ".join(words)
    for g in GESTURES:
        if "_" in g and g.replace("_", " ") in joined:
            return ("action", {"kind": "gesture", "name": g})
    first = words[0]
    if first in EMOTIONS:
        return ("emotion", first)
    if first in GESTURES:
        return ("action", {"kind": "gesture", "name": first})
    if first in DIRECTIONS:
        meaning = DIRECTIONS[first]
        if meaning is None:
            return ("drop", None)
        if meaning[0] == "gesture":
            return ("action", {"kind": "gesture", "name": meaning[1]})
        return meaning
    return None if starred else ("drop", None)


def _emphasis(body):
    """One word that, between asterisks inside a sentence, is emphasis ("I'm *glad* you came", "let's *pause*")
    rather than an action ("*smiles*", "*giggles softly*")."""
    words = re.findall(r"[a-z]+", body.lower())
    return len(words) == 1 and not (words[0].endswith("s") and _base(words[0]) != words[0])


def clean_for_speech(text):
    text = MARKDOWN.sub("", text)
    text = EMOJI.sub("", text).replace("*", "")
    text = re.sub(r"\s+([.,!?;:…])", r"\1", text)       # where a dropped tag left a gap
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
        hold = len(raw)
        for opener, (closer, reach) in OPENERS.items():
            open_at = raw.rfind(opener)
            if open_at != -1 and closer not in raw[open_at:] and len(raw) - open_at < reach:
                hold = min(hold, open_at)                       # a tag may still be arriving
        stars = [m.start() for m in SINGLE_STAR.finditer(raw)]
        if len(stars) % 2 and len(raw) - stars[-1] < 60:
            hold = min(hold, stars[-1])                         # so may words between asterisks
        if final:
            hold = len(raw)
        ready, self.raw = raw[:hold], raw[hold:]
        pos = 0
        for m in TOKEN.finditer(ready):
            self.text += ready[pos:m.start()]
            pos = m.end()
            bracket, starred, round_, angle = m.groups()
            if bracket is not None:
                parsed = parse_tag(bracket) or stage_direction(bracket)
            elif angle is not None:
                parsed = parse_tag(angle) or stage_direction(angle)
            else:
                parsed = stage_direction(starred if starred is not None else round_, starred=True)
                if (parsed is not None and parsed[0] in ("emotion", "drop") and starred is not None
                        and _emphasis(starred) and self._mid_sentence()):
                    parsed = None            # a feeling word stressed mid-sentence is said, not acted
            if parsed is None:
                # Not a direction after all: emphasis keeps its words, a remark in parentheses its brackets.
                self.text += starred if starred is not None else m.group(0)
            elif parsed[0] != "drop":
                self.tags.append((len(self.text), parsed))
        self.text += ready[pos:]

    def _mid_sentence(self):
        """Whether the words so far stop inside a sentence."""
        ends = list(SENTENCE_END.finditer(self.text))
        tail = self.text[ends[-1].end():] if ends else self.text
        return bool(re.search(r"[^\W\d_]", tail))

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
        if not emotions:                     # no tag: an emoji, if the model used one, says the feeling
            found = [EMOJI_LOOKUP[ch] for ch in piece if ch in EMOJI_LOOKUP]
            if found:
                emotions = [max(set(found), key=found.count)]
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
        "- Tags are never read out. Use no other tags or stage directions, in brackets or asterisks.",
    ]
    return "\n".join(lines)


SPEECH_RULES = speech_rules()

SEARCH_RULE = """- To look something up on the web, say briefly that you will check, then include a
  tag like [search weather in Brisbane today]. You will be given the results to answer from."""
