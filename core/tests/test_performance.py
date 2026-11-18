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


def bumps(count, rate=16000, on=0.12, off=0.08, lead=0.05):
    """Speech-like sound: `count` loud tones, each with a quiet gap before it."""
    samples = array.array("h", [0] * int(rate * lead))
    starts = []
    for _ in range(count):
        starts.append(len(samples))
        samples.extend(int(12000 * math.sin(2 * math.pi * 220 * i / rate) * math.sin(math.pi * i / (rate * on)))
                       for i in range(int(rate * on)))
        samples.extend([0] * int(rate * off))
    return samples.tobytes(), starts


class ShapesTest(unittest.TestCase):
    def test_vowels_become_mouth_shapes(self):
        self.assertEqual(pf.shapes_from_ipa("həlˈoʊ"), ["e", "o"])          # a diphthong is one syllable
        self.assertEqual(pf.shapes_from_ipa("dˈuːɪŋ"), ["u", "i"])           # a vowel after a long one is not
        self.assertEqual(pf.shapes_from_ipa("ɡˈoʊɪŋ"), ["o", "i"])           # nor is a third in a row
        self.assertEqual(pf.shapes_from_spelling("make"), ["a"])             # a silent e
        self.assertEqual(pf.shapes_from_spelling("cool"), ["u"])
        self.assertEqual(pf.shapes_from_spelling("42"), ["e", "e"])

    def test_a_plan_has_a_shape_for_every_syllable_and_its_clauses(self):
        plan = planner().plan("Well, I made bread, and it rose.", ALL)
        self.assertTrue(set(plan["syllables"]) <= set("aeiou"))
        self.assertEqual(plan["clauses"][0], 0)
        self.assertEqual(len(plan["clauses"]), 3, plan)
        self.assertIsNone(planner().plan("...", ALL))


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


class SyllableTest(unittest.TestCase):
    def test_syllables_are_placed_at_their_sounds(self):
        sound, starts = bumps(6)
        offsets = pf.syllable_offsets(sound, 16000, 6)
        self.assertEqual(len(offsets), 6)
        for got, want in zip(offsets, starts):
            self.assertLess(abs(got - want), 16000 * 0.06, (got, want))
        self.assertEqual(len(pf.syllable_offsets(sound, 16000, 9)), 9, "more planned than heard: shared out")
        self.assertEqual(pf.syllable_offsets(sound, 16000, 9), sorted(pf.syllable_offsets(sound, 16000, 9)))

    def test_streamed_sound_gets_marks_in_order_and_keeps_every_byte(self):
        sound, starts = bumps(5)
        marks = pf.SyllableMarks(16000, 5)
        out = []
        for i in range(0, len(sound), 1000):
            out += marks.feed(sound[i:i + 1000])
        out += marks.flush()
        self.assertEqual(b"".join(x for x in out if isinstance(x, bytes)), sound)
        self.assertEqual([x[1] for x in out if isinstance(x, tuple)], [0, 1, 2, 3, 4])

    def test_a_pause_brings_the_count_back_to_the_clause(self):
        marks = pf.SyllableMarks(16000, 8, clauses=[0, 5])
        marks.next = 3                                      # two syllables were missed in the first clause
        marks.feed(b"\0\0" * int(16000 * 0.3))              # the pause at the comma
        self.assertEqual(marks.next, 5)

    @unittest.skipUnless(os.environ.get("COMPANION_TEST_VOICE"), "set COMPANION_TEST_VOICE to a voice folder")
    def test_the_devices_voice_gets_one_mark_per_planned_syllable(self):
        from companion.providers import LocalTTS
        tts = LocalTTS(os.environ["COMPANION_TEST_VOICE"])
        text = "Yes, of course! Hello there, how are you doing today?"
        plan = planner().plan(text, ALL)
        pcm = asyncio.run(tts.full(text))
        offsets = pf.syllable_offsets(pcm, tts.rate, len(plan["syllables"]))
        self.assertEqual(len(offsets), len(plan["syllables"]))
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
