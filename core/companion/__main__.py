"""Run the device's core service.

    python -m companion --data /var/lib/companion --port 80

The button is read from a Linux input device: the Pi's `gpio-key` overlay
turns a GPIO press into a key press (see docs/13-build-and-install.md). On a desktop,
any keyboard device and key code can be used instead, and the console's
"button" does the same job.
"""
import argparse
import asyncio
import glob
import logging
import os
import struct

from aiohttp import web

from .audio import Microphone, Speaker, player_command
from .device import Device
from .web import make_app

EVENT = struct.Struct("llHHi")   # struct input_event on 64-bit Linux
EV_KEY = 1


LONG_PRESS = 12.0       # seconds held to reset setup (forgotten password or Wi-Fi)
SHORT_PRESS = 2.5       # a press longer than this and shorter than LONG_PRESS does nothing


async def read_button(path, code, press, long_press=None):
    """Call `press` for each short press of `code` on an input device, and `long_press` after a
    hold of LONG_PRESS seconds; reopen the device if it goes away."""
    log = logging.getLogger("companion.button")
    while True:
        try:
            with open(path, "rb", buffering=0) as f:
                log.info("reading the button from %s (key %d)", path, code)
                loop = asyncio.get_running_loop()
                down = None
                while True:
                    data = await loop.run_in_executor(None, f.read, EVENT.size)
                    if len(data) < EVENT.size:
                        break
                    sec, usec, kind, key, value = EVENT.unpack(data)
                    if kind != EV_KEY or key != code:
                        continue
                    when = sec + usec / 1e6          # the kernel's own time stamp of the press
                    if value == 1:
                        down = when
                    elif value == 0 and down is not None:
                        held, down = when - down, None
                        if held >= LONG_PRESS and long_press is not None:
                            asyncio.ensure_future(long_press())
                        elif held < SHORT_PRESS:
                            press()
        except OSError as error:
            log.warning("button device unavailable (%s); retrying", error)
        await asyncio.sleep(2.0)


def find_button():
    """The input device the gpio-key overlay creates, if there is one."""
    for path in sorted(glob.glob("/dev/input/by-path/*button*-event")) + sorted(glob.glob("/dev/input/by-path/*gpio*-event")):
        return path
    return ""


def main():
    parser = argparse.ArgumentParser(description="The character device's core service.")
    parser.add_argument("--data", default="/var/lib/companion")
    parser.add_argument("--stage-socket", default="/run/companion/stage.sock")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--no-audio", action="store_true", help="no microphone or speaker (testing)")
    parser.add_argument("--button", default="auto", help="input device for the button, 'auto' or 'none'")
    parser.add_argument("--button-key", type=int, default=148, help="key code the button sends (148 = KEY_PROG1)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    async def run():
        os.makedirs(args.data, exist_ok=True)
        speaker = Speaker(command=None) if args.no_audio else Speaker(command=player_command)
        microphone = None if args.no_audio else Microphone()
        from .network import WiFi
        import shutil
        wifi = WiFi() if shutil.which("nmcli") else None
        device = Device(args.data, stage_socket=args.stage_socket, speaker=speaker, microphone=microphone, wifi=wifi)
        device.start()
        button = find_button() if args.button == "auto" else ("" if args.button == "none" else args.button)
        if button:
            asyncio.ensure_future(read_button(button, args.button_key, device.button, device.setup_reset))
        runner = web.AppRunner(make_app(device), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, args.host, args.port).start()
        logging.getLogger("companion").info("console on port %d", args.port)
        await asyncio.Event().wait()

    asyncio.run(run())


if __name__ == "__main__":
    main()
