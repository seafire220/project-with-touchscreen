"""Tests for the reply pipeline, text splitting, memory, characters and the settings store."""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import conversation, package, speech_text  # noqa: E402
from companion.audio import Detector, Speaker, loudness  # noqa: E402
from companion.characters import Characters, split_persona  # noqa: E402
from companion.memory import Memory  # noqa: E402
from companion.store import Store, redact  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

PERSONA = "# Aria\n\nYou are Aria, cheerful and brief.\n\n## Greeting\n\nHi! I'm Aria.\n"


def run(coro):
    return asyncio.run(coro)


class SplitterTest(unittest.TestCase):
    def pieces(self, text, size=5):
        s = speech_text.Splitter()
        out = []
        for i in range(0, len(text), size):
            out += s.feed(text[i:i + size])
        return out + s.flush()

    def test_sentences_come_out_as_they_complete(self):
        s = speech_text.Splitter()
        self.assertEqual(s.feed("Hello there, my friend"), [])
        out = s.feed(". How are")
        self.assertEqual([t for t, _, _ in out], ["Hello there, my friend."])
        self.assertEqual([t for t, _, _ in s.feed(" you? ")], ["How are you?"])

    def test_emotion_and_action_tags_are_taken_out_even_when_split_across_pieces(self):
        out = self.pieces("[happy] That's great news! [timer 5m tea] I set a tea timer for five minutes.", 3)
        self.assertEqual(out[0][1], "happy")
        self.assertNotIn("[", " ".join(t for t, _, _ in out))
        actions = [a for _, _, acts in out for a in acts]
        self.assertEqual(actions, [{"kind": "timer", "seconds": 300, "label": "tea"}])

    def test_short_bits_are_joined_and_markdown_is_dropped(self):
        out = self.pieces("Oh. **Really** nice to meet you. 😀 Bye now.", 4)
        texts = [t for t, _, _ in out]
        self.assertEqual(texts[0], "Oh. Really nice to meet you.")
        self.assertEqual(texts[-1], "Bye now.")

    def test_a_long_first_sentence_is_broken_at_a_comma_to_start_speaking_sooner(self):
        text = "Well, let me think about that for a moment, because it is a rather interesting question, and then I will answer."
        first = self.pieces(text, 200)[0][0]
        self.assertLess(len(first), len(text))
        self.assertTrue(first.endswith(","))

    def test_tags(self):
        self.assertEqual(speech_text.parse_tag("alarm 7:05 wake up"), ("action", {"kind": "alarm", "time": "07:05", "label": "wake up"}))
        self.assertEqual(speech_text.parse_tag("timer 1h30m bread"), ("action", {"kind": "timer", "seconds": 5400, "label": "bread"}))
        self.assertIsNone(speech_text.parse_tag("alarm 25:00"))
        self.assertIsNone(speech_text.parse_tag("not a tag"))
        self.assertEqual(speech_text.parse_tag("sad"), ("emotion", "sad"))


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.memory = Memory(os.path.join(self.dir.name, "memory"))
        self.stage = FakeStage()
        self.events, self.actions = [], []

    def tearDown(self):
        self.dir.cleanup()

    def make(self, llm=None, tts=None):
        return conversation.Conversation(
            llm=llm or FakeLLM("[happy] Hello there. How are you today? [timer 2m eggs] Your egg timer is set."),
            tts=tts or FakeTTS(), speaker=Speaker(command=None, realtime=False), stage=self.stage,
            memory=self.memory, persona=PERSONA,
            on_event=lambda k, d: self.events.append((k, d)), on_action=self.actions.append)

    def test_a_reply_is_spoken_sentence_by_sentence_with_mouth_movement(self):
        conv = self.make()
        reply = run(conv.respond("hi"))
        self.assertIsNone(reply.error)
        self.assertEqual(reply.spoken, ["Hello there.", "How are you today?", "Your egg timer is set."])
        self.assertEqual(self.stage.states()[0], "thinking")
        self.assertIn("speaking", self.stage.states())
        self.assertEqual(self.stage.states()[-1], "idle")
        levels = [c["mouth"] for c in self.stage.commands if "mouth" in c]
        self.assertGreater(max(levels), 0.3, "the mouth opens with the voice")
        self.assertEqual(levels[-1], 0.0, "and closes at the end")
        self.assertIn({"express": "happy"}, self.stage.commands)
        self.assertEqual(self.actions, [{"kind": "timer", "seconds": 120, "label": "eggs"}])
        self.assertEqual(self.memory.history()[-1]["reply"], "Hello there. How are you today? Your egg timer is set.")

    def test_the_model_gets_the_persona_rules_memory_and_history(self):
        self.memory.set_notes("- Likes tea\n")
        self.memory.add_turn("earlier question", "earlier answer")
        llm = FakeLLM("Sure.")
        run(self.make(llm=llm).respond("and now?"))
        system, messages = llm.calls[0]
        self.assertIn("You are Aria", system)
        self.assertNotIn("Hi! I'm Aria", system, "the greeting is not part of the instructions")
        self.assertIn("Likes tea", system)
        self.assertIn("[timer", system)
        self.assertEqual(messages[-3:], [{"role": "user", "content": "earlier question"},
                                         {"role": "assistant", "content": "earlier answer"},
                                         {"role": "user", "content": "and now?"}])

    def test_an_interruption_stops_speech_and_remembers_what_was_said(self):
        async def scenario():
            conv = self.make(llm=FakeLLM("One two three four five. Six seven eight nine ten. Eleven twelve.", delay=0.01),
                             tts=FakeTTS(seconds_per_char=0.02))
            conv.speaker.realtime = True
            task = conv.start("count")
            while not any(k == "saying" for k, _ in self.events):
                await asyncio.sleep(0.01)
            conv.interrupt()
            return await task
        reply = run(scenario())
        self.assertTrue(reply.interrupted)
        turn = self.memory.history()[-1]
        self.assertTrue(turn["interrupted"])
        self.assertTrue(turn["reply"].startswith("One two"))
        self.assertNotIn("Eleven", turn["reply"])
        self.assertEqual(self.stage.states()[-1], "idle")

    def test_a_model_failure_is_reported_and_the_character_returns_to_rest(self):
        reply = run(self.make(llm=FakeLLM(fail="start")).respond("hi"))
        self.assertIn("fake model failed", reply.error)
        self.assertTrue(any(k == "error" for k, _ in self.events))
        self.assertEqual(self.stage.states()[-1], "idle")
        self.assertEqual(self.memory.history(), [], "nothing was said, so nothing is remembered")

    def test_a_voice_failure_part_way_keeps_what_was_said(self):
        reply = run(self.make(tts=FakeTTS(fail_on="today")).respond("hi"))
        self.assertIn("fake voice failed", reply.error)
        self.assertEqual(reply.spoken, ["Hello there."])

    def test_a_silent_model_times_out(self):
        old = conversation.FIRST_WORDS_TIMEOUT
        conversation.FIRST_WORDS_TIMEOUT = 0.2
        try:
            reply = run(self.make(llm=FakeLLM(hang=True)).respond("hi"))
        finally:
            conversation.FIRST_WORDS_TIMEOUT = old
        self.assertIn("did not answer", reply.error)

    def test_the_greeting_is_spoken(self):
        tts = FakeTTS()
        run(self.make(tts=tts).greet())
        self.assertEqual(tts.texts, ["Hi! I'm Aria."])


