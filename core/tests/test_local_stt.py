"""On-device speech recognition with the real model. Runs when COMPANION_TEST_STT_MODEL names the model folder."""
import asyncio
import os
import sys
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MODEL = os.environ.get("COMPANION_TEST_STT_MODEL", "")


@unittest.skipUnless(MODEL and os.path.isdir(MODEL), "set COMPANION_TEST_STT_MODEL to the model folder")
class LocalSTTTest(unittest.TestCase):
    def test_the_model_recognises_its_test_recording(self):
        from companion.providers import LocalSTT
        stt = LocalSTT(MODEL)
        with wave.open(os.path.join(MODEL, "test_wavs", "0.wav")) as w:
            pcm, rate = w.readframes(w.getnframes()), w.getframerate()
        text = asyncio.run(stt.transcribe(pcm, rate)).lower()
        for word in ("early nightfall", "yellow lamps", "quarter"):
            self.assertIn(word, text)
        self.assertEqual(asyncio.run(stt.transcribe(b"\0\0" * 16000)), "", "silence gives no words")


if __name__ == "__main__":
    unittest.main()
