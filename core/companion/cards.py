"""Character cards: the personality files many AI-companion apps share, as PNG pictures or JSON.

A card holds a character's name, description, personality, situation, greeting and example dialogue
as JSON (the "chara_card_v3" and "chara_card_v2" layouts, or the older flat one). In a PNG it sits in
a text chunk named "ccv3" or "chara", base64-encoded. This turns a card into a persona for the device:
in the second person, with the spoken-reply rule, the example dialogue as a guide to manner, and a
short greeting the voice can say. A card's own "system prompt" and "post-history instructions" are
left out: they are written for chat apps and would fight the device's own rules.

Only the card's text is used, as the character's persona; nothing in it is run.
"""
import base64
import json
import re
import struct
import zlib

from .persona import SPOKEN
from .speech_text import clean_for_speech

MAX_CARD = 20 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
MAX_CHUNKS = 4096
PERSONA_BUDGET = 12000      # characters: the persona goes to the language model with every reply
GREETING_LIMIT = 300
PNG = b"\x89PNG\r\n\x1a\n"


class CardError(ValueError):
    pass


def png_texts(data):
    """The PNG's text chunks (tEXt, zTXt, iTXt) as {keyword (lower case): text}."""
    out, pos, count = {}, 8, 0
    while pos + 8 <= len(data) and count < MAX_CHUNKS:
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        count += 1
        if kind == b"IEND":
            break
        try:
            if kind == b"tEXt":
                key, _, text = body.partition(b"\0")
                out[key.decode("latin-1").lower()] = text.decode("latin-1")
            elif kind == b"zTXt":
                key, _, rest = body.partition(b"\0")
                out[key.decode("latin-1").lower()] = _inflate(rest[1:]).decode("latin-1")
            elif kind == b"iTXt":
                key, _, rest = body.partition(b"\0")
                compressed, rest = rest[0], rest[2:]
                _, _, rest = rest.partition(b"\0")          # language
                _, _, text = rest.partition(b"\0")          # translated keyword
                out[key.decode("latin-1").lower()] = (_inflate(text) if compressed else text).decode("utf-8")
        except (zlib.error, UnicodeDecodeError, IndexError):
            continue
    return out


def _inflate(data):
    d = zlib.decompressobj()
    out = d.decompress(data, MAX_JSON * 2)
    if d.unconsumed_tail:
        raise zlib.error("too large")
    return out


def read_card(data):
    """A card from PNG or JSON bytes, as plain fields. Raises CardError."""
    if len(data) > MAX_CARD:
        raise CardError("the card is too large")
    if data[:8] == PNG:
        texts = png_texts(data)
        raw = texts.get("ccv3") or texts.get("chara")
        if raw is None:
            raise CardError("this picture holds no character card")
        try:
            text = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise CardError("the card in this picture could not be read")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise CardError("this is neither a PNG nor a JSON character card")
    if len(text) > MAX_JSON:
        raise CardError("the card is too large")
    try:
        card = json.loads(text)
    except ValueError:
        raise CardError("the card's contents could not be read")
    return normalise(card)


def normalise(card):
    if not isinstance(card, dict):
        raise CardError("this is not a character card")
    data = card["data"] if isinstance(card.get("data"), dict) else card

    def field(name):
        value = data.get(name)
        return value.strip() if isinstance(value, str) else ""
    name = " ".join(field("name").split())[:60]
    if not name:
        raise CardError("the card has no name")
    book = data.get("character_book") if isinstance(data.get("character_book"), dict) else {}
    lore = []
    for entry in book.get("entries") or []:
        if isinstance(entry, dict) and entry.get("enabled", True) is not False:
            content = entry.get("content")
            if isinstance(content, str) and content.strip():
                lore.append(content.strip())
    greetings = [g.strip() for g in data.get("alternate_greetings") or [] if isinstance(g, str) and g.strip()]
    tags = [t for t in data.get("tags") or [] if isinstance(t, str)][:20]
    return {"name": name, "description": field("description"), "personality": field("personality"),
            "scenario": field("scenario"), "first_mes": field("first_mes"), "mes_example": field("mes_example"),
            "alternate_greetings": greetings, "lore": lore, "creator": field("creator"), "tags": tags}


