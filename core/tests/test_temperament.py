"""Tests for a character's temperament: suggested from its personality, and turned into the stage's terms."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import temperament  # noqa: E402


class TemperamentTest(unittest.TestCase):
    def test_a_personality_suggests_how_lively_and_expressive(self):
        shy = temperament.suggest("Shy and quiet, a little awkward and reserved around new people.")
        self.assertLess(shy["liveliness"], 0.5)
        self.assertLess(shy["expressiveness"], 0.5)
        bubbly = temperament.suggest("Bubbly, energetic and dramatic; loves to tease.")
        self.assertGreater(bubbly["liveliness"], 0.5)
        self.assertGreater(bubbly["expressiveness"], 0.5)
        self.assertEqual(temperament.suggest("Likes tea and astronomy."), temperament.DEFAULT)
        self.assertEqual(temperament.suggest(None), temperament.DEFAULT)

    def test_values_are_kept_in_range_and_become_the_stages_terms(self):
        self.assertEqual(temperament.clean({"liveliness": 3, "expressiveness": "x"}), {"liveliness": 1.0, "expressiveness": 0.5})
        self.assertEqual(temperament.for_stage({"liveliness": 0.0, "expressiveness": 1.0}), (0.6, 1.4))
        self.assertEqual(temperament.for_stage(None), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
