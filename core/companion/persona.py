"""A character's persona from a few plain questions, for owners who would rather not write a prompt.

The answers become the same persona text owners can write by hand: second
person ("You are..."), headed sections, and a "## Greeting" section that
`characters.split_persona` reads. Empty answers are left out.
"""

# (field, heading in the persona, longest answer in characters)
FIELDS = (
    ("name", None, 60),
    ("personality", None, 600),
    ("story", "Your story", 1500),
    ("relationship", "You and the person you talk with", 600),
    ("likes", None, 400),
    ("dislikes", None, 400),
    ("speaking", "How you speak", 600),
    ("never", "Never", 600),
    ("greeting", "Greeting", 300),
)
NAMES = tuple(name for name, _, _ in FIELDS)

SPOKEN = ("Your replies are spoken aloud, so keep them short and natural: one to three sentences unless "
          "asked for more. No lists, headings or emoji.")


def clean(form):
    """The form's answers as trimmed text; raises ValueError for anything unusable."""
    if not isinstance(form, dict):
        raise ValueError("the form must be a set of answers")
    unknown = set(form) - set(NAMES)
    if unknown:
        raise ValueError("unknown questions: %s" % ", ".join(sorted(unknown)))
    out = {}
    for name, _, limit in FIELDS:
        value = form.get(name, "")
        if not isinstance(value, str):
            raise ValueError("%s must be text" % name)
        value = " ".join(value.split()) if name in ("name", "greeting") else value.strip()
        if len(value) > limit:
            raise ValueError("%s is too long (at most %d characters)" % (name, limit))
        out[name] = value
    if not out["name"]:
        raise ValueError("the character needs a name")
    return out


def build(form):
    """Persona text from the form's answers."""
    f = clean(form)
    name = f["name"]
    first = "You are %s, a character who lives on a small screen on the user's desk and talks with them by voice." % name
    parts = ["# %s" % name, (first + (" " + f["personality"] if f["personality"] else ""))]
    if f["story"]:
        parts += ["## Your story", f["story"]]
    if f["relationship"]:
        parts += ["## You and the person you talk with", f["relationship"]]
    if f["likes"] or f["dislikes"]:
        lines = []
        if f["likes"]:
            lines.append("You like: %s" % f["likes"])
        if f["dislikes"]:
            lines.append("You dislike: %s" % f["dislikes"])
        parts += ["## What you like and dislike", "\n".join(lines)]
    parts += ["## How you speak", (f["speaking"] + "\n\n" if f["speaking"] else "") + SPOKEN]
    if f["never"]:
        parts += ["## Never", f["never"]]
    if f["greeting"]:
        parts += ["## Greeting", f["greeting"]]
    return "\n\n".join(parts) + "\n"
