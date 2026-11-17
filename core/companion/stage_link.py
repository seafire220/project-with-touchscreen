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
# names: the face, and posture through the head and body (gentle, because
# large bends show what the picture never drew). Parameters a puppet lacks
# are skipped, so a character missing a part still shows the rest. A
# character's behaviour.json can replace these.
EXPRESSIONS = {
    "neutral": {},
    "happy": {"ParamMouthForm": 1.0, "ParamEyeLSmile": 0.5, "ParamEyeRSmile": 0.5, "ParamAngleZ": 4.0,
              "ParamBodyAngleY": 2.0},
    "sad": {"ParamMouthForm": -0.8, "ParamBrowLY": -0.6, "ParamBrowRY": -0.6, "ParamAngleY": -12.0,
            "ParamBodyAngleY": -3.0},
    "angry": {"ParamMouthForm": -0.6, "ParamBrowLForm": -1.0, "ParamBrowRForm": -1.0, "ParamAngleY": -5.0,
              "ParamBodyAngleY": 3.0},
    "surprised": {"ParamBrowLY": 1.0, "ParamBrowRY": 1.0, "ParamAngleY": 8.0, "ParamBodyAngleY": 2.0},
    "embarrassed": {"ParamCheek": 1.0, "ParamMouthForm": 0.3, "ParamAngleY": -14.0, "ParamAngleX": 10.0,
                    "ParamBodyAngleZ": 3.0, "ParamEyeLSmile": 0.3, "ParamEyeRSmile": 0.3},
    "thinking": {"ParamBrowLY": 0.3, "ParamBrowRY": -0.2, "ParamAngleZ": 8.0, "ParamAngleX": -8.0},
}

# Short movements: (seconds from start, {parameter: value}); the last step
# hands the parameters back to the idle movement.
GESTURES = {
    "nod": [(0.0, {"ParamAngleY": -14.0}), (0.22, {"ParamAngleY": 4.0}), (0.42, {"ParamAngleY": -10.0}),
            (0.62, {"ParamAngleY": 0.0}), (0.8, None)],
    "shake": [(0.0, {"ParamAngleX": -12.0}), (0.2, {"ParamAngleX": 12.0}), (0.4, {"ParamAngleX": -10.0}),
              (0.6, {"ParamAngleX": 8.0}), (0.8, {"ParamAngleX": 0.0}), (0.95, None)],
    "bow": [(0.0, {"ParamBodyAngleY": -10.0, "ParamAngleY": -22.0}), (1.2, {"ParamBodyAngleY": 0.0, "ParamAngleY": 0.0}),
            (1.7, None)],
    "tilt": [(0.0, {"ParamAngleZ": 14.0, "ParamAngleX": -6.0}), (1.4, None)],
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

    def gesture(self, name):
        """Play a short movement; returns the task, or None if unknown. Parameters the puppet lacks are skipped."""
        steps = GESTURES.get(name)
        if not steps:
            return None
        return asyncio.ensure_future(self._play(steps))

    async def _play(self, steps):
        known = (lambda n: n in self.params) if self.params else (lambda n: True)
        loop = asyncio.get_running_loop()
        start = loop.time()
        names = {n for _, values in steps if values for n in values if known(n)}
        for at, values in steps:
            await asyncio.sleep(max(0.0, start + at - loop.time()))
            if values is None:
                # Back to the current emotion's pose, or to the idle movement.
                pose = self.expressions.get(self.expression, {})
                command = {n: pose.get(n) for n in names}
            else:
                command = {n: v for n, v in values.items() if known(n)}
            if command:
                self.send({"set": command, "ease": 0.18})

    def load(self, puppet_path):
        """Ask the stage to show another character (the stage is restarted with it by the service manager)."""
        self.send({"quit": True})
