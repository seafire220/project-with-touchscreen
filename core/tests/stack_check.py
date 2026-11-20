"""Run the real core against the real stage, with stand-in AI providers, and record what the stage shows.

    python tests/stack_check.py STAGE_BINARY PUPPET.inp OUT_DIR [STAGE OPTIONS ...]

Starts the stage on a virtual display with its command socket, connects the
core to it, tells it the time of day, has it listen to a person speaking (a
stand-in voice level, in stretches with pauses), then answer a typed message
(stand-in model and voice, real timing), then stay alone for a while, and
saves frames from the start, ten a second. Prints the stage states seen in
its heartbeats, the moods and gestures the stage played (with what started
each: the words, a command, listening, a reaction, idle), and its drives,
and fails if any mood or gesture tagged in the reply (and available to the
character) did not play, if it did not look up as the person started
speaking, or if it never responded in their pauses. Needs Xvfb. With
COMPANION_TEST_VOICE set to an on-device voice folder, the reply is spoken
by that voice instead of a stand-in, so the mouth follows real speech. With COMPANION_TEST_CAPTIONS
set, captions are shown as the device shows them (core/companion/overlays.py), and the check fails if
the stage did not show them. Options after OUT_DIR go to the stage (for a 3D avatar's full-body style:
--vrm-animation full).
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion.audio import Speaker  # noqa: E402
from companion.conversation import Conversation  # noqa: E402
from companion.memory import Memory  # noqa: E402
from companion.stage_link import StageLink  # noqa: E402
from fakes import FakeLLM, FakeTTS  # noqa: E402

REPLY = ("[happy] [wave] Hello! It is lovely to meet you, and I am glad you came to talk with me today. "
         "[thinking] Let me think about what we could talk about first. "
         "[surprised] Oh, I know! [happy] [nod] Tell me about your day. "
         "[embarrassed] Sorry, I get a little excited when someone new visits.")


async def main(stage, puppet, out, *options):
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp()
    sock = os.path.join(work, "stage.sock")
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "800x1000x24"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    env = dict(os.environ, DISPLAY=":" + xvfb.stdout.readline().strip(), LIBGL_ALWAYS_SOFTWARE="1")
    captures = [round(1.0 + 0.1 * i, 1) for i in range(150)]
    proc = subprocess.Popen([stage, puppet, "--size", "360x640", "--gl", "es", "--no-stdin", "--socket", sock,
                             "--capture-dir", out, "--capture-at", ",".join(map(str, captures)), "--exit-after", "48",
                             *options],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen = []
    link = StageLink(sock, on_event=lambda e: seen.append(e))
    link.start()
    try:
        for _ in range(100):
            if any(e.get("event") == "ready" for e in seen):
                break
            await asyncio.sleep(0.1)
        ready = next(e for e in seen if e.get("event") == "ready")
        voice = os.environ.get("COMPANION_TEST_VOICE")
        if voice:
            from companion.providers import LocalTTS
            tts = LocalTTS(voice)
        else:
            tts = FakeTTS(seconds_per_char=0.03)
        overlays = None
        if os.environ.get("COMPANION_TEST_CAPTIONS"):
            from companion.overlays import Overlays
            overlays = Overlays(os.path.join(work, "overlays"), link)       # the stage's folder, beside its socket
            overlays.screen = (int(ready.get("width") or 360), int(ready.get("height") or 640))
        conv = Conversation(llm=FakeLLM(REPLY, delay=0.02), tts=tts,
                            speaker=Speaker(command=None, realtime=True), stage=link,
                            memory=Memory(os.path.join(work, "memory")), persona="# Test\n\nYou are a test.",
                            on_caption=overlays.caption if overlays else None)
        link.clock(15.0)                         # mid-afternoon: awake
        await asyncio.sleep(3.0)                 # the stage settles; frame 0 is at rest
        # The person speaks for six seconds, in stretches with pauses, while it listens.
        link.state("listening")
        await asyncio.sleep(1.8)
        for i in range(300):
            link.heard(0.55 if (i % 85) < 60 else 0.02)
            await asyncio.sleep(0.02)
        link.state("thinking")
        reply = await conv.respond("hello")
        if overlays:
            overlays.caption_done()
        await asyncio.sleep(12.0)                # then alone a while
    finally:
        await asyncio.sleep(0.5)
        proc.wait(timeout=30)
        xvfb.terminate()
    states = []
    for e in seen:
        if e.get("event") == "heartbeat" and (not states or states[-1] != e["state"]):
            states.append(e["state"])
    from companion.speech_text import EMOTIONS, GESTURES
    import re
    tags = re.findall(r"\[(\w+)\]", REPLY)
    wanted_moods = {t for t in tags if t in EMOTIONS}
    wanted_gestures = {t for t in tags if t in GESTURES and t in ready.get("gestures", [])}
    moods = [e["emotion"] for e in seen if e.get("event") == "emotion"]
    gestures = [(e["name"], e["cause"]) for e in seen if e.get("event") == "gesture"]
    mouth = [e for e in seen if e.get("event") == "heartbeat"]
    drives = [e.get("drives") for e in mouth if e.get("drives")]
    report = {"puppet": ready.get("puppet"), "format": ready.get("format"), "params": len(ready.get("param_names", [])),
              "voice": "on-device" if os.environ.get("COMPANION_TEST_VOICE") else "stand-in",
              "gestures_available": ready.get("gestures"), "actions_available": ready.get("actions"),
              "states_seen": states, "moods_played": moods,
              "gestures_played": gestures, "spoken": reply.spoken, "error": reply.error,
              "drives_first_and_last": [drives[0], drives[-1]] if drives else None,
              "skipped": [(e["name"], e.get("why")) for e in seen if e.get("event") == "gesture_skipped"],
              "errors_from_stage": [e for e in seen if e.get("event") in ("error", "fatal")],
              "captions_shown": sum(1 for e in mouth if "caption" in (e.get("overlays") or []))}
    print(json.dumps(report, indent=1))
    missing = (wanted_moods - set(moods)) | (wanted_gestures - {g for g, _ in gestures})
    if missing:
        print("not played:", sorted(missing))
    looked_up = ("look_up", "reaction") in gestures
    responded = any(cause == "listening" for _, cause in gestures)
    if not looked_up:
        print("it did not look up as the person started speaking")
    if not responded:
        print("it never responded in the person's pauses")
    clocked = bool(drives) and abs(drives[-1].get("hour", 0) - 15.0) < 0.2
    captioned = not os.environ.get("COMPANION_TEST_CAPTIONS") or report["captions_shown"] > 0
    if not captioned:
        print("no caption was shown")
    ok = (not reply.error and "speaking" in states and not report["errors_from_stage"] and not missing
          and looked_up and responded and clocked and captioned)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(*sys.argv[1:])))