class AudioTest(unittest.TestCase):
    def test_loudness(self):
        import array
        self.assertEqual(loudness(b"\0\0" * 320), 0.0)
        loud = array.array("h", [20000, -20000] * 160).tobytes()
        self.assertEqual(loudness(loud), 1.0)

    def test_the_detector_finds_one_utterance_in_noise(self):
        import array
        import random
        rng = random.Random(1)
        quiet = lambda: array.array("h", (rng.randint(-60, 60) for _ in range(320))).tobytes()
        voice = lambda: array.array("h", (rng.randint(-6000, 6000) for _ in range(320))).tobytes()
        d = Detector(end_silence=0.4)
        frames = [quiet() for _ in range(50)] + [voice() for _ in range(40)] + [quiet() for _ in range(40)]
        found = [pcm for pcm in (d.feed(f) for f in frames) if pcm]
        self.assertEqual(len(found), 1)
        seconds = len(found[0]) / 2 / 16000
        self.assertTrue(0.8 <= seconds <= 1.4, seconds)


class MemoryTest(unittest.TestCase):
    def test_notes_are_updated_by_the_model_and_editable(self):
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m.add_turn("My cat is called Miso.", "What a lovely name!")
            count = run(m.update_notes(FakeLLM("- Has a cat called Miso\n- Likes mornings\nnot a note")))
            self.assertEqual(count, 2)
            self.assertEqual(m.notes(), "- Has a cat called Miso\n- Likes mornings\n")
            m.set_notes("- Edited by the owner\n")
            self.assertIn("Edited by the owner", m.update_prompt())
            m.clear()
            self.assertEqual((m.notes(), m.history()), ("", []))


