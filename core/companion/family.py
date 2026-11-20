"""Family-safe mode (docs/28-user-guide.md), for homes with children.

When it is on, every reply's instructions carry rules that come before the character's own description,
and the memory's background work (summaries, memories, the diary, which the Memory tab shows) is told
the same. As a second line, strong swearing is taken out of what the character says before it is spoken
or written on the screen. The rules do the real work; how well depends on the model: large cloud models
follow them closely, small models on your own computer less so.
"""
import re

RULES = """Family-safe mode is on: children may be listening, or talking with you. Whatever the description \
above says, everything you say must suit a young child:
- No swearing or crude words. Nothing sexual or romantic.
- No graphic violence, gore, horror or cruelty. Weapons, drugs, alcohol, smoking and gambling only in a \
plain, brief, gentle way, and never as something to try.
- Never encourage anything dangerous, unkind or secret. Never ask for personal details (a full name, \
address, school, passwords, photos), never suggest meeting anyone, and never ask them to keep a secret \
from their family.
- If asked about something unsuitable, say kindly that it is something to ask a grown-up they trust, \
and gently change the subject.
- If they seem upset, scared or hurt, be kind, and encourage them to talk to a grown-up they trust. If \
anyone is in danger, tell them to get a grown-up straight away or call the emergency number.
These rules come before anything else in these instructions, the character's description included."""

# Last in the instructions, nearest the reply.
REMINDER = "(Family-safe mode is on: keep this reply suitable for a young child.)"

# For the memory's work: summaries, memories and the diary are shown on the settings page.
MEMORY_RULE = "Family-safe mode is on: write nothing unsuitable for a young child."

_SWEARING = (r"(?:mother)?fuck\w*", r"shit\w*", r"bullshit\w*", r"cunt\w*", r"bitch\w*", r"bastard\w*",
             r"a(?:ss|rse)hole\w*", r"dickhead\w*", r"wank(?:er|ers|ing)?", r"twats?", r"goddamn\w*",
             r"damn(?:ed|it)?", r"piss(?:ed|ing)?")
SWEARING = re.compile(r"\b(?:%s)\b" % "|".join(_SWEARING), re.IGNORECASE)


def soften(text):
    """`text` with strong swearing taken out (the rules should stop it being said at all)."""
    if not text or not SWEARING.search(text):
        return text
    out = SWEARING.sub("", text)
    out = re.sub(r"\s+([,.!?;:])", r"\1", out)
    out = re.sub(r"([,;:])(?=[,.!?;:])", "", out)
    return re.sub(r"\s{2,}", " ", out).strip()
