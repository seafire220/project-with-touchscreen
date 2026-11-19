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
        self.param_info = []        # [{"name", "min", "max", "default"}], from the stage when it is ready
        self.controls = []          # [{"control", "param", "min", "max", "rest"}]: what drives what now
        self.expression = "neutral"
        # What the character can do, as the stage reports when it is ready.
        self.emotions = []
        self.gestures = list(DEFAULT_GESTURES)
        self.strokes = {}           # gesture: seconds in that it lands
        self.actions = []           # idle actions it can make
        self.disabled = set()       # gestures and idle actions the owner switched off for this character
        self.library = None         # the whole library, when asked for (describe_library)
        self._library_ready = None
        # For a character with its own expressions: which one shows each emotion.
        self.emotion_map = {}
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
                        self.expression = "neutral"            # a new stage starts at rest
                        self.params = set(event.get("param_names") or [])
                        self.param_info = list(event.get("param_info") or [])
                        self.controls = list(event.get("controls") or [])
                        self.emotions = list(event.get("emotions") or [])
                        if "gestures" in event:
                            self.gestures = list(event.get("gestures") or [])
                        # When each gesture lands, so the speech planner starts it in time for its word.
                        self.strokes = dict(event.get("strokes") or {})
                        self.actions = list(event.get("actions") or [])
                    if event.get("event") == "library":
                        # The library changed (a gesture defined or put back), or was asked for.
                        self.gestures = list(event.get("gestures") or [])
                        self.actions = list(event.get("actions") or [])
                        self.strokes = dict(event.get("strokes") or {})
                        if "clips" in event:
                            self.library = {"clips": event["clips"], "controls": event.get("controls") or []}
                            if self._library_ready is not None:
                                self._library_ready.set()
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

    def perform(self, performance):
        """A sentence starts: its syllables' mouth shapes and the movements tied to them."""
        self.send({"perform": performance})

    def syllable(self, k):
        self.send({"syllable": int(k)})

    def blink(self):
        self.send({"blink": True})

    def express(self, emotion, intensity=1.0):
        """Change the character's mood: how it moves, its face, and the gestures it makes by itself."""
        if emotion == self.expression:
            return
        self.expression = emotion
        command = {"emotion": emotion, "intensity": round(float(intensity), 2)}
        if self.emotion_map:
            command["expression"] = self.emotion_map.get(emotion)    # None hands the face back to the mood
        self.send(command)

    def gesture(self, name, intensity=1.0):
        """Play one of the stage's gestures, if this character can make it."""
        if name not in self.gestures:
            return False
        return self.send({"gesture": name, "intensity": round(float(intensity), 2)})

    def random_gestures(self, on):
        """Let the mood start gestures by itself, or not."""
        self.send({"random_gestures": bool(on)})

    def temperament(self, energy, expressiveness):
        """How lively and how expressive the character is (1 usual, 0.6 to 1.4)."""
        self.send({"temperament": {"energy": round(float(energy), 2), "expressiveness": round(float(expressiveness), 2)}})

    def gestures_off(self, names):
        """Gestures and idle actions the character never starts by itself."""
        self.disabled = set(names)
        self.send({"gestures_off": sorted(self.disabled)})

    def define(self, name, entry):
        """Add a gesture or idle action to the stage's library, or change one."""
        return self.send({"define": dict(entry, name=name)})

    def undefine(self, name):
        """Put a changed gesture back as built, or take an added one away."""
        return self.send({"undefine": name})

    async def describe_library(self, timeout=3.0):
        """The stage's whole library ({"clips", "controls"}), or None if the stage does not answer."""
        self._library_ready = asyncio.Event()
        if not self.send({"describe": True}):
            return None
        try:
            await asyncio.wait_for(self._library_ready.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return self.library

    def clock(self, hour):
        """The local time of day, in hours: the character is livelier in the morning and sleepy at night."""
        self.send({"clock": round(float(hour) % 24.0, 3)})

    def poke(self):
        """Someone is there (the button was pressed): a dozing character wakes, a lonely one brightens."""
        self.send({"poke": True})

    def heard(self, level):
        """How loud the person speaking is, 0 to 1, while the character listens."""
        self.send({"heard": round(min(1.0, max(0.0, float(level))), 3)})

    def load(self, puppet_path):
        """Ask the stage to show another character (the stage is restarted with it by the service manager)."""
        self.send({"quit": True})


# The stage's motion controls, in the order the movement settings show them, with plain names.
CONTROLS = (
    ("head_yaw", "Head turn"), ("head_pitch", "Head nod"), ("head_roll", "Head tilt"),
    ("body_yaw", "Body turn"), ("body_pitch", "Body lean"), ("body_roll", "Body sway"),
    ("gaze_x", "Eyes left and right"), ("gaze_y", "Eyes up and down"),
    ("arm_left", "Left arm"), ("arm_right", "Right arm"), ("arm_left_b", "Left elbow"), ("arm_right_b", "Right elbow"),
    ("shoulders", "Shoulders"), ("smile", "Mouth shape (smile)"), ("brow_left", "Left brow"), ("brow_right", "Right brow"),
    ("brow_form_left", "Left brow shape"), ("brow_form_right", "Right brow shape"),
    ("eye_smile_left", "Left eye smile"), ("eye_smile_right", "Right eye smile"), ("cheek", "Blush"),
    ("mouth_open", "Mouth open"), ("blink_left", "Left eye open"), ("blink_right", "Right eye open"),
    ("breath", "Breathing"),
)
CONTROL_NAMES = dict(CONTROLS)
