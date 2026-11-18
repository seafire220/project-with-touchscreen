"""How a sentence is delivered: the mouth's shapes, and the movements that go with its meaning.

Before a sentence's sound plays, the core plans its performance:

  * its syllables, each with the mouth shape of its vowel (a, e, i, o, u), from the phonemes
    espeak-ng gives (or from the spelling, if espeak-ng is missing);
  * movements that go with the meaning (a nod on "yes", a shake on "no", a tilt at the end of a
    question, a wave on hello, a laugh on "haha"), each tied to the syllable it should start on,
    one or two before its word so that it lands on the word;
  * when the language model tagged no feeling at all, a feeling guessed from the words.

`SyllableMarks` then places a mark in the sentence's audio where each syllable is heard; the stage
changes the mouth's shape and starts each movement as the marks arrive. If any of this fails, the
stage still opens the mouth with the voice's loudness and nods with its stresses, as before.
"""
import math
import re
import shutil
import subprocess

from . import phonemes

SHAPES = "aeiou"
# Phoneme letters, by the mouth shape they make (the first vowel of a diphthong sets its shape).
IPA_SHAPES = {}
for shape, letters in (("a", "aɑæɐʌ"), ("e", "eɛəɜɘɚɝ"), ("i", "iɪɨyʏᵻ"), ("o", "oɔɒɵøœ"), ("u", "uʊɯɤʉ")):
    for letter in letters:
        IPA_SHAPES[letter] = shape
IPA_KEEP = set("ːˑ̯̃")          # marks that do not end a vowel
CLAUSE_END = re.compile(r"[,;:—–.!?…]+(?=\s|$)")
WORD = re.compile(r"[^\W_](?:[^\W_]|['’-][^\W_])*")

# Movements by meaning: (gesture, strength, syllables before its word to start).
BIG = {"wave", "laugh", "shrug", "bow", "lean_in", "hands_on_hips"}
LEAD = {"wave": 2, "shrug": 2, "bow": 2}
YES = {"yes", "yeah", "yep", "yup", "sure", "absolutely", "definitely", "exactly", "certainly", "indeed", "okay",
       "ok", "alright", "agreed", "correct", "totally", "right"}
NO = {"no", "nope", "nah", "not", "never", "don't", "doesn't", "didn't", "can't", "cannot", "won't", "isn't",
      "aren't", "wasn't", "weren't", "shouldn't", "wouldn't", "couldn't", "haven't", "hasn't", "nothing", "nobody",
      "neither", "nor"}
NO_BUT_FINE = ("no problem", "no worries", "not bad", "no doubt", "never mind")
UNSURE = ("maybe", "perhaps", "probably", "possibly", "i think", "i guess", "not sure", "i wonder", "kind of",
          "sort of", "who knows")
HELLO = ("hello", "hi", "hey", "hiya", "howdy", "good morning", "good afternoon", "good evening", "welcome back",
         "welcome")
BYE = ("goodbye", "bye", "good night", "goodnight", "see you", "take care", "talk soon", "talk later", "farewell")
LAUGH = ("haha", "hahaha", "hehe", "heh", "lol", "ha ha")
THANKS = ("thank you", "thanks", "thank")
SORRY = ("sorry", "apologies", "apologise", "apologize", "unfortunately")
STRONG = {"really", "so", "very", "totally", "absolutely", "completely", "super", "incredibly", "amazing", "awesome",
          "love", "best", "huge", "wonderful", "fantastic", "perfect", "seriously"}
COUNTING = {"first", "second", "third", "fourth", "next", "then", "finally", "lastly", "also"}

# Feelings guessed from words, when the language model tagged none.
FEELING_WORDS = {
    "happy": ("love great wonderful awesome amazing yay glad happy fun excited congratulations congrats fantastic "
              "perfect delighted lovely nice cool sweet cute adorable yummy delicious haha hehe welcome enjoy "
              "brilliant terrific hooray"),
    "sad": ("sorry sad miss unfortunately lost cry crying hurt lonely tired heartbroken depressed unhappy awful "
            "terrible rough sigh grief condolences"),
    "angry": "angry annoyed hate unfair stupid ugh furious mad irritating ridiculous outrageous rude",
    "surprised": "wow whoa woah omg incredible unbelievable seriously really",
    "embarrassed": "um uh er oops eep blush embarrassing flustered awkward shy",
    "thinking": "hmm hm maybe perhaps wonder guess think suppose possibly probably",
}
FEELING_PHRASES = {
    "happy": ("can't wait", "well done", "good job", "so happy", "that's great"),
    "sad": ("i'm sorry", "so sorry", "that's sad", "miss you"),
    "angry": ("how dare", "so annoying", "not fair"),
    "surprised": ("no way", "oh my", "what?!", "really?"),
    "embarrassed": ("oh no", "you think so", "stop it"),
    "thinking": ("let me think", "let's see", "i wonder", "not sure", "i think"),
}
FEELING_LOOKUP = {w: f for f, words in FEELING_WORDS.items() for w in words.split()}