class CharactersTest(unittest.TestCase):
    def test_install_list_edit_export_delete(self):
        with tempfile.TemporaryDirectory() as d:
            chars = Characters(d)
            data = package.build(good_files(), manifest())
            cid = chars.install(data)
            self.assertEqual(cid, "aria")
            self.assertEqual(chars.list()[0]["name"], "Aria")
            with self.assertRaises(package.PackageError):
                chars.install(data)
            chars.set_device_settings(cid, {"voice": "voice-123"})
            chars.install(data, replace=True)
            self.assertEqual(chars.device_settings(cid)["voice"], "voice-123", "device choices survive an update")
            chars.set_persona(cid, PERSONA)
            with self.assertRaises(ValueError):
                chars.set_persona(cid, "key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            exported = package.open_package(io.BytesIO(chars.export(cid)))
            self.assertEqual(exported.persona, PERSONA)
            self.assertNotIn("device.json", exported.files)
            chars.delete(cid)
            self.assertEqual(chars.list(), [])

    def test_ids_from_outside_cannot_reach_other_folders(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(KeyError):
                Characters(d).persona("../../etc")

    def test_persona_greeting(self):
        self.assertEqual(split_persona(PERSONA), ("# Aria\n\nYou are Aria, cheerful and brief.", "Hi! I'm Aria."))


class StoreTest(unittest.TestCase):
    def test_keys_are_kept_apart_and_never_returned(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            s.set_secret("openai", "sk-test-1234567890")
            self.assertEqual(s.secret_status()["openai"], True)
            self.assertNotIn("sk-test", json.dumps(s.secret_status()))
            self.assertNotIn("sk-test", json.dumps(s.settings()))
            self.assertEqual(os.stat(s.secrets_path).st_mode & 0o777, 0o600)
            self.assertEqual(redact("failed with sk-test-1234567890 oops", s), "failed with [openai key] oops")
            with self.assertRaises(ValueError):
                s.set_secret("nonsense", "x")
            s.set_secret("openai", "")
            self.assertFalse(s.secret_status()["openai"])

    def test_settings_merge_and_reject_unknown_names(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            s.update_settings({"llm": {"provider": "groq", "model": "m"}})
            self.assertEqual(s.settings()["llm"]["max_tokens"], 400, "defaults kept")
            with self.assertRaises(ValueError):
                s.update_settings({"bogus": 1})

    def test_password(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            self.assertFalse(s.has_password())
            with self.assertRaises(ValueError):
                s.set_password("short")
            s.set_password("correct horse")
            self.assertTrue(s.check_password("correct horse"))
            self.assertFalse(s.check_password("wrong horse"))


if __name__ == "__main__":
    unittest.main()
