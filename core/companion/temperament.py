"""A character's temperament: how lively (calm to lively) and how expressive (reserved to expressive).

Each is 0 to 1 (0.5 usual), set on the settings page with two sliders, and suggested from the
personality text when a character is made or a card imported (a shy character moves less and looks
away; a bubbly one gestures more). The stage turns them into how lively the idle motion is, how often
and how big the character's own gestures are, and which idle actions suit it; the speech planner into
how many gestures go with the words.
"""
import re

DEFAULT = {"liveliness": 0.5, "expressiveness": 0.5}

LIVELY = ("energetic", "bubbly", "cheerful", "excitable", "hyper", "hyperactive", "playful", "outgoing", "loud",
          "enthusiastic", "peppy", "spirited", "lively", "boisterous", "restless", "sporty", "mischievous", "chaotic",
          "spunky", "upbeat", "vivacious", "fidgety", "impulsive", "adventurous")
CALM = ("calm", "quiet", "gentle", "serene", "soft-spoken", "softspoken", "laid-back", "laidback", "sleepy", "lazy",
        "mellow", "composed", "patient", "relaxed", "tranquil", "stoic", "lethargic", "placid", "unhurried", "dignified",
        "elegant", "graceful")
EXPRESSIVE = ("dramatic", "expressive", "animated", "theatrical", "emotional", "flamboyant", "passionate", "bubbly",
              "excitable", "outgoing", "affectionate", "touchy", "silly", "goofy", "over-the-top", "sassy", "flirty",
              "demonstrative", "warm", "cheerful")
RESERVED = ("reserved", "shy", "stoic", "cold", "aloof", "introverted", "introvert", "timid", "serious", "deadpan",
            "withdrawn", "awkward", "bashful", "quiet", "stern", "distant", "cool", "guarded", "taciturn", "formal",
            "tsundere", "kuudere", "dandere")


def _count(words, text):
    return sum(len(re.findall(r"\b%s\b" % re.escape(w), text)) for w in words)


def suggest(text):
    """Starting values from a personality's text ({"liveliness", "expressiveness"}, 0 to 1)."""
    text = (text or "").lower()
    lively, calm = _count(LIVELY, text), _count(CALM, text)
    loud, reserved = _count(EXPRESSIVE, text), _count(RESERVED, text)

    def lean(up, down):
        if up == down:
            return 0.5
        return round(max(0.15, min(0.85, 0.5 + 0.15 * (up - down))), 2)

    return {"liveliness": lean(lively, calm), "expressiveness": lean(loud, reserved)}


def clean(values):
    """A temperament from the settings page: both values, 0 to 1."""
    out = dict(DEFAULT)
    for key in DEFAULT:
        try:
            out[key] = round(max(0.0, min(1.0, float((values or {}).get(key, DEFAULT[key])))), 2)
        except (TypeError, ValueError):
            pass
    return out


def for_stage(values):
    """The stage's multipliers, 1 usual: (energy, expressiveness), each 0.6 to 1.4."""
    v = clean(values)
    return round(0.6 + 0.8 * v["liveliness"], 2), round(0.6 + 0.8 * v["expressiveness"], 2)