def _fill(text, name, user="the user"):
    text = re.sub(r"\{\{\s*char\s*\}\}|<bot>", name, text, flags=re.I)
    text = re.sub(r"\{\{\s*user\s*\}\}|<user>", user, text, flags=re.I).strip()
    return re.sub(r"(^|[.!?…]\s+)" + re.escape(user), lambda m: m.group(1) + user[:1].upper() + user[1:], text)


def _examples(text, name):
    """Example dialogue as lines of "Person:" and the character's name."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.upper() == "<START>":
            continue
        line = re.sub(r"^(\{\{\s*user\s*\}\}|<user>)\s*:", "Person:", line, flags=re.I)
        line = re.sub(r"^(\{\{\s*char\s*\}\}|<bot>)\s*:", name + ":", line, flags=re.I)
        lines.append(_fill(line, name, "the person"))
    return "\n".join(lines)


def spoken_greeting(text, name):
    """A greeting the voice can say: its spoken words without the narration, a couple of sentences."""
    user = r"(?:\{\{\s*user\s*\}\}|<user>)"
    text = re.sub(r"\s*,\s*" + user + r"(?=\s*[!?.])", "", text, flags=re.I)                  # "Hello, {{user}}!"
    text = re.sub(r"(^|[\"“.!?…]\s*)" + user + r"\s*[,!]\s*(\w)",                              # "{{user}}, you're"
                  lambda m: m.group(1) + m.group(2).upper(), text, flags=re.I)
    text = _fill(text, name, "you")
    quoted = re.findall(r"[\"“]([^\"“”]{2,})[\"”]", text)
    if quoted:
        text = " ".join(quoted)
    text = re.sub(r"\*[^*]*\*|\[[^\]]*\]|\([^)]*\)", " ", text)
    text = clean_for_speech(text)
    sentences = re.findall(r"[^.!?…]+[.!?…]+[\"'”’]*|[^.!?…]+$", text)
    out, count = "", 0
    for sentence in sentences:
        if out and (len(out) + len(sentence) > GREETING_LIMIT or (count >= 2 and len(out) >= 60)):
            break
        out = (out + " " + sentence.strip()).strip()
        count += 1
    return out[:GREETING_LIMIT].strip()


def _trim(text, room):
    if len(text) <= room:
        return text
    cut = text[:max(0, room)]
    end = max(cut.rfind("\n"), cut.rfind(". "))
    return (cut[:end + 1] if end > room * 0.6 else cut).rstrip() + " [...]"


def to_persona(card):
    """The device's persona for a card: (persona text, greeting)."""
    name = card["name"]
    first = ("You are %s, a character who lives on a small screen on the user's desk and talks with them "
             "by voice. Stay in character." % name)
    sections = [("Who you are", _fill(card["description"], name)), ("Your personality", _fill(card["personality"], name)),
                ("The situation", _fill(card["scenario"], name))]
    lore = "\n".join("- " + _fill(e, name) for e in card["lore"])
    examples = _examples(card["mes_example"], name)
    room = PERSONA_BUDGET
    parts = ["# %s" % name, first]
    for heading, text in sections:
        if text:
            text = _trim(text, room)
            parts += ["## " + heading, text]
            room -= len(text)
    if lore and room > 400:
        lore = _trim(lore, room - 200)
        parts += ["## Things you know", lore]
        room -= len(lore)
    if examples and room > 400:
        parts += ["## How you talk (examples of your manner, not of how long to speak)", _trim(examples, room - 200)]
    parts += ["## How you speak", SPOKEN]
    greeting = spoken_greeting(card["first_mes"] or (card["alternate_greetings"] or [""])[0], name)
    if greeting:
        parts += ["## Greeting", greeting]
    return "\n\n".join(parts) + "\n", greeting
