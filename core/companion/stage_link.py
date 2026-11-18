"""The connection to the stage program that draws the character.

Commands go out as JSON lines on the stage's local socket; events (ready,
heartbeat, errors) come back the same way. If the stage restarts, the link
reconnects and the core carries on.
"""
import asyncio
import json
import logging

log = logging.getLogger("companion.stage")

# The stage owns the animation (stage/src/motion.rs, stage/motions/library.json):
# an emotion is a mood that changes how the character moves and looks, and a
# gesture is a short movement added on top of whatever it is doing. The core
# only names them, in step with the speech.
DEFAULT_GESTURES = ("nod", "shake", "bow", "tilt")


class StageLink:
    def __init__(self, socket_path, on_event=None):
        self.socket_path = socket_path
        self.on_event = on_event
        self.writer = None
        self.params = set()
        self.expression = "neutral"
        # What the character can do, as the stage reports when it is ready.
        self.emotions = []
        self.gestures = list(DEFAULT_GESTURES)
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
                        self.emotions = list(event.get("emotions") or [])
                        if "gestures" in event:
                            self.gestures = list(event.get("gestures") or [])
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

    def express(self, emotion, intensity=1.0):
        """Change the character's mood: how it moves, its face, and the gestures it makes by itself."""
        if emotion == self.expression:
            return
        self.expression = emotion
        self.send({"emotion": emotion, "intensity": round(float(intensity), 2)})

    def gesture(self, name, intensity=1.0):
        """Play one of the stage's gestures, if this character can make it."""
        if name not in self.gestures:
            return False
        return self.send({"gesture": name, "intensity": round(float(intensity), 2)})

    def random_gestures(self, on):
        """Let the mood start gestures by itself, or not."""
        self.send({"random_gestures": bool(on)})

    def load(self, puppet_path):
        """Ask the stage to show another character (the stage is restarted with it by the service manager)."""
        self.send({"quit": True})
