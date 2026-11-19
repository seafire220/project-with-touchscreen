"""How a sentence is delivered: the mouth's shapes, and the movements that go with its meaning.

Before a sentence's sound plays, the core plans its performance:

  * its syllables, each with the mouth shape of its vowel (a, e, i, o, u), from the phonemes
    espeak-ng gives (or from the spelling, if espeak-ng is missing);
  * movements that go with the meaning (a nod on "yes", a shake on "no", a tilt at the end of a
    question, a wave on hello, a laugh on "haha"), each tied to the syllable it should start on,
    one or two before its word so that it lands on the word;
  * when the language model tagged no feeling at all, a feeling guessed from the words.

A mark then goes into the sentence's audio where each syllable is heard (`syllable_offsets` for a sentence
made whole, `SyllableMarks` for one that streams in); the stage changes the mouth's shape and starts each
movement as the marks arrive. If any of this fails, the stage still opens the mouth with the voice's
loudness and nods with its stresses, as before.

Where a syllable is heard comes from counting phonemes: in a voice's speech each lasts about as long as any
other (35 to 45 ms in the device's voice), so a syllable's place among the sentence's phonemes is close to
its place in time. Pauses at commas and full stops anchor the count. Measured against the exact timings of
the device's voice (`core/tools/measure_syllable_marks.py`), marks in a whole sentence land within 0.1 s of
their vowel four times in five.
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
STRESS = set("ˈˌ")              # marks that take no time
WORD_GAP = 1.2                  # the time between words, in phonemes
VOWEL_LEAD = 0.5                # a mark comes this many phonemes before its vowel, so the shape is on its way
CLAUSE_END = re.compile(r"[,;:—–.!?…]+(?=\s|$)")
SENTENCE_END = re.compile(r"[.!?…]")
WORD = re.compile(r"[^\W_](?:[^\W_]|['’-][^\W_])*")

# Movements by meaning: (gesture, strength, syllables before its word to start).
BIG = {"wave", "laugh", "shrug", "bow", "lean_in", "hands_on_hips"}
# How many syllables before its word a gesture starts, so that it lands on the word: from when the stage
# says it lands (its stroke) over a syllable's length in the device's voice (measured: 0.18 s on
# average); these are used when the stage has not said.
LEAD = {"wave": 2, "shrug": 2, "bow": 2}
SYLLABLE_SECONDS = 0.18


def lead_for(gesture, strokes=None):
    """Syllables before its word to start a gesture."""
    if strokes and gesture in strokes:
        try:
            return max(0, min(3, int(round(float(strokes[gesture]) / SYLLABLE_SECONDS))))
        except (TypeError, ValueError):
            pass
    return LEAD.get(gesture, 1)
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

def syllables_from_ipa(ipa):
    """A word's syllables from its phonemes: [(mouth shape, where its mark goes, in phonemes from the word's
    start)], and the word's length in phonemes. Two vowels in a row are one syllable (the diphthong in
    "day"); a vowel after a long one, or a third in a row, starts a new one ("doing", "going")."""
    out, run, pos = [], 0, 0.0           # run: vowels in a row so far
    for ch in ipa:
        if ch in IPA_SHAPES:
            if run == 0 or run == 2:         # a third vowel in a row starts a new syllable ("going": goʊ-ɪŋ)
                out.append((IPA_SHAPES[ch], max(0.0, pos - VOWEL_LEAD)))
                run = 1 if run == 2 else run
            run += 1
        elif ch == "ː":
            run = 0
        elif ch not in IPA_KEEP:
            run = 0
        if ch not in STRESS:
            pos += 1.0
    return out, pos


def shapes_from_ipa(ipa):
    """The mouth shapes of a word's syllables, from its phonemes."""
    return [shape for shape, _ in syllables_from_ipa(ipa)[0]]


def syllables_from_spelling(word):
    """A word's syllables guessed from its letters (when espeak-ng is missing), as `syllables_from_ipa`."""
    w = word.lower()
    if w.isdigit():
        return [("e", float(i)) for i in range(max(1, len(w)))], float(max(1, len(w)))
    groups = [(m.group(), m.start()) for m in re.finditer(r"[aeiouy]+", w)]
    if len(groups) > 1 and w.endswith("e") and not w.endswith(("le", "ee", "ye")) and groups[-1][0] == "e":
        groups = groups[:-1]                     # a silent final e: "make", "time"
    out = []
    for g, at in groups:
        if g.startswith("oo") or g.startswith("u"):
            shape = "u"
        elif g.startswith("ou"):
            shape = "a" if w.startswith("ou") or "out" in w else "u"
        else:
            shape = {"a": "a", "e": "e", "i": "i", "y": "i", "o": "o"}[g[0]]
        out.append((shape, max(0.0, at - VOWEL_LEAD)))
    return out or [("e", 0.0)], float(max(1, len(w)))


