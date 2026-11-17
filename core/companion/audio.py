"""Sound in and out.

The device plays and records through small external programs (PipeWire's
pw-play and pw-record, or ALSA's aplay and arecord), fed 16-bit mono PCM.
This keeps audio libraries out of the core and lets the hardware change
without code changes.

While playing, the loudness of each 20 ms of sound is reported at the moment
that sound is heard, which is what moves the character's mouth.
"""
import asyncio
import math
import shutil

FRAME = 0.02            # seconds per loudness reading
LEAD = 0.12             # how far ahead of the speaker audio is written
OUTPUT_LATENCY = 0.06   # time from writing audio to hearing it (measured per device later)


def loudness(frame):
    """16-bit PCM -> mouth openness 0..1 (about -50 dBFS silent, -15 dBFS wide open)."""
    count = len(frame) // 2
    if count == 0:
        return 0.0
    import array
    samples = array.array("h", frame[:count * 2])
    power = sum(s * s for s in samples) / count
    if power <= 0:
        return 0.0
    db = 10 * math.log10(power / (32768.0 ** 2))
    return max(0.0, min(1.0, (db + 50.0) / 35.0))


def player_command(rate):
    if shutil.which("pw-play"):
        return ["pw-play", "--rate", str(rate), "--channels", "1", "--format", "s16", "-"]
    if shutil.which("aplay"):
        return ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", "1", "-"]
    return None


def recorder_command(rate):
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", str(rate), "--channels", "1", "--format", "s16", "-"]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", "1", "-"]
    return None


class Speaker:
    """Plays PCM in real time and reports loudness in step with the sound.

    With no player program (tests, the virtual device in a browser) it keeps
    the same timing and simply makes no sound; `on_audio` then receives the
    sound instead.
    """

    def __init__(self, command=player_command, latency=OUTPUT_LATENCY, realtime=True):
        self.command = command
        self.latency = latency
        self.realtime = realtime
        self.process = None
        self.stopped = False
        self.volume = 1.0

    async def play(self, chunks, rate, on_level, on_audio=None):
        """Play an async stream of PCM chunks. Returns seconds played."""
        loop = asyncio.get_running_loop()
        frame_bytes = int(rate * FRAME) * 2
        cmd = self.command(rate) if self.command else None
        self.stopped = False
        self.process = None
        if cmd:
            self.process = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL)
        start, index, pending = None, 0, b""
        timers = []
        try:
            async for chunk in chunks:
                if self.stopped:
                    break
                pending += chunk
                while len(pending) >= frame_bytes and not self.stopped:
                    frame, pending = pending[:frame_bytes], pending[frame_bytes:]
                    frame = self._scale(frame)
                    now = loop.time()
                    if start is None or start + index * FRAME < now - 0.05:
                        start = now - index * FRAME      # first frame, or the sound ran dry: restart the clock
                    due = start + index * FRAME
                    if self.realtime and due - LEAD > now:
                        await asyncio.sleep(due - LEAD - now)
                    if self.process:
                        try:
                            self.process.stdin.write(frame)
                            await self.process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError):
                            self.process = None
                    if on_audio:
                        on_audio(frame)
                    level = loudness(frame)
                    if self.realtime:
                        timers.append(loop.call_at(due + self.latency, on_level, level))
                    else:
                        on_level(level)
                    index += 1
            if start is not None and self.realtime and not self.stopped:
                await asyncio.sleep(max(0.0, start + index * FRAME + self.latency - loop.time()))
        finally:
            if self.stopped:
                for t in timers:
                    t.cancel()
            await self._close()
            on_level(0.0)
        return index * FRAME

    def _scale(self, frame):
        if self.volume >= 0.999:
            return frame
        import array
        samples = array.array("h", frame)
        v = max(0.0, self.volume)
        for i, s in enumerate(samples):
            samples[i] = int(s * v)
        return samples.tobytes()

    async def _close(self):
        p, self.process = self.process, None
        if p is None:
            return
        if self.stopped:
            p.kill()
        else:
            try:
                p.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass
        try:
            await asyncio.wait_for(p.wait(), 2.0)
        except asyncio.TimeoutError:
            p.kill()

    def stop(self):
        """Stop at once (the character was interrupted)."""
        self.stopped = True
        if self.process:
            self.process.kill()


async def tone(rate=24000, seconds=0.25, pitch=660.0, level=0.25):
    """A short tone as one PCM chunk, for notices when the voice service fails."""
    import array
    n = int(rate * seconds)
    fade = int(rate * 0.02)
    samples = array.array("h")
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade)
        samples.append(int(32767 * level * env * math.sin(2 * math.pi * pitch * i / rate)))
    yield samples.tobytes()


class Detector:
    """Finds where speech starts and ends in 20 ms frames, by loudness against the room's noise.

    Simple and free of models. A neural detector can replace it behind the
    same two calls.
    """

    def __init__(self, end_silence=0.8, max_turn=30.0, rate=16000):
        self.rate = rate
        self.end_frames = max(5, int(end_silence / FRAME))
        self.max_frames = int(max_turn / FRAME)
        self.noise = -60.0
        self.reset()

    def reset(self):
        self.speaking = False
        self.voiced_run = 0
        self.silent_run = 0
        self.frames = []
        self.preroll = []

    def _db(self, frame):
        count = len(frame) // 2
        if count == 0:
            return -100.0
        import array
        samples = array.array("h", frame[:count * 2])
        power = sum(s * s for s in samples) / count
        return 10 * math.log10(max(power, 1e-9) / (32768.0 ** 2))

    def feed(self, frame):
        """Add one frame. Returns the finished utterance's PCM when one ends, else None."""
        db = self._db(frame)
        voiced = db > max(self.noise + 12.0, -48.0)
        if not voiced:
            # follow the noise floor down quickly and up slowly
            self.noise = db if db < self.noise else self.noise + 0.02 * (db - self.noise)
        if not self.speaking:
            self.preroll = (self.preroll + [frame])[-15:]
            self.voiced_run = self.voiced_run + 1 if voiced else 0
            if self.voiced_run >= 3:
                self.speaking = True
                self.frames = list(self.preroll)
                self.silent_run = 0
            return None
        self.frames.append(frame)
        self.silent_run = 0 if voiced else self.silent_run + 1
        if self.silent_run >= self.end_frames or len(self.frames) >= self.max_frames:
            pcm = b"".join(self.frames[:len(self.frames) - self.silent_run + 5])
            self.reset()
            return pcm
        return None


class Microphone:
    """Reads 16 kHz mono PCM from the recorder program, 20 ms at a time."""

    rate = 16000

    def __init__(self, command=recorder_command):
        self.command = command
        self.process = None

    async def frames(self):
        cmd = self.command(self.rate)
        if not cmd:
            raise RuntimeError("no recording program (pw-record or arecord) is installed")
        self.process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        size = int(self.rate * FRAME) * 2
        try:
            while True:
                frame = await self.process.stdout.readexactly(size)
                yield frame
        except asyncio.IncompleteReadError:
            return
        finally:
            if self.process and self.process.returncode is None:
                self.process.kill()
