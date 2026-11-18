"""Tests for sentence performances: mouth shapes, movements that go with the meaning, feelings guessed
when no tag says, and where syllables are heard in the sound."""
import array
import asyncio
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import performance as pf  # noqa: E402
from companion.audio import Speaker  # noqa: E402

ALL = ["nod", "shake", "tilt", "wave", "laugh", "brow_flash", "shrug", "look_down", "lean_in"]


def planner():
    return pf.Planner(random.Random(4), expressiveness=10.0)      # every rule that applies fires


def names(plan):
    return [name for _, name, _ in plan["events"]]


class ShapesTest(unittest.TestCase):
    def test_vowels_become_mouth_shapes(self):
        self.assertEqual(pf.shapes_from_ipa("həlˈoʊ"), ["e", "o"])          # a diphthong is one syllable
        self.assertEqual(pf.shapes_from_ipa("dˈuːɪŋ"), ["u", "i"])           # a vowel after a long one is not
        self.assertEqual(pf.shapes_from_ipa("ɡˈoʊɪŋ"), ["o", "i"])           # nor is a third in a row
        self.assertEqual(pf.shapes_from_spelling("make"), ["a"])             # a silent e
        self.assertEqual(pf.shapes_from_spelling("cool"), ["u"])
        self.assertEqual(pf.shapes_from_spelling("42"), ["e", "e"])


class MeaningTest(unittest.TestCase):
    def test_the_meaning_brings_its_movement(self):
        self.assertEqual(names(planner().plan("Yes, I would love to.", ALL))[0], "nod")
        self.assertIn("shake", names(planner().plan("I don't think that will work.", ALL)))
        self.assertNotIn("shake", names(planner().plan("No problem at all.", ALL)), "a friendly no")
        self.assertIn("tilt", names(planner().plan("Do you like it?", ALL)))
        self.assertIn("laugh", names(planner().plan("Haha, that is funny.", ALL)))
        self.assertIn("look_down", names(planner().plan("I am sorry to hear that.", ALL)))

    def test_hello_waves_only_at_the_start_of_a_reply(self):
        self.assertIn("wave", names(planner().plan("Hello there, welcome back.", ALL, first=True)))
        self.assertNotIn("wave", names(planner().plan("I said hello to her.", ALL, first=True)))
        self.assertNotIn("wave", names(planner().plan("Hello there, welcome back.", ALL)))

    def test_a_movement_starts_a_syllable_or_two_before_its_word(self):
        plan = planner().plan("Well, I really think so.", ["brow_flash"])
        really = 2                                          # well(1) I(1) -> "really" starts at syllable 2
        self.assertEqual(plan["events"], [[really - 1, "brow_flash", 0.7]])

    def test_it_never_flails(self):
        p = planner()
        plan = p.plan("Haha, yes, hello, I really don't know, maybe, goodbye?", ALL, first=True)
        self.assertLessEqual(len(plan["events"]), 2)
        self.assertLessEqual(sum(n in pf.BIG for n in names(plan)), 1)
        self.assertTrue(all(n not in pf.BIG or n == "laugh" for n in names(p.plan("Bye now, goodbye!", ALL))),
                        "big movements wait a few sentences")
        asked = p.plan("Yes, sure, hello!", ALL, asked=["nod"])
        self.assertNotIn("nod", names(asked), "not what the model already asked for")
        self.assertLessEqual(len(asked["events"]), 1)
        self.assertEqual(names(planner().plan("Yes, of course.", ["tilt"])), [], "only movements it can make")


class FeelingTest(unittest.TestCase):
    def test_a_feeling_is_guessed_only_when_something_stands_out(self):
        self.assertEqual(pf.guess_feeling("That's wonderful news, congratulations!"), "happy")
        self.assertEqual(pf.guess_feeling("I'm so sorry to hear that."), "sad")
        self.assertEqual(pf.guess_feeling("Hmm, let me think about it."), "thinking")
        self.assertEqual(pf.guess_feeling("Wow, no way!"), "surprised")
        self.assertIsNone(pf.guess_feeling("The meeting is at three."))
        self.assertIsNone(pf.guess_feeling("I love it but I hate it."), "a tie says nothing")


RATE = 16000
# Two sentences, 19 and 13 phonemes long, said at the usual pace: 0.9 s, 0.4 s of quiet, then 0.6 s.
TIMING = {"at": [0.0, 6.0, 12.0, 19.5, 25.5], "length": 32.0, "clauses": [[3, 19.0, "end"]]}


def clauses_of_sound(lead=0.05, first=0.9, pause=0.4, second=0.6):
    """Speech-like sound: two stretches of a wavering tone, a pause between them. Returns the sound and
    where each stretch starts (in samples)."""
    def tone(seconds):
        return [int(9000 * math.sin(2 * math.pi * 220 * i / RATE) * (0.75 + 0.25 * math.sin(2 * math.pi * 5 * i / RATE)))
                for i in range(int(RATE * seconds))]
    samples = array.array("h", [0] * int(RATE * lead))
    a = len(samples)
    samples.extend(tone(first))
    samples.extend([0] * int(RATE * pause))
    b = len(samples)
    samples.extend(tone(second))
    samples.extend([0] * int(RATE * 0.1))
    return samples.tobytes(), a, b


