"""Stand-ins for providers, the stage and the speaker, for tests and the virtual device."""
import asyncio
import array
import math

from companion.providers import ProviderError


class FakeLLM:
    def __init__(self, reply="Hello there. How are you today?", pieces=7, delay=0.0, fail=None, hang=False):
        self.reply = reply
        self.pieces = pieces
        self.delay = delay
        self.fail = fail
        self.hang = hang
        self.calls = []

    async def stream(self, system, messages):
        self.calls.append((system, list(messages)))
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail == "start":
            raise ProviderError("the fake model failed", retry=True)
        step = max(1, len(self.reply) // self.pieces)
        for i in range(0, len(self.reply), step):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield self.reply[i:i + step]
            if self.fail == "middle" and i > len(self.reply) // 2:
                raise ProviderError("the fake model broke off")


class FakeTTS:
    rate = 24000

    def __init__(self, seconds_per_char=0.01, fail_on=None):
        self.seconds_per_char = seconds_per_char
        self.fail_on = fail_on
        self.texts = []

    async def stream(self, text):
        if self.fail_on and self.fail_on in text:
            raise ProviderError("the fake voice failed")
        self.texts.append(text)
        n = int(self.rate * self.seconds_per_char * len(text))
        samples = array.array("h", (int(8000 * math.sin(i / 7.0)) for i in range(n)))
        data = samples.tobytes()
        for i in range(0, len(data), 4800):
            yield data[i:i + 4800]
            await asyncio.sleep(0)


class FakeStage:
    def __init__(self):
        self.commands = []
        self.params = set()

    def send(self, command):
        self.commands.append(command)

    def state(self, name):
        self.commands.append({"state": name})

    def mouth(self, level):
        self.commands.append({"mouth": level})

    def express(self, emotion, ease=0.35):
        self.commands.append({"express": emotion})

    def blink(self):
        self.commands.append({"blink": True})

    def states(self):
        return [c["state"] for c in self.commands if "state" in c]
