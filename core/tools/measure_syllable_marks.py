"""Measure how close the syllable marks land to the real sounds, using the exact timings of a Piper voice.

    python core/tools/measure_syllable_marks.py VOICE_FOLDER [--speakers 0,7,23] [--speeds 0.85,1,1.2]

A Piper voice model decides how long it holds each phoneme. This tool makes a copy of the model that also
reports those durations (it needs the `onnx`, `onnxruntime` and `numpy` packages, for this tool only),
speaks a set of test sentences, and so knows exactly when each word and each vowel starts. It then places
the marks as the device does, for a sentence made whole (`syllable_offsets`) and for one streamed in
(`SyllableMarks`), and reports how far they land from the vowels and the words' starts.

Only for measuring: nothing here runs on the device.
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import performance as pf  # noqa: E402

SENTENCES = [
    "Yes, of course! I would love to help you with that today.",
    "Hello there, how are you doing this lovely morning?",
    "No, I really do not think that is a good idea at all.",
    "Maybe we could try something different next time.",
    "Oh wow, that is absolutely amazing news, congratulations!",
    "I'm so sorry to hear that. Do you want to talk about it?",
    "First, preheat the oven. Next, mix the flour and sugar, and finally bake it for twenty minutes.",
    "Haha, you always know how to make me laugh.",
    "Thank you so much, that really means a lot to me.",
    "Hmm, I'm not sure. It could be the battery, or maybe the charger.",
    "Good night! Sleep well, and I'll see you tomorrow.",
    "The rings of Saturn are mostly made of ice, with some rock and dust mixed in.",
]
HOP = 256        # samples per frame of a Piper voice


class Voice:
    def __init__(self, folder):
        import onnx
        import onnxruntime as ort
        model = next(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".onnx"))
        self.config = json.load(open(model + ".json"))
        self.ids = self.config["phoneme_id_map"]
        self.rate = self.config["audio"]["sample_rate"]
        graph = onnx.load(model)
        ceil = next(n for n in graph.graph.node if n.op_type == "Ceil")      # the phonemes' lengths in frames
        graph.graph.output.append(onnx.helper.make_tensor_value_info(ceil.output[0], onnx.TensorProto.FLOAT, None))
        with tempfile.TemporaryDirectory() as work:
            path = os.path.join(work, "durations.onnx")
            onnx.save(graph, path)
            self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])

    def speak(self, text, speaker=0, speed=1.0):
        """The sound (16-bit bytes), and when each word and each vowel starts (seconds)."""
        import numpy as np
        words = pf.WORD.findall(text)
        run = subprocess.run(["espeak-ng", "-q", "--ipa", "-v", self.config.get("espeak", {}).get("voice", "en-us")],
                             input="\n".join(words), capture_output=True, text=True, timeout=30)
        ipas = [line.strip() for line in run.stdout.splitlines() if line.strip()]
        ends = [m.end() for m in pf.WORD.finditer(text)]
        ids, word_first, vowel_first = [self.ids["^"][0], 0], [], []
        for k, ipa in enumerate(ipas):
            word_first.append(len(ids))
            run_ = 0                          # finds each syllable's vowel as syllables_from_ipa does
            for ch in ipa:
                if ch in pf.IPA_SHAPES:
                    if run_ in (0, 2):
                        vowel_first.append(len(ids))
                        run_ = 1 if run_ == 2 else run_
                    run_ += 1
                elif ch == "ː" or ch not in pf.IPA_KEEP:
                    run_ = 0
                if ch in self.ids:
                    ids += self.ids[ch] + [0]
            following = text[ends[k]:ends[k + 1] if k + 1 < len(ends) else len(text)]
            for ch in following:
                if ch in ",.!?;:" and ch in self.ids:
                    ids += self.ids[ch] + [0]
            ids += self.ids[" "] + [0]
        ids.append(self.ids["$"][0])
        inference = self.config["inference"]
        audio, lengths = self.session.run(None, {
            "input": np.array([ids], dtype=np.int64),
            "input_lengths": np.array([len(ids)], dtype=np.int64),
            "scales": np.array([inference["noise_scale"], speed * inference["length_scale"], inference["noise_w"]],
                               dtype=np.float32),
            "sid": np.array([speaker], dtype=np.int64)})
        audio, lengths = audio.reshape(-1), lengths.reshape(-1)
        starts = np.concatenate([[0], np.cumsum(lengths)]) * HOP / self.rate
        pcm = (np.clip(audio / max(1e-6, float(np.abs(audio).max())) * 0.9, -1, 1) * 32767).astype(np.int16).tobytes()
        return pcm, [float(starts[i]) for i in word_first], [float(starts[i]) for i in vowel_first]


def streamed(pcm, rate, timing, count):
    marks = pf.SyllableMarks(rate, timing)
    out = []
    step = int(rate * 0.1) * 2
    for i in range(0, len(pcm), step):
        out += marks.feed(pcm[i:i + step])
    out += marks.flush()
    pos, got = 0, [None] * count
    for x in out:
        if isinstance(x, tuple):
            if got[x[1]] is None:
                got[x[1]] = pos // 2
        else:
            pos += len(x)
    following = pos // 2           # a syllable never marked on its own shows with the next mark
    for k in range(count - 1, -1, -1):
        got[k] = following if got[k] is None else got[k]
        following = got[k]
    return got


def report(name, errors):
    a = sorted(abs(e) for e in errors)
    print("%-26s %4d marks: median %.3f s, 90%% within %.3f s, %d%% within 0.1 s, on average %+.3f s"
          % (name, len(a), statistics.median(a), a[int(0.9 * len(a))],
             round(100 * sum(e <= 0.1 for e in a) / len(a)), statistics.mean(errors)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("voice", help="a Piper voice folder (the .onnx model and its .onnx.json)")
    parser.add_argument("--speakers", default="0,7,23,61,140,333", help="speaker numbers, for voices with several")
    parser.add_argument("--speeds", default="0.85,1,1.2", help="length scales (above 1 is slower)")
    args = parser.parse_args()
    voice = Voice(args.voice)
    speakers = [int(s) for s in args.speakers.split(",")]
    if voice.config.get("num_speakers", 1) <= 1:
        speakers = [0]
    errors = {"whole": ([], []), "streamed": ([], [])}
    for speaker in speakers:
        for speed in (float(s) for s in args.speeds.split(",")):
            for text in SENTENCES:
                pcm, word_starts, vowel_starts = voice.speak(text, speaker, speed)
                plan = pf.Planner(random.Random(1)).plan(text, ())
                count = len(plan["syllables"])
                if count != len(vowel_starts):
                    print("skipped (syllables differ):", text)
                    continue
                firsts, n = [], 0
                for shapes in pf.word_shapes(pf.WORD.findall(text)):
                    firsts.append(n)
                    n += len(shapes)
                placed = {"whole": pf.syllable_offsets(pcm, voice.rate, plan["timing"]),
                          "streamed": streamed(pcm, voice.rate, plan["timing"], count)}
                for way, offsets in placed.items():
                    errors[way][0].extend(offsets[k] / voice.rate - w for k, w in zip(firsts, word_starts))
                    errors[way][1].extend(o / voice.rate - v for o, v in zip(offsets, vowel_starts))
    for way, (words, vowels) in errors.items():
        report(way + ", vowels", vowels)
        report(way + ", word starts", words)


if __name__ == "__main__":
    main()