# --------------------------------------------------------------------------------------------------
# Syllables and mouth shapes
# --------------------------------------------------------------------------------------------------

def shapes_from_ipa(ipa):
    """The mouth shapes of a word's syllables, from its phonemes. Two vowels in a row are one syllable (the
    diphthong in "day"); a vowel after a long one, or a third in a row, starts a new one ("doing", "going")."""
    out, run = [], 0                     # run: vowels in a row so far
    for ch in ipa:
        if ch in IPA_SHAPES:
            if run == 0 or run == 2:         # a third vowel in a row starts a new syllable ("going": goʊ-ɪŋ)
                out.append(IPA_SHAPES[ch])
                run = 1 if run == 2 else run
            run += 1
        elif ch == "ː":
            run = 0
        elif ch not in IPA_KEEP:
            run = 0
    return out


def shapes_from_spelling(word):
    """The mouth shapes of a word's syllables, guessed from its letters (when espeak-ng is missing)."""
    w = word.lower()
    if w.isdigit():
        return ["e"] * max(1, len(w))
    groups = re.findall(r"[aeiouy]+", w)
    if len(groups) > 1 and w.endswith("e") and not w.endswith(("le", "ee", "ye")) and groups[-1] == "e":
        groups = groups[:-1]                     # a silent final e: "make", "time"
    out = []
    for g in groups:
        if g.startswith("oo") or g.startswith("u"):
            out.append("u")
        elif g.startswith("ou"):
            out.append("a" if w.startswith("ou") or "out" in w else "u")
        else:
            out.append({"a": "a", "e": "e", "i": "i", "y": "i", "o": "o"}[g[0]])
    return out or ["e"]


def word_shapes(words, voice="en-us"):
    """Each word's syllable shapes: from espeak-ng's phonemes (one word per line) when it is installed."""
    espeak = phonemes.espeak_path()
    if espeak and words:
        try:
            run = subprocess.run([espeak, "-q", "--ipa", "-v", voice], input="\n".join(words), capture_output=True,
                                 text=True, timeout=10)
            lines = [line.strip() for line in run.stdout.splitlines() if line.strip()]
            if run.returncode == 0 and len(lines) == len(words):
                return [shapes_from_ipa(line) or shapes_from_spelling(word) for line, word in zip(lines, words)]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return [shapes_from_spelling(w) for w in words]


# --------------------------------------------------------------------------------------------------
# Feelings from words (when no tag says)
# --------------------------------------------------------------------------------------------------

def guess_feeling(text):
    """The feeling a sentence's words suggest, or None when nothing stands out."""
    lower = " %s " % " ".join(text.lower().split())
    scores = {}
    for feeling, phrases in FEELING_PHRASES.items():
        for phrase in phrases:
            if phrase in lower:
                scores[feeling] = scores.get(feeling, 0.0) + 1.5
    for word in WORD.findall(lower):
        feeling = FEELING_LOOKUP.get(word.replace("’", "'"))
        if feeling:
            scores[feeling] = scores.get(feeling, 0.0) + 1.0
    if text.rstrip().endswith("!"):
        for feeling in ("happy", "surprised", "angry"):
            if feeling in scores:
                scores[feeling] += 0.5
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best, score = ranked[0]
    if score < 1.0 or (len(ranked) > 1 and ranked[1][1] == score):
        return None
    return best


# --------------------------------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------------------------------