def shapes_from_spelling(word):
    """The mouth shapes of a word's syllables, guessed from its letters."""
    return [shape for shape, _ in syllables_from_spelling(word)[0]]


def word_syllables(words, voice="en-us"):
    """Each word's syllables and length (as `syllables_from_ipa`): from espeak-ng's phonemes, one word per
    line, when it is installed; else from the spelling."""
    espeak = phonemes.espeak_path()
    if espeak and words:
        try:
            run = subprocess.run([espeak, "-q", "--ipa", "-v", voice], input="\n".join(words), capture_output=True,
                                 text=True, timeout=10)
            lines = [line.strip() for line in run.stdout.splitlines() if line.strip()]
            if run.returncode == 0 and len(lines) == len(words):
                out = []
                for line, word in zip(lines, words):
                    found = syllables_from_ipa(line)
                    out.append(found if found[0] else syllables_from_spelling(word))
                return out
        except (OSError, subprocess.TimeoutExpired):
            pass
    return [syllables_from_spelling(w) for w in words]


def word_shapes(words, voice="en-us"):
    """Each word's syllable shapes."""
    return [[shape for shape, _ in found] for found, _ in word_syllables(words, voice)]


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

    def plan(self, text, available, asked=(), first=False, strokes=None):
        """The performance for one sentence, or None for no words:
        {"syllables": a mouth shape per syllable, "events": [[syllable, gesture, strength], ...],
         "timing": {"at": each syllable's place in phonemes, "length": the sentence's length in phonemes,
                    "clauses": [[first syllable, place, "end" after a full stop or "clause"], ...]}}."""
        words = WORD.findall(text)
        if not words:
            return None
        found = word_syllables(words, self.voice)
        starts, word_at, at, shapes, n, pos = [], [], [], [], 0, 0.0
        for sylls, length in found:
            starts.append(n)
            word_at.append(pos)
            for shape, offset in sylls:
                shapes.append(shape)
                at.append(round(pos + offset, 2))
            n += len(sylls)
            pos += length + WORD_GAP
        # Each clause after the first starts at the word after a clause-ending mark.
        clauses = []
        positions = [m.start() for m in WORD.finditer(text)]
        for mark in CLAUSE_END.finditer(text):
            following = next((i for i, p in enumerate(positions) if p > mark.start()), None)
            if following and all(c[0] != starts[following] for c in clauses):
                kind = "end" if SENTENCE_END.search(mark.group()) else "clause"
                clauses.append([starts[following], round(word_at[following], 2), kind])
        events = self._events(text, words, starts, set(available), set(asked), first, strokes)
        return {"syllables": "".join(shapes),
                "events": [[k, name, round(strength, 2)] for k, name, strength in events],
                "timing": {"at": at, "length": round(pos, 2), "clauses": clauses}}

    def _events(self, text, words, starts, available, asked, first, strokes=None):
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
            chosen.append((max(0, starts[index] - lead_for(gesture, strokes)), gesture, strength))
        if big:
            self.sentences_since_big = 0
        return sorted(chosen)


# --------------------------------------------------------------------------------------------------
# Where the syllables are heard
# --------------------------------------------------------------------------------------------------

STEP = 0.01                  # seconds per loudness reading
FLOOR_DB = -40.0             # quieter than this is silence (or 35 dB under the loudest sound, if higher)
GAP_DB = 5.0                 # a dip that stays within this of the silence...
GAP_MIN = 0.07               # ...for this many seconds may be a clause's pause
CLEAR_PAUSE = 0.2            # quiet this long is a pause, whether or not a clause ends there
PAUSE = 0.15                 # in sound that streams in, quiet this long is a pause
LONG_PAUSE = 0.3             # a pause this long more likely follows a full stop than a comma
SECONDS_PER_PHONEME = 0.047  # a voice's usual pace (the device's voice: 0.04 to 0.055)
PRIOR_PHONEMES = 10.0        # how much the usual pace counts against the pace heard so far
HOLD = 0.6                   # seconds of sound past a full stop, at least, before its pause is given up


def even_timing(count):
    """Timing for syllables known only by their number: evenly spaced."""
    return {"at": [3.0 * k for k in range(count)], "length": 3.0 * count, "clauses": []}


