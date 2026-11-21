"""The wake word: saying the character's name starts listening (docs/28-user-guide.md)."""
import array
import asyncio
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import device as device_module, package, wakeword  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.device import Device  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

QUIET = array.array("h", [30, -30] * 160).tobytes()
VOICE = array.array("h", [9000, -9000] * 160).tobytes()


class WordsTest(unittest.TestCase):
    def test_it_listens_for_a_greeting_and_the_first_name_or_the_owners_words(self):
        self.assertEqual(wakeword.phrases("Mika"), ["HEY MIKA", "HI MIKA", "HELLO MIKA"])
        self.assertEqual(wakeword.phrases("Zoë Starlight"), ["HEY ZOE", "HI ZOE", "HELLO ZOE"])
        self.assertEqual(wakeword.phrases("Mika", "okay, computer!"), ["OKAY COMPUTER"])
        self.assertEqual(wakeword.phrases("", ""), [])

    def test_the_words_are_taken_off_what_was_said_after_them(self):
        words = wakeword.phrases("Mika")
        for said, rest in (("Hey, Mika, what time is it?", "what time is it?"),
                           ("Hamika, what time is it?", "what time is it?"),     # run together by the recogniser
                           ("Hey Miko, set a timer for ten minutes.", "set a timer for ten minutes."),
                           ("Hello, mika.", ""), ("Hey Mika", ""), ("", "")):
            self.assertEqual(wakeword.after_wake(said, words), rest, said)
        self.assertEqual(wakeword.after_wake("What is the weather like?", words), "What is the weather like?",
                         "nothing like the name: all of it is the request")

    def test_without_the_model_it_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(wakeword.WakeWordError, "not on this device|not installed"):
                wakeword.WakeWord(d, ["HEY MIKA"])


class FakeWake:
    """Hears the words on a chosen frame."""

    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.fed = 0

    def feed(self, frame):
        self.fed += 1
        return "Hey Ace" if self.fed == self.on_frame else None

    def reset(self):
        pass


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.heard = []

    async def transcribe(self, pcm):
        self.heard.append(len(pcm))
        return self.text


class Mic:
    def __init__(self, frames):
        self.list = frames

    async def frames(self):
        for f in self.list:
            yield f
            await asyncio.sleep(0)
        await asyncio.sleep(3600)


class DeviceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.llm = FakeLLM("It is ten past nine.")
        self.stt = FakeSTT("Hey, Ace, what time is it?")
        self.stage = FakeStage()
        self.device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=self.stage,
                             provider_factory=lambda which, d: {"llm": self.llm, "tts": FakeTTS(), "stt": self.stt}.get(which))
        self.device.characters.install(package.build(good_files(), manifest()))
        self.device.store.update_settings({"wake_word": {"on": True}})

    async def asyncTearDown(self):
        self.dir.cleanup()

    def ready(self, on_frame):
        self.device._wake = FakeWake(on_frame)
        self.device._wake_for = (["HEY ACE"], "normal")

    async def run_mic(self, frames, seconds=0.6):
        self.device.microphone = Mic(frames)
        task = asyncio.ensure_future(self.device.listen_loop())
        await asyncio.sleep(seconds)
        task.cancel()

    async def test_in_one_breath_the_question_is_answered(self):
        self.ready(on_frame=40)                 # the words heard while the person is still speaking
        await self.run_mic([QUIET] * 20 + [VOICE] * 70 + [QUIET] * 80)
        self.assertEqual(self.stt.heard[:1] and self.stt.heard[0] > 70 * 640, True, "the whole utterance, words and all")
        self.assertEqual(self.llm.calls[0][1][-1]["content"], "what time is it?", "the words are taken off")
        self.assertTrue(self.device.listening, "it listens a while for a follow-up")
        self.assertGreater(self.device.answer_until, time.time())

    async def test_the_words_alone_wait_for_the_question(self):
        self.stt.text = "Hey Ace."
        self.ready(on_frame=40)
        await self.run_mic([QUIET] * 20 + [VOICE] * 40 + [QUIET] * 80)
        self.assertEqual(self.llm.calls, [], "nothing asked yet")
        self.assertTrue(self.device.listening)
        self.assertEqual(self.device.state, "listening")
        self.device.answer_until = time.time() - 1
        await self.run_mic([QUIET] * 10, seconds=0.2)
        self.assertEqual((self.device.listening, self.device.state), (False, "idle"), "nothing more said: it stops")

    async def test_not_while_the_microphone_is_off_or_the_character_is_talking(self):
        self.ready(on_frame=1)
        self.device.set_muted(True)
        self.assertIsNone(self.device.wake_listener())
        self.device.set_muted(False)
        self.device.state = "speaking"
        await self.run_mic([VOICE] * 20, seconds=0.3)
        self.assertEqual(self.device._wake.fed, 0, "its own voice is not listened to")

    async def test_the_words_follow_the_character_and_the_settings(self):
        self.assertEqual(self.device.wake_words(), wakeword.phrases(self.device.characters.manifest(self.device.active_id())["name"]))
        old = self.device.store.settings()
        new = self.device.store.update_settings({"wake_word": {"phrase": "okay buddy"}})
        self.ready(on_frame=5)
        self.device.settings_changed(old, new)
        self.assertIsNone(self.device._wake, "built again for the new words")
        self.assertEqual(self.device.wake_words(), ["OKAY BUDDY"])
        status = self.device.status()["wake_word"]
        self.assertEqual(status["words"], ["Okay Buddy"])

    async def test_a_missing_model_is_reported_once_and_left_off(self):
        self.assertIsNone(self.device.wake_listener())
        # The model is looked for in the background: wait for that (a busy computer can take a while).
        for _ in range(100):
            if self.device.wake_error:
                break
            await asyncio.sleep(0.05)
        self.assertIsNone(self.device.wake_listener())
        self.assertRegex(self.device.wake_error, "not on this device|not installed")
        self.assertEqual(sum(1 for e in self.device.log if "wake word cannot" in e.get("message", "")), 1)


@unittest.skipUnless(os.environ.get("COMPANION_WAKE_MODEL") and os.environ.get("COMPANION_VOICE_MODEL"),
                     "set COMPANION_WAKE_MODEL and COMPANION_VOICE_MODEL to the model folders")
class RealModelTest(unittest.TestCase):
    def test_hello_and_a_clear_name_is_heard_and_everyday_speech_is_not(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        import numpy as np
        import wake_check
        from companion.providers import LocalTTS
        tts = LocalTTS(os.environ["COMPANION_VOICE_MODEL"])
        listener = wakeword.WakeWord(os.environ["COMPANION_WAKE_MODEL"], wakeword.phrases("Lucy"))
        rng = np.random.default_rng(1)
        heard = 0
        for sid in (12, 77, 140, 333, 500, 702):
            tts.sid = sid
            heard += bool(wake_check.listen(listener, wake_check.clip(wake_check.resample(tts._speak("Hello Lucy."), tts.rate), rng)))
        self.assertGreaterEqual(heard, 5)
        tts.sid = 12
        everyday = wake_check.clip(wake_check.resample(tts._speak("Could you set a timer for ten minutes please?"), tts.rate), rng)
        self.assertEqual(wake_check.listen(listener, everyday), [])


if __name__ == "__main__":
    unittest.main()
