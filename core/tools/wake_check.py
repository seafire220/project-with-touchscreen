"""How well the wake word works, measured with the device's own voices.

    python3 core/tools/wake_check.py --wake MODEL_DIR --voice VOICE_DIR [--name Mika] [--voices 40]

The device's voice (Piper LibriTTS-R, 904 speakers) says the wake phrases ("hey Mika", "hi Mika", "hello
Mika", and "hey Mika" followed by a question) in many voices, over a little room noise; and everyday
sentences that must not wake it, among them near misses ("hey Mike", "hi Mia") and the name without a
greeting. For each sensitivity it prints how many phrases were heard, how often everyday speech woke it
(per hour of speech), and how much of one processor core listening takes.

Synthetic speech is cleaner than a room, so treat the numbers as a first check: try it on the device too
(docs/15-hardware-test-plan.md).
"""
import argparse
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from companion import wakeword  # noqa: E402
from companion.providers import LocalTTS  # noqa: E402

EVERYDAY = [
    "Could you set a timer for ten minutes please?", "I made pancakes this morning and burnt the first one.",
    "What's the weather going to be like tomorrow?", "My sister called me after lunch.",
    "Hey Mike, did you see the game last night?", "Hi Mia, how was school today?", "Hello Micah, nice to meet you.",
    "Mika is my favourite character in the show.", "I told Mika about the trip yesterday.",
    "Hey, look at that bird on the fence.", "Hello everyone, dinner is ready.", "Hi there, can I help you?",
    "Have you seen my car keys anywhere?", "Monica is coming over on Saturday.", "We should paint the kitchen blue.",
    "The microphone on my laptop stopped working.", "Mick and Kate are getting married in June.",
    "This rock has flakes of mica in it.", "Turn left at the next roundabout.", "Can you remind me to call the dentist?",
    "I think it might rain later today.", "The kids are playing in the garden.", "Put the milk back in the fridge.",
    "That film was much better than I expected.", "Let's go for a walk after dinner.", "My meeting ran over again.",
    "Hey Jude, don't make it bad.", "Hi, my name is Sam.", "Hello, is anybody home?", "Mikey likes it.",
    "She bought a new bike for the summer.", "Could you turn the music down a little?", "The train was late this morning.",
    "I need to finish my homework first.", "Good night, sleep well.", "What a lovely day it is today.",
    "Make a cup of tea for me, would you?", "My cat knocked a glass off the table.", "We're out of bread again.",
    "The neighbours are having a party tonight.",
]


def resample(pcm, rate, to=16000):
    """16-bit sound at `rate` as 16-bit sound at `to` (linear interpolation; speech has little above 8 kHz)."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if rate == to or not len(x):
        return x
    t = np.arange(int(len(x) * to / rate)) * (rate / to)
    return np.interp(t, np.arange(len(x)), x)


def clip(samples, rng, noise_db=-55.0, before=0.4, after=0.6):
    """Speech with silence around it and a little room noise, as 16-bit bytes at 16 kHz."""
    gain = 10 ** (rng.uniform(-8, 0) / 20)
    pad = lambda s: np.zeros(int(16000 * s), dtype=np.float32)  # noqa: E731
    x = np.concatenate([pad(before), samples * gain, pad(after)])
    x = x + rng.normal(0, 32768 * 10 ** (noise_db / 20), len(x))
    return np.clip(x, -32768, 32767).astype(np.int16).tobytes()


def listen(spotter, pcm):
    """What a wake-word listener hears in `pcm`, fed 20 ms at a time as the device does."""
    spotter.reset()
    heard = []
    for i in range(0, len(pcm), 640):
        found = spotter.feed(pcm[i:i + 640])
        if found:
            heard.append(found)
    return heard


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wake", required=True, help="the wake-word model's folder")
    parser.add_argument("--voice", required=True, help="the on-device voice's folder")
    parser.add_argument("--name", default="Mika")
    parser.add_argument("--voices", type=int, default=40, help="how many of the voice's speakers to use")
    parser.add_argument("--everyday-voices", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    rng = np.random.default_rng(args.seed)
    tts = LocalTTS(args.voice, threads=2)
    speakers = sorted(random.Random(args.seed).sample(range(tts.speakers), max(args.voices, args.everyday_voices)))
    name = args.name

    def say(text, sid):
        tts.sid = sid
        return resample(tts._speak(text), tts.rate)

    started = time.time()
    wanted = ["Hey %s." % name, "Hi %s!" % name, "Hello %s." % name, "Hey %s, what time is it?" % name]
    positives = [clip(say(text, sid), rng) for sid in speakers[:args.voices] for text in wanted]
    everyday = [clip(say(text, sid), rng, before=0.2, after=0.3)
                for sid in speakers[:args.everyday_voices] for text in EVERYDAY]
    speech_hours = sum(len(p) for p in everyday) / 2 / 16000 / 3600
    print("Made %d wake phrases and %.0f minutes of everyday speech in %.0f s" % (
        len(positives), speech_hours * 60, time.time() - started))
    print()
    print("| Sensitivity | Wake phrases heard | Woken by everyday speech | Of that, near misses | Processor (one core) |")
    print("|---|---|---|---|---|")
    for level in ("low", "normal", "high"):
        spotter = wakeword.WakeWord(args.wake, wakeword.phrases(name), level)
        took, audio = 0.0, 0.0
        heard = 0
        for pcm in positives:
            t = time.time()
            heard += bool(listen(spotter, pcm))
            took += time.time() - t
            audio += len(pcm) / 32000
        false, near = 0, 0
        for i, pcm in enumerate(everyday):
            t = time.time()
            woke = listen(spotter, pcm)
            took += time.time() - t
            audio += len(pcm) / 32000
            if woke:
                false += 1
                text = EVERYDAY[i % len(EVERYDAY)]
                near += any(w in text for w in ("Mike", "Mia", "Micah", "Mika", "Mikey", "mica"))
                print("  %s: woken by %r (%s)" % (level, text, woke[0]), file=sys.stderr)
        print("| %s | %d of %d (%.0f%%) | %d times: %.1f an hour of speech | %d | %.1f%% |" % (
            level, heard, len(positives), 100.0 * heard / len(positives), false, false / speech_hours, near,
            100.0 * took / audio))


if __name__ == "__main__":
    main()