class Planner:
    """Plans each sentence of a conversation; remembers recent big movements so they are not overused."""

    def __init__(self, rng, expressiveness=1.0, voice="en-us"):
        self.rng = rng
        self.expressiveness = expressiveness
        self.voice = voice
        self.sentences_since_big = 99

    def plan(self, text, available, asked=(), first=False):
        """The performance for one sentence: {"syllables", "clauses", "events"}, or None for no words."""
        words = WORD.findall(text)
        if not words:
            return None
        shapes = word_shapes(words, self.voice)
        starts, n = [], 0
        for s in shapes:
            starts.append(n)
            n += len(s)
        syllables = "".join("".join(s) for s in shapes)
        # Clause starts: the syllable after each clause-ending mark.
        clauses = [0]
        positions = [m.start() for m in WORD.finditer(text)]
        for mark in CLAUSE_END.finditer(text):
            following = next((i for i, p in enumerate(positions) if p > mark.start()), None)
            if following is not None and starts[following] not in clauses:
                clauses.append(starts[following])
        events = self._events(text, words, starts, set(available), set(asked), first)
        return {"syllables": syllables, "clauses": clauses,
                "events": [[k, name, round(strength, 2)] for k, name, strength in events]}

    def _events(self, text, words, starts, available, asked, first):
        lower = [w.lower().replace("’", "'") for w in words]
        joined = " ".join(lower)
        found = []                                   # (priority, word index, gesture, strength)

        def word_at(phrase):
            parts = phrase.split()
            for i in range(len(lower) - len(parts) + 1):
                if lower[i:i + len(parts)] == parts:
                    return i
            return None

        def add(priority, index, gesture, strength, chance=1.0):
            if index is None or gesture not in available or gesture in asked:
                return
            if self.rng.random() < min(1.0, chance * self.expressiveness):
                found.append((priority, index, gesture, strength))

        question = text.rstrip().endswith("?")
        fine = any(p in joined for p in NO_BUT_FINE)
        for phrase in LAUGH:
            add(5, word_at(phrase), "laugh", 0.8, 0.9)
        if first:
            for phrase in HELLO:
                i = word_at(phrase)
                if i is not None and i <= 1:
                    add(5, i, "wave", 0.9, 0.85)
                    break
        for phrase in BYE:
            add(5, word_at(phrase), "wave", 0.8, 0.8)
        if lower[0] in YES or (fine and not question):
            add(4, 0, "nod", 0.7, 0.9)
        negation = next((i for i, w in enumerate(lower) if w in NO), None)
        if negation is not None and not fine and not question:
            add(4, negation, "shake", 0.55, 0.75)
        for phrase in THANKS:
            i = word_at(phrase)
            if i is not None:
                add(3, i, "nod", 0.6, 0.7)
                break
        for phrase in SORRY:
            i = word_at(phrase)
            if i is not None:
                add(3, i, "look_down", 0.5, 0.6)
                break
        for phrase in UNSURE:
            i = word_at(phrase)
            if i is not None:
                add(3, i, "shrug" if "shrug" in available and self.rng.random() < 0.4 else "tilt", 0.6, 0.6)
                break
        if question:
            add(2, max(0, len(lower) - 1), "tilt", 0.6, 0.65)
        strong = next((i for i, w in enumerate(words) if w.lower() in STRONG or (len(w) > 1 and w.isupper())), None)
        if strong is not None:
            add(2, strong, "brow_flash", 0.7, 0.55)
        counted = [i for i, w in enumerate(lower) if w in COUNTING]
        if len(counted) >= 2:
            for i in counted[:3]:
                add(1, i, "nod", 0.4, 0.8)
        elif text.rstrip().endswith("!") and not question:
            add(1, len(lower) - 1, "nod", 0.45, 0.4)

        # A budget: at most two movements a sentence (one if the model asked for one), one of them big, and big
        # ones only every few sentences, so the character never flails.
        found.sort(key=lambda f: (-f[0], f[1]))
        budget = 1 if asked else 2
        chosen, big, used = [], False, set()
        self.sentences_since_big += 1
        for priority, index, gesture, strength in found:
            if len(chosen) >= budget or index in used:
                continue
            if gesture in BIG:
                # Laughing goes with the joke, however recent the last big movement.
                if big or (self.sentences_since_big < 3 and gesture != "laugh"):
                    continue
                big = True
            used.add(index)
            chosen.append((max(0, starts[index] - LEAD.get(gesture, 1)), gesture, strength))
        if big:
            self.sentences_since_big = 0
        return sorted(chosen)


# --------------------------------------------------------------------------------------------------
# Where the syllables are heard
# --------------------------------------------------------------------------------------------------

STEP = 0.01          # seconds per loudness reading for finding syllables
FLOOR_DB = -40.0     # quieter than this is not a syllable
RISE_DB = 3.0        # a rise this much above the dip before it starts a syllable
MIN_GAP = 0.08       # seconds between syllables, at least
PAUSE = 0.15         # seconds of quiet that end a clause
STEADY = 0.3         # seconds of loud sound without a clear syllable before one is marked anyway


def _levels(samples, rate):
    """Loudness in dB, one reading every STEP seconds, lightly smoothed."""
    n = max(1, int(rate * STEP))
    out = []
    for i in range(0, len(samples) - n + 1, n):
        seg = samples[i:i + n]
        power = sum(s * s for s in seg) / n
        out.append(10 * math.log10(power / (32768.0 ** 2)) if power > 0 else -100.0)
    return [sum(out[max(0, i - 2):i + 1]) / len(out[max(0, i - 2):i + 1]) for i in range(len(out))]


