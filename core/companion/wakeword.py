"""Saying the character's name starts listening, as the button does (docs/28-user-guide.md).

Keyword spotting on the device, with sherpa-onnx: a small speech model (zipformer, 3.3 million
parameters, Apache-2.0, trained on GigaSpeech by the k2-fsa project) listens for words given as text, so
any name works without training. It listens only while the character is idle and the microphone is on;
nothing it hears is kept or sent anywhere.

By default it listens for "hey", "hi" and "hello" before the character's first name; the owner can
choose other words instead. How readily it hears them is a setting (docs/28-user-guide.md, measured in
core/tools/wake_check.py).
"""
import glob
import os
import re
import tempfile
import unicodedata

try:
    import numpy as np
except ImportError:
    np = None

RATE = 16000
# How readily it hears the words: (threshold, boost). A lower threshold and a higher boost hear them more
# easily, and start by mistake more often. Chosen with core/tools/wake_check.py (docs/28-user-guide.md):
# on 240 synthetic phrases, "hey/hi/hello Mika" was heard 57%, 69% and 72% of the time, and in 21 minutes
# of everyday speech only "hello Micah" (said almost the same) woke it, at each setting.
SENSITIVITY = {"low": (0.25, 1.5), "normal": (0.1, 2.0), "high": (0.05, 3.0)}
GREETINGS = ("HEY", "HI", "HELLO")
# Words a recogniser may write for a greeting run together with a name ("Hamika", "A Mika").
_LEAD_INS = {"HEY", "HI", "HELLO", "HAY", "HE", "A", "AH", "OH", "OK", "OKAY", "HIYA", "YO", "HELLO'"}


class WakeWordError(Exception):
    pass


def clean(text):
    """Upper-case letters, apostrophes and single spaces, accents taken off (as the model was trained)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    text = re.sub(r"[^A-Z' ]+", " ", text)
    return " ".join(text.split())


def phrases(name, phrase=""):
    """The words to listen for: the owner's own, or a greeting and the character's first name."""
    own = clean(phrase)
    if own:
        return [own]
    first = clean(name).split(" ")[0] if clean(name) else ""
    if not first:
        return []
    return ["%s %s" % (greeting, first) for greeting in GREETINGS]


def after_wake(transcript, words):
    """What was said after the wake words, in a transcript of the whole utterance ("Hey Mika, what time is
    it?" gives "what time is it?"); "" if only the wake words were said."""
    import difflib
    names = {w.split(" ")[-1] for w in (clean(x) for x in words) if w}
    tokens = (transcript or "").split()
    plain = [clean(t) for t in tokens]
    cut = 0
    for i, word in enumerate(plain[:4]):
        if not word:
            continue
        if any(difflib.SequenceMatcher(None, word, name).ratio() >= 0.6 or (len(word) > len(name) and word.endswith(name))
               for name in names):
            cut = i + 1
            break
    if not cut:
        while cut < len(plain) and cut < 2 and plain[cut] in _LEAD_INS:
            cut += 1
    rest = " ".join(tokens[cut:]).lstrip(",.!?;: ").strip()
    return rest if len(rest.split()) >= 2 or (rest and rest[-1:] == "?") else ""


def model_files(folder):
    """The model's files in `folder`, or None if it is not there (the 8-bit model is preferred)."""
    def pick(kind):
        found = sorted(glob.glob(os.path.join(folder, kind + "*.int8.onnx"))) or \
            sorted(glob.glob(os.path.join(folder, kind + "*.onnx")))
        return found[0] if found else None
    files = {"encoder": pick("encoder"), "decoder": pick("decoder"), "joiner": pick("joiner"),
             "tokens": os.path.join(folder, "tokens.txt"), "bpe": os.path.join(folder, "bpe.model")}
    if not all(files.values()) or not all(os.path.isfile(p) for p in files.values()):
        return None
    return files


def word_pieces(words, files):
    """Each phrase as the model's word pieces (its BPE vocabulary), or [] for one it cannot spell."""
    try:
        import sentencepiece
    except ImportError:
        raise WakeWordError("the wake word needs sentencepiece, which is not installed")
    with open(files["tokens"], encoding="utf-8") as f:
        known = {line.split()[0] for line in f if line.strip()}
    model = sentencepiece.SentencePieceProcessor()
    model.load(files["bpe"])
    out = []
    for word in words:
        pieces = model.encode(word, out_type=str)
        out.append(pieces if pieces and all(p in known for p in pieces) else [])
    return out


class WakeWord:
    """Listens for some words in 16 kHz 16-bit sound, fed 20 ms at a time."""

    def __init__(self, folder, words, sensitivity="normal", threads=1):
        try:
            import sherpa_onnx
        except ImportError:
            raise WakeWordError("the wake word needs sherpa-onnx, which is not installed")
        if np is None:
            raise WakeWordError("the wake word needs numpy")
        files = model_files(folder)
        if files is None:
            raise WakeWordError("the wake-word model is not on this device")
        words = [clean(w) for w in words if clean(w)]
        if not words:
            raise WakeWordError("there are no words to listen for")
        pieces = word_pieces(words, files)
        threshold, boost = SENSITIVITY.get(sensitivity, SENSITIVITY["normal"])
        lines = ["%s @%s" % (" ".join(p), w.replace(" ", "_")) for p, w in zip(pieces, words) if p]
        if not lines:
            raise WakeWordError("these words cannot be listened for")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n".join(lines) + "\n")
            keywords = f.name
        try:
            self.spotter = sherpa_onnx.KeywordSpotter(
                tokens=files["tokens"], encoder=files["encoder"], decoder=files["decoder"], joiner=files["joiner"],
                keywords_file=keywords, num_threads=threads, keywords_score=boost, keywords_threshold=threshold,
                num_trailing_blanks=1, max_active_paths=4, provider="cpu")
        except Exception as error:
            raise WakeWordError("the wake-word model could not be loaded (%s)" % error)
        finally:
            os.unlink(keywords)
        self.words = words
        self.stream = self.spotter.create_stream()

    def feed(self, pcm):
        """Add some sound. Returns the words heard (as text), or None."""
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.stream.accept_waveform(RATE, samples)
        heard = None
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            result = self.spotter.get_result(self.stream)
            if result:
                heard = result.replace("_", " ").title()
                self.spotter.reset_stream(self.stream)
        return heard

    def reset(self):
        """Forget what it has heard so far (after it heard the words, or the character spoke)."""
        self.stream = self.spotter.create_stream()
