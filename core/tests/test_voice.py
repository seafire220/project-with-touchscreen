"""The on-device voice: phonemes from espeak-ng, and a Piper voice through sherpa-onnx.

The voice test needs a voice folder: set COMPANION_TEST_VOICE to one (for example
models/tts from the device install, or a sherpa-onnx vits-piper download)."""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import phonemes, providers  # noqa: E402

VOICE = os.environ.get("COMPANION_TEST_VOICE", "")


class PhonemeTest(unittest.TestCase):
    def test_clauses_keep_their_punctuation_and_numbers_stay_whole(self):
        self.assertEqual(phonemes.clauses("Hello there! It costs 3.5 dollars, I think."),
                         [("Hello there", "!"), ("It costs 3.5 dollars", ","), ("I think", ".")])
        self.assertEqual(phonemes.clauses("  "), [])
        self.assertEqual(phonemes.clauses("No ending"), [("No ending", "")])

    @unittest.skipUnless(phonemes.espeak_path(), "espeak-ng is not installed")
    def test_phonemes_come_clause_by_clause_with_the_marks(self):
        p = phonemes.phonemize("Welcome home! Shall we talk, or rest?")
        self.assertEqual(p.count("!"), 1)
        self.assertEqual(p.count(","), 1)
        self.assertTrue(p.endswith("?"))
        self.assertIn("ˈ", p, "stress marks, as the voices were trained with")

    def test_a_missing_espeak_is_reported_plainly(self):
        with self.assertRaises(phonemes.PhonemeError):
            phonemes.phonemize("Hello.", espeak="/nonexistent/espeak-ng")


@unittest.skipUnless(VOICE and os.path.isdir(VOICE) and phonemes.espeak_path(), "no test voice (COMPANION_TEST_VOICE)")
class LocalVoiceTest(unittest.TestCase):
    def test_it_speaks_in_chunks_and_picks_speakers_by_number(self):
        tts = providers.build_tts({"tts": {"provider": "local", "voice": "7"}}, store=None, model_dir=VOICE)
        self.assertEqual(tts.sid, 7 if tts.speakers > 7 else 0)
        default = int(tts.catalogue.get("default", 0))
        tts.set_voice("not a number")
        self.assertEqual(tts.sid, default)
        tts.set_voice("99999")
        self.assertEqual(tts.sid, default, "out of range falls back to the default voice")
        if tts.catalogue:
            listed = asyncio.run(tts.voices())
            self.assertEqual(len(listed), 24)
            self.assertTrue(listed[0]["name"].startswith("Higher voice A"))

        async def speak():
            return [chunk async for chunk in tts.stream("Hello there, it is lovely to meet you.")]
        chunks = asyncio.run(speak())
        seconds = sum(len(c) for c in chunks) / 2 / tts.rate
        self.assertGreater(seconds, 1.0)
        self.assertTrue(all(len(c) <= int(tts.rate * tts.CHUNK) * 2 for c in chunks))
        self.assertIn("seconds of audio", asyncio.run(tts.test()))

    def test_a_missing_voice_folder_is_reported_plainly(self):
        with self.assertRaises(providers.ProviderError):
            providers.LocalTTS("/nonexistent/voice")


if __name__ == "__main__":
    unittest.main()