def _levels(samples, rate):
    """Loudness in dB, one reading every STEP seconds, lightly smoothed."""
    n = max(1, int(rate * STEP))
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        a = np.frombuffer(samples, dtype=np.int16) if isinstance(samples, (bytes, bytearray)) else np.asarray(samples)
        frames = len(a) // n
        if frames == 0:
            return []
        power = (a[:frames * n].astype(np.float64) ** 2).reshape(frames, n).mean(axis=1)
        db = np.where(power > 0, 10 * np.log10(np.maximum(power, 1e-12) / 32768.0 ** 2), -100.0)
        total = np.concatenate([[0.0], np.cumsum(db)])
        index = np.arange(frames)
        low = np.maximum(0, index - 2)
        return ((total[index + 1] - total[low]) / (index + 1 - low)).tolist()
    import array
    a = array.array("h", samples) if isinstance(samples, (bytes, bytearray)) else samples
    out = []
    for i in range(0, len(a) - n + 1, n):
        power = sum(s * s for s in a[i:i + n]) / n
        out.append(10 * math.log10(power / (32768.0 ** 2)) if power > 0 else -100.0)
    return [sum(out[max(0, i - 2):i + 1]) / len(out[max(0, i - 2):i + 1]) for i in range(len(out))]


def _match(expected, kinds, pauses, scale):
    """Clause starts to pauses, both in order, at the least total cost: [(clause, pause)]. A clause after a
    full stop nearly always has a pause before it; one after a comma often has none; and a voice may pause
    where no clause ends."""
    rows, cols = len(expected), len(pauses)
    cost = [[math.inf] * (cols + 1) for _ in range(rows + 1)]
    how = [[None] * (cols + 1) for _ in range(rows + 1)]
    cost[0] = [0.0] * (cols + 1)
    for b in range(1, rows + 1):
        miss = 2.0 if kinds[b - 1] == "end" else 1.0
        cost[b][0], how[b][0] = cost[b - 1][0] + miss, "miss"
        for k in range(1, cols + 1):
            best, step = cost[b][k - 1], "unused"
            if cost[b - 1][k] + miss < best:
                best, step = cost[b - 1][k] + miss, "miss"
            d = abs(pauses[k - 1] - expected[b - 1]) / scale
            if d < 2.5 and cost[b - 1][k - 1] + d < best:
                best, step = cost[b - 1][k - 1] + d, "match"
            cost[b][k], how[b][k] = best, step
    pairs, b, k = [], rows, cols
    while b > 0:
        step = how[b][k]
        if step == "match":
            pairs.append((b - 1, k - 1))
            b, k = b - 1, k - 1
        elif step == "miss":
            b -= 1
        else:
            k -= 1
    return pairs[::-1]


