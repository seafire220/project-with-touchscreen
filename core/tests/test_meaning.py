"""Matching by meaning: the device's own reading of a small static embedding model, and memory finding what
was meant, not only what was said (docs/31-memory.md)."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np  # noqa: E402

from companion import meaning  # noqa: E402
from companion.memory import Memory  # noqa: E402

# A made-up model: pets point one way, food another, weather a third; small words barely count.
DIRECTIONS = {"dog": 0, "pup": 0, "puppy": 0, "bis": 0, "##cuit": 0, "train": 0, "training": 0,
              "vegetarian": 1, "meat": 1, "dinner": 1, "weather": 2, "rain": 2}
SMALL = ["they", "have", "a", "called", "my", "chewed", "shoes", "again", "are", "what", "'", "s", "the", "like",
         "is", "it", "going", "to", "for", "no", "please", "make", "should", "i", "?", ",", "!", "we", "talked", "about",
         "cafe", "naive", "."]


def fake_model(folder):
    vocab = {"[PAD]": 0, "[UNK]": 1}
    for word in list(DIRECTIONS) + SMALL:
        vocab.setdefault(word, len(vocab))
    vectors = np.zeros((len(vocab), 4), dtype=np.float32)
    for word, i in vocab.items():
        if word in DIRECTIONS:
            vectors[i, DIRECTIONS[word]] = 1.0
        elif word in SMALL:
            vectors[i, 3] = 0.08
    with open(os.path.join(folder, "tokenizer.json"), "w") as f:
        json.dump({"model": {"type": "WordPiece", "vocab": vocab, "unk_token": "[UNK]", "continuing_subword_prefix": "##",
                             "max_input_chars_per_word": 100}}, f)
    data = vectors.tobytes()
    header = json.dumps({"embeddings": {"dtype": "F32", "shape": list(vectors.shape), "data_offsets": [0, len(data)]}}).encode()
    with open(os.path.join(folder, "model.safetensors"), "wb") as f:
        f.write(struct.pack("<Q", len(header)) + header + data)
    return meaning.Meaning(folder)


class ModelTest(unittest.TestCase):
    def test_text_is_split_the_way_the_model_was_taught(self):
        self.assertEqual(meaning._words("Café, naïve!  my dog's"), ["cafe", ",", "naive", "!", "my", "dog", "'", "s"])
        self.assertEqual(meaning._words("日本語 ok"), ["日", "本", "語", "ok"])
        with tempfile.TemporaryDirectory() as d:
            model = fake_model(d)
            self.assertEqual(model.pieces("Biscuit"), [model.vocab["bis"], model.vocab["##cuit"]], "word pieces")
            self.assertEqual(model.pieces("zebra dog"), [model.vocab["dog"]], "an unknown word is left out")
            vectors = model.embed(["my pup", "", "zebra"])
            self.assertAlmostEqual(float(np.linalg.norm(vectors[0])), 1.0, places=5)
            self.assertFalse(vectors[1].any() or vectors[2].any(), "nothing known: no direction")

    def test_without_the_model_memory_matches_by_words_as_before(self):
        self.assertIsNone(meaning.load("/nonexistent/meaning"))
        with tempfile.TemporaryDirectory() as d:
            m = Memory(d)
            m.add_memory("They have a dog called Biscuit", "their people", 2)
            self.assertNotIn("Biscuit", m.context("my pup chewed my shoes again")[0])


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.model = fake_model(self.dir.name)
        self.m = Memory(os.path.join(self.dir.name, "memory"), meaning=self.model)

    def tearDown(self):
        self.dir.cleanup()

    def test_a_memory_is_found_by_what_was_meant(self):
        dog = self.m.add_memory("They have a dog called Biscuit", "their people", 2)
        self.m.add_memory("They are vegetarian", "health and wellbeing", 2)
        text, _ = self.m.context("my pup chewed my shoes again")
        self.assertIn("Biscuit", text, "no word in common, but the same meaning")
        self.assertNotIn("vegetarian", text)
        text, _ = self.m.context("what should I make for dinner? no meat please")
        self.assertIn("vegetarian", text)
        text, _ = self.m.context("what's the weather like?")
        self.assertNotIn("Biscuit", text, "small talk brings up nothing unlike it")
        self.assertNotIn("vegetarian", text)
        self.assertTrue(os.path.exists(self.m.vectors_path))
        self.assertTrue(self.m.forget_memory(dog["id"]))
        with np.load(self.m.vectors_path) as data:
            self.assertNotIn(dog["id"], list(data["m_ids"]), "a forgotten memory's vector goes with it")

    def test_conversations_are_recalled_by_meaning_too(self):
        from companion import memory as mem
        mem._write_jsonl(self.m.sessions_path, [
            {"id": 1, "start": 1_800_000_000, "end": 1_800_000_600, "title": "Training", "summary": "We talked about puppy training.", "done": True},
            {"id": 2, "start": 1_800_100_000, "end": 1_800_100_600, "title": "Rain", "summary": "We talked about the rain.", "done": True},
            {"id": 3, "start": 1_800_200_000, "end": 1_800_200_600, "title": "Dinner", "summary": "We talked about dinner.", "done": True}])
        self.assertEqual([s["id"] for s in self.m.recall("my dog chewed my shoes", limit=1)], [1, 3])
        self.assertEqual(self.m.refresh_vectors(), 1, "the latest conversation, not needed until now")
        self.assertEqual(self.m.refresh_vectors(), 0, "all made already, and kept")
        sessions = mem._jsonl(self.m.sessions_path)
        sessions[0]["summary"] = "We talked about the weather."
        mem._write_jsonl(self.m.sessions_path, sessions)
        self.assertEqual(self.m.refresh_vectors(), 1, "a changed summary gets a new vector")
        self.m.clear()
        self.assertFalse(os.path.exists(self.m.vectors_path), "forgetting everything takes the vectors too")


@unittest.skipUnless(os.environ.get("COMPANION_MEANING_TEST"), "set COMPANION_MEANING_TEST to the potion-base-8M folder")
class RealModelTest(unittest.TestCase):
    """The real model on 30 remarks whose memory shares few words with them."""
    MEMORIES = ["Their name is Sam.", "Their sister Kim lives in Darwin.", "They have a dog called Biscuit, a golden retriever.",
                "They are vegetarian.", "They are allergic to peanuts.", "They work as a nurse at the Royal Hospital, often on night shifts.",
                "They are studying for a biology exam on 2026-12-03.", "They love oolong tea.", "Their favourite band is Arctic Monkeys.",
                "They play the guitar, learning since September.", "Their mum's birthday is on 2026-12-14.",
                "They feel anxious before job interviews.", "They moved to Brisbane last year from Melbourne.",
                "Their best friend is called Priya.", "They are training for a half marathon in March.", "They hate horror movies.",
                "They are saving up for a trip to Japan.", "Their car is an old blue Corolla that keeps breaking down.",
                "They have trouble sleeping lately.", "Their partner Alex works in IT.", "They grow tomatoes and basil on their balcony.",
                "They like it when I tell them jokes.", "I said my favourite season is autumn.", "They are learning Japanese on Duolingo.",
                "Their cat Miso died last year; it still makes them sad.", "They support the Brisbane Lions in the AFL.",
                "They don't drink alcohol.", "They read fantasy novels, especially Brandon Sanderson.",
                "They have a sore knee from an old football injury.", "Their grandmother lives in a nursing home in Toowoomba."]
    REMARKS = ["my pup chewed my shoes again", "I'm so stressed, my shift at the hospital was brutal",
               "what should I make for dinner? no meat please", "can I have a snack with nuts in it?",
               "I've got a test coming up and I'm not ready", "fancy a cuppa?", "I heard a new song by Alex Turner's band",
               "I practised chords for an hour today", "I need a present for my mother", "I have an interview tomorrow and I'm nervous",
               "do you remember where I grew up?", "my bestie is coming over", "I ran 15 kilometres this morning!",
               "want to watch something scary tonight?", "I'm putting money aside for Tokyo", "the car won't start again",
               "I couldn't fall asleep last night", "my boyfriend got a promotion at his tech job",
               "the plants on my balcony are thriving", "tell me something funny", "konnichiwa! I learnt a new word today",
               "I saw a cat that looked just like my old one", "the footy is on tonight, go Lions!", "want a beer? oh wait",
               "I just finished Mistborn", "my knee is killing me", "I visited Nan today", "my sister called from up north",
               "what's your favourite time of year?", "who am I again?"]
    ANSWERS = [2, 5, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 1, 22, 0]

    def test_the_right_memory_is_given_for_most_remarks(self):
        model = meaning.load(os.environ["COMPANION_MEANING_TEST"])
        with tempfile.TemporaryDirectory() as d:
            words, both = Memory(os.path.join(d, "w")), Memory(os.path.join(d, "m"), meaning=model)
            for text in self.MEMORIES:
                words.add_memory(text, "other", 2, now=1)
                both.add_memory(text, "other", 2, now=1)
            right = lambda m: sum(self.MEMORIES[a].rstrip(".") in m.context(r)[0] for r, a in zip(self.REMARKS, self.ANSWERS))
            self.assertLessEqual(right(words), 10)
            self.assertGreaterEqual(right(both), 26)
            for small_talk in ("what's the weather like?", "ok", "hmm, let me think", "that's interesting"):
                self.assertLessEqual(both.context(small_talk)[0].count("\n- "), 2)


if __name__ == "__main__":
    unittest.main()
