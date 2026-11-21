"""Tests for piper_voice.py: Piper voices made ready for sherpa-onnx, vowel pairs and all."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import piper_voice  # noqa: E402

CONFIG = {
    "audio": {"sample_rate": 22050},
    "espeak": {"voice": "en-gb-x-rp"},
    "num_speakers": 109,
    "language": {"name_english": "English"},
    "vowel_clusters": [["a", "ɪ"], ["a", "ʊ"], ["e", "ɪ"]],
    "phoneme_id_map": {"_": [0], "^": [1], "$": [2], " ": [3], "a": [14], "ɪ": [74], "m": [25], "h": [20],
                       "s": [31], "ˈ": [120], "aɪ": [160], "aʊ": [161], "eɪ": [162]},
}


def read_varint(data, i):
    shift = value = 0
    while True:
        b = data[i]
        i += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, i


def read_metadata(data):
    """The metadata_props entries (field 14) in a serialised ONNX model, as {key: value}."""
    out, i = {}, 0
    while i < len(data):
        tag, i = read_varint(data, i)
        field, wire = tag >> 3, tag & 7
        if wire == 2:
            size, i = read_varint(data, i)
            body, i = data[i:i + size], i + size
            if field == 14:
                entry, j = {}, 0
                while j < len(body):
                    t, j = read_varint(body, j)
                    n, j = read_varint(body, j)
                    entry[t >> 3] = body[j:j + n].decode("utf-8")
                    j += n
                out[entry[1]] = entry[2]
        elif wire == 0:
            _, i = read_varint(data, i)
        else:
            raise AssertionError("unexpected wire type %d" % wire)
    return out


class PiperVoiceTest(unittest.TestCase):
    def test_vowel_pairs_become_one_stand_in_each(self):
        clusters = piper_voice.cluster_symbols(CONFIG)
        self.assertEqual(clusters, {"aɪ": "", "aʊ": "", "eɪ": ""})
        self.assertEqual(piper_voice.merge_clusters("mˈaɪ hˈaʊs", clusters), "mˈ hˈs")
        self.assertEqual(piper_voice.merge_clusters("mˈaɪ", {}), "mˈaɪ", "older voices have no pairs")

    def test_the_symbol_list_names_each_pair_by_its_stand_in(self):
        lines = piper_voice.tokens(CONFIG).splitlines()
        self.assertIn(" 160", lines)
        self.assertIn("  3", lines, "the space symbol, as sherpa-onnx's own lists write it")
        self.assertNotIn("aɪ 160", lines)
        bad = dict(CONFIG, phoneme_id_map=dict(CONFIG["phoneme_id_map"], **{"tʃ": [99]}))
        with self.assertRaises(ValueError):
            piper_voice.tokens(bad)

    def test_a_converted_model_carries_sherpas_labels_after_the_original_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            model = os.path.join(d, "voice.onnx")
            original = b"\x08\x07\x12\x04test"          # a stand-in serialised model: two fields
            with open(model, "wb") as f:
                f.write(original)
            desc = model + ".json"
            with open(desc, "w", encoding="utf-8") as f:
                json.dump(CONFIG, f, ensure_ascii=False)
            out = piper_voice.convert(model, desc, os.path.join(d, "tts"))
            with open(out, "rb") as f:
                data = f.read()
            self.assertTrue(data.startswith(original))
            meta = read_metadata(data)
            self.assertEqual(meta["model_type"], "vits")
            self.assertEqual(meta["comment"], "piper")
            self.assertEqual(meta["voice"], "en-gb-x-rp")
            self.assertEqual((meta["n_speakers"], meta["sample_rate"], meta["has_espeak"]), ("109", "22050", "1"))
            with open(os.path.join(d, "tts", "tokens.txt"), encoding="utf-8") as f:
                self.assertIn(" 162\n", f.read())
            self.assertTrue(os.path.exists(os.path.join(d, "tts", "voice.onnx.json")))


if __name__ == "__main__":
    unittest.main()