def syllable_offsets(samples, rate, timing):
    """Where each planned syllable is heard in a whole sentence's audio (sample offsets).

    The syllables' places among the sentence's phonemes are spread over the time the voice sounds; each
    clause that has a pause before it starts where the sound starts again."""
    at = list(timing["at"])
    count = len(at)
    if count == 0:
        return []
    n = max(1, int(rate * STEP))
    db = _levels(samples, rate)
    floor = max(FLOOR_DB, max(db) - 35) if db else FLOOR_DB
    voiced = [d > floor for d in db]
    if not any(voiced):
        frames = max(1, len(db))
        return [n * (frames * k // count) for k in range(count)]
    first = voiced.index(True)
    last = len(db) - 1 - voiced[::-1].index(True)
    # Dips that may be pauses.
    gaps, f = [], first
    while f <= last:
        if db[f] <= floor + GAP_DB:
            g = f
            while g <= last and db[g] <= floor + GAP_DB:
                g += 1
            if (g - f) * STEP >= GAP_MIN:
                gaps.append((f, g))
            f = g
        else:
            f += 1
    clauses = [c for c in timing.get("clauses", ()) if 0 < c[0] < count]
    total = max(float(timing.get("length") or 0.0), at[-1] + 1.0)
    span = last + 1 - first
    pairs = _match([first + c[1] / total * span for c in clauses], [c[2] for c in clauses],
                   [(a + b) / 2 for a, b in gaps], 0.1 * span + 15)
    matched = {g for _, g in pairs}
    pauses = [gap for i, gap in enumerate(gaps) if i in matched or (gap[1] - gap[0]) * STEP >= CLEAR_PAUSE]
    paused = set()
    for a, b in pauses:
        paused.update(range(a, b))
    sounding = [f for f in range(first, last + 1) if f not in paused]     # frames the clock runs in
    before = {f: k for k, f in enumerate(sounding)}
    anchors = [(0.0, 0.0)]
    for c, g in pairs:
        start = gaps[g][1]
        while start not in before and start <= last:
            start += 1
        if start in before and clauses[c][1] > anchors[-1][0]:
            anchors.append((clauses[c][1], float(before[start])))
    anchors.append((total, float(len(sounding))))
    out = []
    for u in at:
        k = 0
        while k + 2 < len(anchors) and anchors[k + 1][0] <= u:
            k += 1
        (u0, s0), (u1, s1) = anchors[k], anchors[k + 1]
        x = s0 + (u - u0) / max(1e-6, u1 - u0) * (s1 - s0)
        frame = sounding[min(len(sounding) - 1, max(0, math.ceil(x - 1e-9)))]
        out.append(max(frame, out[-1]) if out else frame)
    return [f * n for f in out]


class SyllableMarks:
    """Marks where a sentence's syllables are heard, as its audio streams in (when it does not come whole).

    A clock counts the sentence's phonemes at the voice's pace while it sounds. At each pause it decides
    which clause starts there (a long pause most likely after a full stop), restarts the count there and
    corrects the pace. At a full stop it waits for the pause, for a while, so it never runs on into the next
    sentence. Syllables due at once are marked as the latest of them.
    """

    def __init__(self, rate, timing, seconds_per_phoneme=SECONDS_PER_PHONEME):
        self.rate = rate
        self.at = list(timing["at"])
        self.count = len(self.at)
        self.clauses = [tuple(c) for c in timing.get("clauses", ()) if 0 < c[0] < self.count]
        self.n = max(1, int(rate * STEP))
        self.pace = self.usual = seconds_per_phoneme / STEP          # readings per phoneme
        self.pending = b""
        self.history = []
        self.loudest = -100.0
        self.started = False
        self.sounding = 0.0          # readings with sound since the start (pauses do not count)
        self.quiet = 0
        self.anchor = (0.0, 0.0)     # (place in phonemes, sounding readings)
        self.next = 0
        self.clause = -1             # the last clause the count restarted at

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
            mark = self._step(sum(self.history) / len(self.history))
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
        self.loudest = max(self.loudest, level)
        if level <= max(FLOOR_DB, self.loudest - 35):
            if self.started:
                self.quiet += 1
                pause = int(PAUSE / STEP)
                if self.quiet < pause:
                    self.sounding += 1           # a stop between sounds, part of the word
                elif self.quiet == pause:
                    self.sounding -= pause - 1   # a pause after all
            return None
        self.started = True
        if self.quiet >= int(PAUSE / STEP):
            self._resume(self.quiet * STEP)
        self.quiet = 0
        self.sounding += 1
        due = None
        while self.next < self.count:
            u0, s0 = self.anchor
            when = s0 + (self.at[self.next] - u0) * self.pace
            if when > self.sounding or self._waiting(when):
                break
            due, self.next = self.next, self.next + 1
        return due

    def _waiting(self, when):
        """At a full stop, wait for its pause (a voice nearly always makes one): for a while, or for half
        as long again as the sentence has taken, if longer (a slower voice than the count)."""
        upcoming = self.clauses[self.clause + 1] if self.clause + 1 < len(self.clauses) else None
        return (upcoming is not None and upcoming[2] == "end" and self.next >= upcoming[0]
                and self.sounding - when < max(HOLD / STEP, 0.5 * (when - self.anchor[1])))

    def _resume(self, pause):
        """Sound again after a pause: decide which clause starts now."""
        u0, s0 = self.anchor
        now = u0 + (self.sounding - s0) / self.pace
        scale = max(5.0, 0.3 * (now - u0))
        best, skipped = None, 0.0
        for i in range(self.clause + 1, len(self.clauses)):
            first, place, kind = self.clauses[i]
            cost = abs(place - now) / scale + skipped
            if (pause >= LONG_PAUSE) != (kind == "end"):
                cost += 0.5
            if best is None or cost < best[0]:
                best = (cost, i)
            skipped += 1.5 if kind == "end" else 0.5
        if best is None or best[0] > 2.5:
            return
        self.clause = best[1]
        first, place, _ = self.clauses[self.clause]
        if place > 0:
            self.pace = (self.sounding + self.usual * PRIOR_PHONEMES) / (place + PRIOR_PHONEMES)
        self.anchor = (place, self.sounding)
        self.next = first
