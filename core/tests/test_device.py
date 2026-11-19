"""Tests for screen cards and Wi-Fi setup, with a stand-in for nmcli."""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import screen  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.network import NetworkError, WiFi, split_terse  # noqa: E402
from fakes import FakeStage  # noqa: E402

STAGE = os.path.join(os.path.dirname(__file__), "..", "..", "stage", "target", "release", "stage")


class FakeNmcli:
    def __init__(self, connected=False, fail_join=False, saved=(), comes_back_after=None):
        self.connected = connected
        self.fail_join = fail_join
        self.saved = list(saved)
        self.comes_back_after = comes_back_after      # hotspot closings before the home network returns
        self.closings = 0
        self.calls = []

    async def __call__(self, *args, timeout=40):
        self.calls.append(args)
        if args[1:4] == ("-t", "-f", "STATE"):
            return "connected\n" if self.connected else "disconnected\n"
        if args[1:4] == ("-t", "-f", "NAME,TYPE"):
            return "".join("%s:802-11-wireless\n" % n for n in self.saved) + "companion-setup:802-11-wireless\n"
        if args[1:3] == ("connection", "down"):
            self.closings += 1
            if self.comes_back_after is not None and self.closings >= self.comes_back_after:
                self.connected = True
        if "IP4.ADDRESS" in args:
            return "IP4.ADDRESS[1]:192.168.1.50/24\n" if self.connected else ""
        if "list" in args:
            return "Home\\:Net:80:WPA2\nCafe:40:\nHome\\:Net:60:WPA2\n:30:WPA2\n"
        if "connect" in args:
            if self.fail_join:
                raise NetworkError("Secrets were required, but not provided")
            self.connected = True
        return ""


class WiFiTest(unittest.IsolatedAsyncioTestCase):
    def test_terse_fields_with_escaped_colons(self):
        self.assertEqual(split_terse("Home\\:Net:80:WPA2"), ["Home:Net", "80", "WPA2"])

    async def test_networks_are_merged_sorted_and_hidden_ones_dropped(self):
        nets = await WiFi(run=FakeNmcli()).networks()
        self.assertEqual([n["ssid"] for n in nets], ["Home:Net", "Cafe"])
        self.assertEqual(nets[0]["signal"], 80)
        self.assertFalse(nets[1]["secure"])

    async def test_bad_credentials_are_refused_before_nmcli(self):
        wifi = WiFi(run=FakeNmcli())
        with self.assertRaises(NetworkError):
            await wifi.join("Home", "short")
        with self.assertRaises(NetworkError):
            await wifi.join("", "longenough")

    async def test_a_device_without_network_opens_a_hotspot_and_shows_how_to_join(self):
        with tempfile.TemporaryDirectory() as d:
            nm = FakeNmcli(connected=False)
            device = Device(d, speaker=Speaker(command=None), stage=FakeStage(), wifi=WiFi(run=nm))
            await device.network_watch(wait=0.1)
            ssid, password = device.wifi.hotspot
            self.assertTrue(ssid.startswith("Companion-"))
            self.assertEqual(len(password), 8)
            self.assertEqual(os.path.realpath(device.current_puppet), os.path.realpath(device.card))
            self.assertIn({"quit": True}, device.stage.commands, "the stage is restarted to show the card")
            await device.join_wifi("Home", "a good password")
            self.assertTrue(nm.connected)
            self.assertIsNone(device.wifi.hotspot, "the hotspot closes once joined")
            self.assertTrue(any(e["kind"] == "network" and e.get("address") == "192.168.1.50" for e in device.log))

    async def test_after_a_power_cut_the_device_goes_back_to_the_home_network(self):
        with tempfile.TemporaryDirectory() as d:
            nm = FakeNmcli(connected=False, saved=["Home"], comes_back_after=2)
            device = Device(d, speaker=Speaker(command=None), stage=FakeStage(), wifi=WiFi(run=nm))
            await asyncio.wait_for(device.network_watch(wait=0.05, retry=0.05, busy=0.0), 10)
            self.assertTrue(nm.connected)
            self.assertEqual(nm.closings, 2, "the hotspot was closed to retry the home network until it came back")
            self.assertTrue(any(e["kind"] == "network" and e.get("connected") for e in device.log))

    async def test_a_new_device_waits_in_its_hotspot(self):
        with tempfile.TemporaryDirectory() as d:
            nm = FakeNmcli(connected=False, saved=[])
            device = Device(d, speaker=Speaker(command=None), stage=FakeStage(), wifi=WiFi(run=nm))
            await asyncio.wait_for(device.network_watch(wait=0.05, retry=0.05), 5)
            self.assertIsNotNone(device.wifi.hotspot)
            self.assertEqual(nm.closings, 0)

    async def test_the_hotspot_stays_open_while_someone_uses_the_settings_page(self):
        with tempfile.TemporaryDirectory() as d:
            nm = FakeNmcli(connected=False, saved=["Home"], comes_back_after=1)
            device = Device(d, speaker=Speaker(command=None), stage=FakeStage(), wifi=WiFi(run=nm))
            device.last_use = 10 ** 12            # in use "now" for the length of the test
            task = asyncio.ensure_future(device.network_watch(wait=0.05, retry=0.05, busy=60.0))
            await asyncio.sleep(0.5)
            self.assertEqual(nm.closings, 0)
            task.cancel()

    async def test_a_failed_join_reopens_the_hotspot(self):
        with tempfile.TemporaryDirectory() as d:
            device = Device(d, speaker=Speaker(command=None), stage=FakeStage(), wifi=WiFi(run=FakeNmcli(fail_join=True)))
            await device.network_watch(wait=0.1)
            with self.assertRaises(NetworkError):
                await device.join_wifi("Home", "wrong password")
            self.assertIsNotNone(device.wifi.hotspot)


class CardTest(unittest.TestCase):
    def test_a_card_puppet_is_a_valid_puppet(self):
        data = screen.card_puppet(screen.setup_card("192.168.1.50"))
        self.assertTrue(data.startswith(b"TRNSRTS\0"))
        self.assertIn(b"TEX_SECT", data)

    @unittest.skipUnless(os.path.exists(STAGE) and shutil.which("Xvfb"), "needs the built stage and Xvfb")
    def test_the_stage_draws_a_card(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "card.inp")
            with open(path, "wb") as f:
                f.write(screen.card_puppet(screen.hotspot_card("Companion-1A2B", "23456789")))
            xvfb = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "800x1400x24"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            env = dict(os.environ, DISPLAY=":" + xvfb.stdout.readline().strip(), LIBGL_ALWAYS_SOFTWARE="1")
            try:
                run = subprocess.run([STAGE, path, "--size", "360x640", "--gl", "es", "--no-stdin", "--still",
                                      "--fixed-dt", "0.02", "--capture-dir", d, "--capture-at", "0.5",
                                      "--exit-after", "0.6"], env=env, capture_output=True, text=True, timeout=60)
            finally:
                xvfb.terminate()
                xvfb.wait(timeout=10)
                xvfb.stdout.close()
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            frame = Image.open(os.path.join(d, "frame_000.png")).convert("RGB")
            colours = frame.getcolors(1 << 20)
            bright = sum(n for n, c in colours if min(c) > 200)
            self.assertGreater(bright, 500, "the text is drawn")


if __name__ == "__main__":
    unittest.main()
