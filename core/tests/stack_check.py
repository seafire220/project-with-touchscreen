"""Run the real core against the real stage, with stand-in AI providers, and record what the stage shows.

    python tests/stack_check.py STAGE_BINARY PUPPET.inp OUT_DIR

Starts the stage on a virtual display with its command socket, connects the
core to it, has the character answer a typed message (stand-in model and
voice, real timing), and saves frames before, during and after the reply.
Prints the stage states seen in its heartbeats. Needs Xvfb.
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

REPLY = ("[happy] [nod] Hello! It is lovely to meet you, and I am glad you came to talk with me today. "
         "[embarrassed] Shall we chat for a while about anything you like?")


async def main(stage, puppet, out):
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp()
    sock = os.path.join(work, "stage.sock")
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "800x1000x24"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    env = dict(os.environ, DISPLAY=":" + xvfb.stdout.readline().strip(), LIBGL_ALWAYS_SOFTWARE="1")
    captures = [1.5, 4.0, 4.6, 5.2, 5.8, 6.4, 12.0]
    proc = subprocess.Popen([stage, puppet, "--size", "360x640", "--gl", "es", "--no-stdin", "--socket", sock,
                             "--capture-dir", out, "--capture-at", ",".join(map(str, captures)), "--exit-after", "12.5"],
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
        conv = Conversation(llm=FakeLLM(REPLY, delay=0.02), tts=FakeTTS(seconds_per_char=0.03),
                            speaker=Speaker(command=None, realtime=True), stage=link,
                            memory=Memory(os.path.join(work, "memory")), persona="# Test\n\nYou are a test.")
        await asyncio.sleep(3.0)                 # the stage settles; frame 0 is at rest
        reply = await conv.respond("hello")
        await asyncio.sleep(6.5)
    finally:
        await asyncio.sleep(0.5)
        proc.wait(timeout=30)
        xvfb.terminate()
    states = []
    for e in seen:
        if e.get("event") == "heartbeat" and (not states or states[-1] != e["state"]):
            states.append(e["state"])
    report = {"puppet": ready.get("puppet"), "params": len(ready.get("param_names", [])),
              "states_seen": states, "spoken": reply.spoken, "error": reply.error,
              "errors_from_stage": [e for e in seen if e.get("event") in ("error", "fatal")]}
    print(json.dumps(report, indent=1))
    return 0 if not reply.error and "speaking" in states and not report["errors_from_stage"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(*sys.argv[1:4])))