def streamed(marks, sound, size=1000):
    out = []
    for i in range(0, len(sound), size):
        out += marks.feed(sound[i:i + size])
    return out + marks.flush()


def mark_times(out):
    """{syllable: seconds into the sound where its mark is}."""
    pos, times = 0, {}
    for x in out:
        if isinstance(x, tuple):
            times.setdefault(x[1], pos / 2 / RATE)
        else:
            pos += len(x)
    return times


class TimingTest(unittest.TestCase):
    def test_syllables_have_places_among_the_phonemes(self):
        found, length = pf.syllables_from_ipa("h\u0259l\u02c8o\u028a")       # "hello": stress marks take no time
        self.assertEqual(found, [("e", 0.5), ("o", 2.5)])
        self.assertEqual(length, 5.0)
        plan = planner().plan("Well, I made bread. And it rose.", ALL)
        timing = plan["timing"]
        self.assertEqual(len(timing["at"]), len(plan["syllables"]))
        self.assertEqual(timing["at"], sorted(timing["at"]))
        self.assertGreater(timing["length"], timing["at"][-1])
        self.assertEqual([(c[0], c[2]) for c in timing["clauses"]], [(1, "clause"), (4, "end")])
        self.assertIsNone(planner().plan("...", ALL))

    def test_syllables_are_spread_over_the_sound_and_a_clause_starts_after_its_pause(self):
        sound, a, b = clauses_of_sound()
        got = [o / RATE for o in pf.syllable_offsets(sound, RATE, TIMING)]
        want = [a / RATE, a / RATE + 6 / 19 * 0.9, a / RATE + 12 / 19 * 0.9,    # 0.9 s for phonemes 0 to 19
                b / RATE + 0.5 / 13 * 0.6, b / RATE + 6.5 / 13 * 0.6]         # 0.6 s for phonemes 19 to 32
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, delta=0.03)
        quiet = pf.syllable_offsets(b"\0\0" * RATE, RATE, TIMING)
        self.assertEqual(len(quiet), 5)
        self.assertEqual(quiet, sorted(quiet), "no sound at all: still one mark each, in order")

    def test_streamed_sound_gets_marks_in_order_and_keeps_every_byte(self):
        sound, a, b = clauses_of_sound()
        out = streamed(pf.SyllableMarks(RATE, TIMING), sound)
        self.assertEqual(b"".join(x for x in out if isinstance(x, bytes)), sound)
        marks = [x[1] for x in out if isinstance(x, tuple)]
        self.assertEqual(marks, sorted(marks))
        times = mark_times(out)
        self.assertAlmostEqual(times[0], a / RATE, delta=0.03)
        self.assertAlmostEqual(times[3], b / RATE, delta=0.06, msg="the clause after the pause starts with its sound")

    def test_a_slow_count_catches_up_at_the_pause(self):
        sound, a, b = clauses_of_sound()
        times = mark_times(streamed(pf.SyllableMarks(RATE, TIMING, seconds_per_phoneme=0.12), sound))
        self.assertNotIn(2, times, "the clock was too slow to reach the third syllable before the pause")
        self.assertAlmostEqual(times[3], b / RATE, delta=0.06)

    def test_a_fast_count_waits_at_the_full_stop(self):
        sound, a, b = clauses_of_sound()
        times = mark_times(streamed(pf.SyllableMarks(RATE, TIMING, seconds_per_phoneme=0.02), sound))
        self.assertGreaterEqual(times[3], b / RATE - 0.01, "not into the next sentence before its pause")

    @unittest.skipUnless(os.environ.get("COMPANION_TEST_VOICE"), "set COMPANION_TEST_VOICE to a voice folder")
    def test_the_devices_voice_gets_one_mark_per_planned_syllable(self):
        from companion.providers import LocalTTS
        tts = LocalTTS(os.environ["COMPANION_TEST_VOICE"])
        text = "Yes, of course! Hello there, how are you doing today?"
        plan = planner().plan(text, ALL)
        pcm = asyncio.run(tts.full(text))
        offsets = pf.syllable_offsets(pcm, tts.rate, plan["timing"])
        self.assertEqual(len(offsets), len(plan["syllables"]))
        self.assertEqual(offsets, sorted(offsets))
        self.assertTrue(all(0 <= o < len(pcm) // 2 for o in offsets))


class MarkerTest(unittest.TestCase):
    def test_a_marker_runs_when_the_sound_before_it_is_heard(self):
        heard = []

        async def chunks():
            yield b"\x10\x00" * 1600                   # 0.1 s at 16 kHz
            yield lambda: heard.append("mark")
            yield b"\x10\x00" * 1600

        async def go():
            speaker = Speaker(command=None, latency=0.0)
            await speaker.play(chunks(), 16000, lambda level: heard.append("level"))
        asyncio.run(go())
        i = heard.index("mark")
        self.assertEqual(heard[:i].count("level"), 5, "after the first 0.1 s (five 20 ms readings)")
        self.assertGreater(heard[i + 1:].count("level"), 3, "before the rest")


if __name__ == "__main__":
    unittest.main()
