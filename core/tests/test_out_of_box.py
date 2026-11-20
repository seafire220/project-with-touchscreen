"""Tests for out-of-the-box behaviour: sound card detection, time zone, resets, the long press, QR codes."""
import asyncio
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import package, screen  # noqa: E402
from companion.__main__ import EVENT, read_inputs  # noqa: E402
from companion.audio import Speaker, detect_card  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.network import WiFi  # noqa: E402
from companion.web import make_app  # noqa: E402
from fakes import FakeStage  # noqa: E402
from test_package import good_files, manifest  # noqa: E402

CARDS = """ 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0
                      vc4-hdmi-0
 2 [Lite           ]: USB-Audio - ReSpeaker Lite
                      Seeed Studio ReSpeaker Lite at usb-xhci-hcd.0-1, high speed
"""


class Commands:
    """Stand-in for system commands (timedatectl, nmcli)."""

    def __init__(self):
        self.calls = []

    async def __call__(self, *args, timeout=30):
        self.calls.append(args)
        if args[:2] == ("nmcli", "-t") and "connection" in args:
            return "Home Wi-Fi:802-11-wireless\ncompanion-setup:802-11-wireless\nWired connection 1:802-3-ethernet\n"
        return ""


def device_in(folder, commands, restarted):
    return Device(folder, speaker=Speaker(command=None, realtime=False), stage=FakeStage(),
                  wifi=WiFi(run=commands), run=commands, restart=lambda: restarted.append(1))