def syllable_offsets(samples, rate, count):
    """Where `count` syllables start in a whole sentence's audio (sample offsets), from its loudness:
    the `count` most prominent peaks, each starting at the dip before it."""
    import array
    if count <= 0:
        return []
    db = _levels(array.array("h", samples) if isinstance(samples, (bytes, bytearray)) else samples, rate)
    if not db:
        return [0] * count
    peaks = []
    for i in range(1, len(db) - 1):
        if db[i] >= db[i - 1] and db[i] > db[i + 1] and db[i] > FLOOR_DB:
            left = min(db[max(0, i - 25):i + 1])
            right = min(db[i:i + 26])
            prominence = db[i] - max(left, right)
            if prominence >= 1.0:
                dip = i                      # back down the rise to where it starts (not across a quiet stretch)
                while dip > 0 and db[dip - 1] < db[dip] and i - dip < 25:
                    dip -= 1
                peaks.append((prominence, i, dip))
    peaks.sort(key=lambda p: -p[0])
    chosen = []
    for prominence, i, dip in peaks:
        if all(abs(i - j) * STEP >= MIN_GAP for _, j, _ in chosen):
            chosen.append((prominence, i, dip))
        if len(chosen) == count:
            break
    starts = sorted(dip for _, _, dip in chosen)
    # Fewer peaks than syllables: share out the rest in the longest stretches between them.
    end = len(db)
    while len(starts) < count:
        edges = [0] + starts + [end]
        gaps = [(edges[k + 1] - edges[k], k) for k in range(len(edges) - 1)]
        size, k = max(gaps)
        starts.append(edges[k] + size // 2)
        starts.sort()
    n = max(1, int(rate * STEP))
    return [s * n for s in starts]


class SyllableMarks:
    """Marks where a sentence's syllables are heard, as its audio streams in (when it does not come whole).

    A syllable starts where the loudness rises clearly after a dip. The count is kept to the sentence's
    planned syllables, and a pause snaps it to the nearest clause start, so a miscount never drifts far.
    """

    def __init__(self, rate, count, clauses=(0,)):
        self.rate = rate
        self.count = count
        self.clauses = list(clauses) or [0]
        self.n = max(1, int(rate * STEP))
        self.pending = b""
        self.history = []
        self.next = 0
        self.low, self.high, self.rising = 1e9, -1e9, False
        self.since = 99.0
        self.quiet = 0.0
        self.paused = False
        self.loud = 0.0          # loud sound since the last mark
        self.marked = False

    def feed(self, chunk):
        """Audio in; audio out, with ("syllable", k) marks between the bytes where syllable k starts."""
        import array
        out, start = [], 0
        data = self.pending + chunk
        usable = len(data) - len(data) % (2 * self.n)
        for pos in range(0, usable, 2 * self.n):
            frame = array.array("h", data[pos:pos + 2 * self.n])
            power = sum(s * s for s in frame) / self.n
            level = 10 * math.log10(power / (32768.0 ** 2)) if power > 0 else -100.0
            self.history = (self.history + [level])[-3:]
            level = sum(self.history) / len(self.history)
            self.since += STEP
            mark = self._step(level)
            if mark is not None:
                out.append(data[start:pos])
                out.append(("syllable", mark))
                start = pos
        out.append(data[start:usable])
        self.pending = data[usable:]
        return [x for x in out if x != b""]

    def flush(self):
        rest, self.pending = self.pending, b""
        return [rest] if rest else []

    def _step(self, level):
        if level < FLOOR_DB:
            self.quiet += STEP
            if self.quiet >= PAUSE and not self.paused:
                self.paused = True
                self._snap()
        else:
            self.quiet, self.paused = 0.0, False
            self.loud += STEP
            # The first sound is the first syllable; and a voice too even to show its syllables still
            # gets one now and then, so the mouth and the movements keep going.
            if self.next < self.count and (self.next == 0 and not self.marked or self.loud >= STEADY):
                return self._mark(level)
        if not self.rising:
            self.low = min(self.low, level)
            if level > self.low + RISE_DB and level > FLOOR_DB and self.since >= MIN_GAP and self.next < self.count:
                return self._mark(level)
        else:
            self.high = max(self.high, level)
            if level < self.high - RISE_DB:
                self.rising, self.low = False, level
        return None

    def _mark(self, level):
        self.rising, self.high, self.since, self.loud, self.marked = True, level, 0.0, 0.0, True
        k, self.next = self.next, self.next + 1
        return k

    def _snap(self):
        """A pause ends a clause: the next syllable is the first of the clause nearest the count."""
        near = min(self.clauses, key=lambda c: (abs(c - self.next), -c))
        if abs(near - self.next) <= 3:
            self.next = near
        else:
            ahead = [c for c in self.clauses if c > self.next]
            if ahead:
                self.next = ahead[0]
