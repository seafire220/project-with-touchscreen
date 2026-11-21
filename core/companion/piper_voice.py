"""Piper voices for sherpa-onnx, which plays the on-device voice.

Piper publishes a voice as an ONNX model and a JSON description (its symbols, speakers, espeak-ng
voice and settings). sherpa-onnx wants the same model with a few labels inside it, and the symbols as
a `tokens.txt` list. `convert()` makes those, with Python's own library only: the labels are added to
the ONNX file as extra `metadata_props` fields (a protobuf message takes extra fields at its end).

Voices trained with Piper 1.5 merge some vowel pairs into single symbols (`vowel_clusters` in the
description: "aɪ" is one symbol, not "a" then "ɪ"). sherpa-onnx is given one character per symbol, so
each pair gets a stand-in character from Unicode's private-use area: `tokens.txt` lists the stand-in, and
`merge_clusters()` puts it in place of the pair in the phonemes before they are spoken. Both use
`cluster_symbols()`, so they agree.

    python3 -m companion.piper_voice VOICE.onnx VOICE.onnx.json OUT_DIR
"""
import json
import os
import shutil
import sys

# The first private-use character; pairs take this and the ones after it, in the description's order.
PRIVATE_USE = 0xE000


def cluster_symbols(config):
    """{"aɪ": "\\ue000", ...}: each merged vowel pair and the character that stands for it."""
    out = {}
    for i, pair in enumerate(config.get("vowel_clusters") or []):
        if isinstance(pair, (list, tuple)) and pair and all(isinstance(p, str) for p in pair):
            out["".join(pair)] = chr(PRIVATE_USE + i)
    return out


def merge_clusters(phonemes, clusters):
    """Phonemes as espeak-ng gives them, with each merged vowel pair as its one stand-in character (as Piper
    1.5 merges them: no pair starts with a sound another ends with, so the order of replacing is free)."""
    for pair, symbol in clusters.items():
        phonemes = phonemes.replace(pair, symbol)
    return phonemes


def tokens(config):
    """The symbol list sherpa-onnx reads: one "symbol id" per line."""
    clusters = cluster_symbols(config)
    lines = []
    for symbol, ids in config["phoneme_id_map"].items():
        if len(symbol) > 1 and symbol not in clusters:
            raise ValueError("the voice has a symbol of several characters that is not a vowel pair: %r" % symbol)
        lines.append("%s %d\n" % (clusters.get(symbol, symbol), ids[0]))
    return "".join(lines)


def _varint(n):
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def metadata_fields(pairs):
    """ONNX `ModelProto.metadata_props` (field 14) entries, as bytes to add at the end of a model file."""
    out = bytearray()
    for key, value in pairs:
        k, v = str(key).encode("utf-8"), str(value).encode("utf-8")
        entry = b"\x0a" + _varint(len(k)) + k + b"\x12" + _varint(len(v)) + v
        out += b"\x72" + _varint(len(entry)) + entry
    return bytes(out)


def sherpa_metadata(config):
    return [
        ("model_type", "vits"),
        ("comment", "piper"),
        ("language", config.get("language", {}).get("name_english", "English")),
        ("voice", config["espeak"]["voice"]),
        ("has_espeak", 1),
        ("n_speakers", config.get("num_speakers", 1)),
        ("sample_rate", config["audio"]["sample_rate"]),
    ]


def convert(model, description, out_dir):
    """Make a sherpa-onnx voice folder from a Piper voice: the model with its labels, `tokens.txt`, and the
    description (the device reads its espeak-ng voice, its settings and its vowel pairs from it)."""
    with open(description, encoding="utf-8") as f:
        config = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.basename(model)
    target = os.path.join(out_dir, name)
    shutil.copyfile(model, target + ".part")
    with open(target + ".part", "ab") as f:
        f.write(metadata_fields(sherpa_metadata(config)))
    os.replace(target + ".part", target)
    with open(os.path.join(out_dir, "tokens.txt"), "w", encoding="utf-8") as f:
        f.write(tokens(config))
    shutil.copyfile(description, os.path.join(out_dir, name + ".json"))
    return target


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__.strip().splitlines()[-1].strip())
    print(convert(sys.argv[1], sys.argv[2], sys.argv[3]))