class OutOfBoxTest(unittest.IsolatedAsyncioTestCase):
    def test_the_respeaker_is_found_without_configuration(self):
        self.assertEqual(detect_card(CARDS), "plughw:CARD=Lite")
        self.assertEqual(detect_card(" 1 [Device         ]: USB-Audio - USB Audio Device\n"), "plughw:CARD=Device")
        self.assertEqual(detect_card(" 0 [vc4hdmi0       ]: vc4-hdmi - vc4-hdmi-0\n"), "")

    async def test_the_time_zone_is_checked_then_set(self):
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            for bad in ("../../etc/passwd", "Not/A_Zone", "", "Europe/London; rm -rf /"):
                with self.assertRaises(ValueError):
                    await device.set_timezone(bad)
            if os.path.isfile("/usr/share/zoneinfo/Australia/Brisbane"):
                await device.set_timezone("Australia/Brisbane")
                self.assertIn(("timedatectl", "set-timezone", "Australia/Brisbane"), cmds.calls)

    async def test_a_factory_reset_removes_everything_but_the_speech_model(self):
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            device.store.set_password("a good password")
            device.store.set_secret("openai", "sk-test-1234567890")
            device.characters.install(package.build(good_files(), manifest()))
            device.memory("aria").set_notes("- likes tea\n")
            os.makedirs(os.path.join(d, "models", "stt"))
            await device.factory_reset()
            self.assertEqual(sorted(os.listdir(d)), ["card.inp", "current-map.json", "current-stage.json", "current.inp", "models",
                                                     "updates"], "the software's update state is kept, like the speech model")
            with open(os.path.join(d, "current-map.json")) as f:
                self.assertEqual(f.read().strip(), "{}", "no movement settings are kept")
            self.assertEqual(restarted, [1])
            self.assertIn(("nmcli", "connection", "delete", "Home Wi-Fi"), cmds.calls)
            self.assertNotIn(("nmcli", "connection", "delete", "companion-setup"), cmds.calls)
            self.assertNotIn(("nmcli", "connection", "delete", "Wired connection 1"), cmds.calls)

    async def test_a_live2d_only_character_is_shown_with_its_live2d_model(self):
        from test_package import live2d_files
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            files = {"persona.md": "You are Aria.", "voice.json": "{}"}
            files.update(live2d_files())
            device.characters.install(package.build(files, manifest()))
            device.activate("aria")
            linked = os.path.realpath(device.current_puppet)
            self.assertEqual(linked, os.path.realpath(device.characters.file("aria", package.LIVE2D_MODEL)))

    async def test_a_vrm_avatar_is_shown_with_its_vrm_drawing(self):
        from vrm_sample import sample_vrm
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            device.characters.install(package.from_vrm(sample_vrm(1)))
            device.activate("sample")
            linked = os.path.realpath(device.current_puppet)
            self.assertEqual(linked, os.path.realpath(device.characters.file("sample", package.VRM_MODEL)))

    async def test_a_character_with_both_formats_shows_the_chosen_one(self):
        from test_package import live2d_files
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            files = good_files()
            files.update(live2d_files())
            device.characters.install(package.build(files, manifest()))
            device.activate("aria")
            self.assertTrue(os.path.realpath(device.current_puppet).endswith("model.model3.json"),
                            "the Live2D-format copy is shown by default")
            device.store.update_settings({"character_format": "inochi2d"})
            device.activate("aria")
            self.assertTrue(os.path.realpath(device.current_puppet).endswith("puppet.inp"))

    async def test_a_setup_reset_forgets_the_password_and_wifi_but_keeps_characters(self):
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            device.store.set_password("a good password")
            device.characters.install(package.build(good_files(), manifest()))
            await device.setup_reset()
            self.assertFalse(device.store.has_password())
            self.assertEqual(device.characters.ids(), ["aria"])
            self.assertIn(("nmcli", "connection", "delete", "Home Wi-Fi"), cmds.calls)
            self.assertEqual(restarted, [1])

    async def test_the_reset_page_needs_the_password_and_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            cmds, restarted = Commands(), []
            device = device_in(d, cmds, restarted)
            client = TestClient(TestServer(make_app(device)))
            await client.start_server()
            try:
                h = {"X-Companion": "1"}
                await client.post("/api/setup", json={"password": "a good password"}, headers=h)
                r = await client.post("/api/reset", json={"password": "wrong password", "confirm": "RESET"}, headers=h)
                self.assertEqual(r.status, 401)
                r = await client.post("/api/reset", json={"password": "a good password", "confirm": "yes"}, headers=h)
                self.assertEqual(r.status, 400)
                r = await client.post("/api/reset", json={"password": "a good password", "confirm": "RESET"}, headers=h)
                self.assertEqual(r.status, 200)
                await asyncio.sleep(2.5)
                self.assertEqual(restarted, [1])
            finally:
                await client.close()

    async def test_the_button_going_down_and_up_and_the_mute_switch_are_read(self):
        class Device:
            def __init__(self):
                self.calls = []

            def button_down(self):
                self.calls.append("down")

            def button_up(self, held):
                self.calls.append(("up", round(held, 1)))

            def set_switch(self, on):
                self.calls.append(("switch", on))

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "event")
            events = []
            for t, key, value in ((100.0, 148, 1), (100.3, 148, 0), (200.0, 148, 1), (200.5, 148, 2), (205.0, 148, 0),
                                  (250.0, 248, 1), (260.0, 248, 0), (300.0, 30, 1)):
                events.append(EVENT.pack(int(t), int(round((t % 1) * 1e6)), 1, key, value))
                events.append(EVENT.pack(int(t), 0, 0, 0, 0))            # a sync event, ignored
            with open(path, "wb") as f:
                f.write(b"".join(events))
            device = Device()
            task = asyncio.ensure_future(read_inputs(path, device))
            await asyncio.sleep(0.5)
            task.cancel()
            self.assertEqual(device.calls, ["down", ("up", 0.3), "down", ("up", 5.0), ("switch", True), ("switch", False)],
                             "the hold's length goes to the device, repeats and other keys are ignored")

    def test_setup_cards_carry_qr_codes(self):
        self.assertEqual(screen.wifi_qr("My;Net", "pa:ss"), r"WIFI:T:WPA;S:My\;Net;P:pa\:ss;;")
        if screen.qr_code("http://192.168.1.50") is not None:
            plain = screen.card_png("x", ["y"])
            with_code = screen.card_png("x", ["y"], qr="http://192.168.1.50")
            self.assertNotEqual(plain, with_code)


if __name__ == "__main__":
    unittest.main()
