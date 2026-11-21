"""Subtle synthesized tactile UI audio cues for the touchscreen edition.

All cues are short (30–170 ms) warm glass/marimba harmonic tones synthesized in pure
Python into cached 16-bit 24 kHz mono PCM (< 80 KB total RAM, zero external sound files).
They respect the speaker's volume and never play over active speech or recording.
"""
import array
import asyncio
import math

RATE = 24000
_CACHE = {}


def _tone(notes, volume=0.22):
    """Synthesize a sequence of (start_s, dur_s, freq_hz, gain) soft harmonic notes to S16LE PCM."""
    end_s = max(start + dur for start, dur, _, _ in notes) + 0.015
    total = int(RATE * end_s)
    buf = [0.0] * total
    for start, dur, freq, gain in notes:
        i0 = int(start * RATE)
        count = max(1, int(dur * RATE))
        attack = max(1, int(min(0.005, dur * 0.15) * RATE))
        for k in range(count):
            idx = i0 + k
            if idx >= total:
                break
            t = k / RATE
            env = (k / attack) if k < attack else math.exp(-5.2 * (k - attack) / max(1, count - attack))
            # Fundamental + gentle 2nd harmonic for a warm glass/marimba timbre.
            sample = math.sin(2.0 * math.pi * freq * t) + 0.22 * math.sin(4.0 * math.pi * freq * t)
            buf[idx] += sample * env * gain * volume
    out = array.array("h", (max(-32767, min(32767, int(v * 32767.0))) for v in buf))
    return out.tobytes()


# Musical, ultra-gentle UI cue definitions (Hz based on soft pentatonic / major intervals).
CUES = {
    "tap": ((0.0, 0.032, 920.0, 0.45),),
    "open": ((0.0, 0.055, 587.3, 0.55), (0.042, 0.085, 880.0, 0.50)),
    "close": ((0.0, 0.050, 740.0, 0.45), (0.036, 0.070, 523.3, 0.40)),
    "listen_start": ((0.0, 0.065, 523.3, 0.58), (0.055, 0.100, 784.0, 0.55)),
    "listen_stop": ((0.0, 0.060, 659.3, 0.48), (0.048, 0.085, 493.9, 0.44)),
    "headpat": ((0.0, 0.070, 659.3, 0.48), (0.045, 0.085, 880.0, 0.45), (0.090, 0.115, 1046.5, 0.40)),
    "poke": ((0.0, 0.045, 784.0, 0.52), (0.032, 0.055, 1174.7, 0.40)),
    "gift": ((0.0, 0.075, 523.3, 0.52), (0.050, 0.090, 659.3, 0.50), (0.100, 0.115, 784.0, 0.48), (0.150, 0.145, 1046.5, 0.44)),
    "timer": ((0.0, 0.060, 880.0, 0.50), (0.055, 0.090, 1174.7, 0.48)),
    "test": ((0.0, 0.090, 523.3, 0.65), (0.090, 0.090, 659.3, 0.65), (0.180, 0.150, 784.0, 0.65)),
}


def pcm_for(name, scale=1.0):
    """Return cached 24 kHz S16LE PCM for `name`, optionally scaled by `scale` (0..1)."""
    if name not in CUES:
        return b""
    base = _CACHE.get(name)
    if base is None:
        base = _tone(CUES[name])
        _CACHE[name] = base
    scale = max(0.0, min(1.0, float(scale)))
    if scale >= 0.99:
        return base
    if scale <= 0.01:
        return b""
    samples = array.array("h")
    samples.frombytes(base)
    scaled = array.array("h", (int(s * scale) for s in samples))
    return scaled.tobytes()


async def play_cue(speaker, name):
    """Play a brief tactile cue asynchronously through `speaker.command`, never blocking or raising."""
    if speaker is None or speaker.command is None or speaker.volume <= 0.01:
        return False
    data = pcm_for(name, scale=speaker.volume)
    if not data:
        return False
    cmd = speaker.command(RATE) if callable(speaker.command) else speaker.command
    if not cmd:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(data), timeout=1.5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        return True
    except OSError:
        return False
