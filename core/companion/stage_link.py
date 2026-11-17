"""The connection to the stage program that draws the character.

Commands go out as JSON lines on the stage's local socket; events (ready,
heartbeat, errors) come back the same way. If the stage restarts, the link
reconnects and the core carries on.
"""
import asyncio
import json
import logging

log = logging.getLogger("companion.stage")

# Parameter settings for each emotion, for puppets with the usual parameter
# names. Parameters a puppet lacks are skipped. A character's behaviour.json
# can replace these.
EXPRESSIONS = {
    "neutral": {},
    "happy": {"ParamMouthForm": 1.0, "ParamEyeLSmile": 0.5, "ParamEyeRSmile": 0.5},
    "sad": {"ParamMouthForm": -0.8, "ParamBrowLY": -0.6, "ParamBrowRY": -0.6},
    "angry": {"ParamMouthForm": -0.6, "ParamBrowLForm": -1.0, "ParamBrowRForm": -1.0},
    "surprised": {"ParamBrowLY": 1.0, "ParamBrowRY": 1.0},
    "embarrassed": {"ParamCheek": 1.0, "ParamMouthForm": 0.3},
    "thinking": {"ParamBrowLY": 0.3, "ParamBrowRY": -0.2},
}


class StageLink:
    def __init__(self, socket_path, on_event=None):
        self.socket_path = socket_path
        self.on_event = on_event
        self.writer = None
        self.params = set()
        self.expression = "neutral"
        self.expressions = dict(EXPRESSIONS)
        self._task = None

    def start(self):
        self._task = asyncio.ensure_future(self._run())

    async def _run(self):
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(self.socket_path)
            except OSError:
                await asyncio.sleep(1.0)
                continue
            self.writer = writer
            log.info("connected to the stage")
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("event") == "ready":
                        self.params = set(event.get("param_names") or [])
                    if self.on_event:
                        self.on_event(event)
            except (OSError, asyncio.IncompleteReadError):
                pass
            self.writer = None
            log.warning("lost the stage; reconnecting")
            await asyncio.sleep(0.5)

    def send(self, command):
        if self.writer is None:
            return False
        try:
            self.writer.write((json.dumps(command) + "\n").encode())
        except (OSError, RuntimeError):
            self.writer = None
            return False
        return True

    def state(self, name):
        self.send({"state": name})

    def mouth(self, level):
        self.send({"mouth": round(float(level), 3)})

    def blink(self):
        self.send({"blink": True})

    def express(self, emotion, ease=0.35):
        """Show an emotion; parameters the puppet lacks are left out."""
        if emotion == self.expression:
            return
        wanted = self.expressions.get(emotion, {})
        previous = self.expressions.get(self.expression, {})
        known = (lambda n: n in self.params) if self.params else (lambda n: True)
        command = {n: v for n, v in wanted.items() if known(n)}
        for name in previous:
            if name not in command and known(name):
                command[name] = None
        self.expression = emotion
        if command:
            self.send({"set": command, "ease": ease})

    def load(self, puppet_path):
        """Ask the stage to show another character (the stage is restarted with it by the service manager)."""
        self.send({"quit": True})
