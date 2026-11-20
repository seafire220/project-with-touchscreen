"""Matching by meaning, on the device: what someone says is turned into a vector, and so is each memory and
conversation, so "my pup chewed my shoes" finds "They have a dog called Biscuit" (docs/31-memory.md).

The model is Model2Vec's potion-base-8M (MIT; distilled from BAAI's bge-base-en-v1.5, MIT): a table of one
256-number vector per word piece, averaged over a text's pieces. No neural network runs: with numpy alone it
takes well under a millisecond per sentence and about 15 MB of memory, which suits a 1 GB board. On a test
of 30 remarks and 30 memories (core/tests/test_meaning.py), it put the right memory in its top three for 29;
matching by words alone found 9.

The model's files (model.safetensors, tokenizer.json) live in /var/lib/companion/models/meaning, put there
when the device image is made (device/install.sh) or by an update. Without them, memory matches by words
alone, as before.
"""
import json
import os
import struct
import threading
import unicodedata

try:
    import numpy as np
except ImportError:                     # memory still works, by words alone
    np = None

FOLDER = os.environ.get("COMPANION_MEANING", "/var/lib/companion/models/meaning")
_loaded = {}
_lock = threading.Lock()


class Meaning:
    """The model: a vocabulary of word pieces and a vector for each."""

    def __init__(self, folder):
        with open(os.path.join(folder, "tokenizer.json"), encoding="utf-8") as f:
            tokenizer = json.load(f)
        model = tokenizer["model"]
        if model.get("type") != "WordPiece":
            raise ValueError("the meaning model's tokenizer is not WordPiece")
        self.vocab = model["vocab"]
        self.unk = self.vocab.get(model.get("unk_token", "[UNK]"))
        self.prefix = model.get("continuing_subword_prefix", "##")
        self.max_chars = int(model.get("max_input_chars_per_word", 100))
        self.vectors = _read_safetensors(os.path.join(folder, "model.safetensors"), "embeddings").astype(np.float16)
        if self.vectors.shape[0] != len(self.vocab):
            raise ValueError("the meaning model's vocabulary and vectors do not match")
        self.size = self.vectors.shape[1]

    def pieces(self, text):
        """The word pieces' numbers for a text (lower-cased, without accents, punctuation apart)."""
        out = []
        for word in _words(text):
            if len(word) > self.max_chars:
                continue
            start, found = 0, []
            while start < len(word):
                end, piece = len(word), None
                while start < end:
                    candidate = word[start:end] if start == 0 else self.prefix + word[start:end]
                    if candidate in self.vocab:
                        piece = self.vocab[candidate]
                        break
                    end -= 1
                if piece is None:
                    found = []                  # an unknown word is left out whole
                    break
                found.append(piece)
                start = end
            out.extend(found)
        return out

    def embed(self, texts):
        """One unit-length vector per text (all zeros for a text with no known words)."""
        out = np.zeros((len(texts), self.size), dtype=np.float32)
        for i, text in enumerate(texts):
            ids = [p for p in self.pieces(text) if p != self.unk]
            if ids:
                v = self.vectors[ids].astype(np.float32).mean(axis=0)
                norm = float(np.linalg.norm(v))
                if norm > 0:
                    out[i] = v / norm
        return out


def load(folder=None):
    """The model in `folder` (by default the device's), loaded once; None if it is not there."""
    folder = folder or FOLDER
    with _lock:
        if folder not in _loaded:
            try:
                _loaded[folder] = Meaning(folder) if np is not None and os.path.isfile(
                    os.path.join(folder, "model.safetensors")) else None
            except (OSError, ValueError, KeyError):
                _loaded[folder] = None
        return _loaded[folder]


def _read_safetensors(path, name):
    """One tensor from a safetensors file (an 8-byte header length, a JSON header, the raw numbers)."""
    with open(path, "rb") as f:
        size = struct.unpack("<Q", f.read(8))[0]
        if size > 10 * 1024 * 1024:
            raise ValueError("the meaning model's file is not laid out as expected")
        header = json.loads(f.read(size))
        info = header[name]
        dtype = {"F32": np.float32, "F16": np.float16}[info["dtype"]]
        begin, end = info["data_offsets"]
        f.seek(8 + size + begin)
        data = np.frombuffer(f.read(end - begin), dtype=dtype)
    return data.reshape(info["shape"])


def _words(text):
    """BERT's way of splitting text into words: lower case, no accents, each punctuation mark apart."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    words, current = [], []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Mn":                         # an accent
            continue
        if ch.isspace() or cat in ("Cc", "Cf"):
            if current:
                words.append("".join(current))
                current = []
        elif _punctuation(ch, cat) or _cjk(ch):
            if current:
                words.append("".join(current))
                current = []
            words.append(ch)
        else:
            current.append(ch)
    if current:
        words.append("".join(current))
    return words


def _punctuation(ch, cat):
    cp = ord(ch)
    return (33 <= cp <= 47) or (58 <= cp <= 64) or (91 <= cp <= 96) or (123 <= cp <= 126) or cat.startswith("P")


def _cjk(ch):
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or (0x20000 <= cp <= 0x2A6DF) or \
        (0xF900 <= cp <= 0xFAFF) or (0x2F800 <= cp <= 0x2FA1F)
