"""Text to phonemes for the on-device voice, with espeak-ng.

Piper voices (played by sherpa-onnx) are trained on espeak-ng's IPA
phonemes, clause by clause, with each clause's punctuation kept so the voice
pauses and rises where the text does. espeak-ng runs as a separate program
(GPL-3.0, from the operating system's packages); nothing of it is linked
into the device's own code.
"""
import re
import shutil
import subprocess

# A clause ends at punctuation followed by a space or the end; "3.5" and "e.g." stay whole.
CLAUSE = re.compile(r"(.+?)([.!?,;:…]+)(?=\s|$)|(.+?)$", re.S)
MAX_CHARS = 2000


class PhonemeError(Exception):
    pass


def espeak_path():
    return shutil.which("espeak-ng")


def clauses(text):
    """The text's clauses, each with the punctuation that ends it (or "")."""
    out = []
    for m in CLAUSE.finditer(text.strip()):
        words, mark = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), "")
        words = " ".join((words or "").split())
        if words:
            out.append((words, mark[:1].replace("…", ".")))
    return out


def phonemize(text, voice="en-us", espeak=None):
    """Phonemes for `text` as one string: each clause's IPA followed by its punctuation."""
    espeak = espeak or espeak_path()
    if not espeak:
        raise PhonemeError("espeak-ng is not installed")
    parts = clauses(text[:MAX_CHARS])
    if not parts:
        return ""
    try:
        run = subprocess.run([espeak, "-q", "--ipa", "-v", voice], input="\n".join(w for w, _ in parts),
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PhonemeError("espeak-ng did not run (%s)" % type(error).__name__)
    lines = [line.strip() for line in run.stdout.splitlines() if line.strip()]
    if run.returncode != 0 or not lines:
        raise PhonemeError("espeak-ng could not read the text")
    if len(lines) != len(parts):
        # espeak-ng divided the text differently; its phonemes are still right, only pauses are lost.
        return " ".join(lines)
    return " ".join(line + mark for line, (_, mark) in zip(lines, parts))
