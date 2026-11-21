"""Tests for the touchscreen edition: tactile reactions, frosted-glass dock, character switcher,
timers, moods/QR, on-screen Wi-Fi setup & touch keyboard, and web API (docs/35-touchscreen.md)."""
import asyncio
import io
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from PIL import Image  # noqa: E402

from companion import package  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.network import NetworkError  # noqa: E402
from companion.providers import ProviderError  # noqa: E402
from companion.web import make_app  # noqa: E402
from fakes import FakeLLM, FakeStage, FakeTTS  # noqa: E402
from test_package import good_files, manifest  # noqa: E402


class FakeBacklight:
    available = True

    def __init__(self):
        self.values = []

    def set(self, level):
        self.values.append(round(level, 3))
        return True


class FakeWiFi:
    def __init__(self, networks=None, connected=False, address="192.168.1.42", fail_join=None):
        self._networks = networks if networks is not None else [
            {"ssid": "HomeFiber", "signal": 88, "secure": True},
            {"ssid": "GuestOpen", "signal": 62, "secure": False},
        ]
        self._connected = connected
        self._address = address
        self.fail_join = fail_join
        self.hotspot = False
        self.joined = []

    async def connected(self):
        return self._connected

    async def address(self):
        return self._address if self._connected else ""

    async def networks(self):
        return list(self._networks)

    async def join(self, ssid, password=""):
        if self.fail_join:
            raise NetworkError(self.fail_join)
        self.joined.append((ssid, password))
        self._connected = True
        self._address = "192.168.1.99"

    async def start_hotspot(self, *args):
        self.hotspot = True
        return ("Companion-Test", "test-pass")

    async def stop_hotspot(self):
        self.hotspot = False


def hit_center(ui, action, payload=None):
    """Find the normalized (x, y) center of a registered hitbox in TouchUI."""
    for x0, y0, x1, y1, act, pl in ui.hits:
        if act == action and (payload is None or pl == payload):
            return (x0 + x1) * 0.5, (y0 + y1) * 0.5
    raise AssertionError("hitbox not found: %r (payload=%r) in %r" % (
        action, payload, [(h[4], h[5]) for h in ui.hits]))


def tap_hit(device, action, payload=None):
    x, y = hit_center(device.touch_ui, action, payload)
    device._stage_event({"event": "ui_touch", "phase": "tap", "target": "panel", "x": x, "y": y})


def last_overlay(stage, slot):
    matches = [c["overlay"] for c in stage.commands if isinstance(c, dict) and "overlay" in c
               and c["overlay"]["slot"] == slot]
    return matches[-1] if matches else None


def last_capture(stage):
    matches = [c["touch_capture"] for c in stage.commands if isinstance(c, dict) and "touch_capture" in c]
    return matches[-1] if matches else None


def make_preview_png(color=(120, 140, 220, 255)):
    img = Image.new("RGBA", (180, 180), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class TouchBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.llm = FakeLLM("Hehe, that tickles!")
        self.tts = FakeTTS()
        self.stage = FakeStage()
        self.backlight = FakeBacklight()
        self.wifi = FakeWiFi()
        self.device = Device(
            self.dir.name,
            speaker=Speaker(command=None, realtime=False),
            stage=self.stage,
            wifi=self.wifi,
            provider_factory=lambda which, d: {"llm": self.llm, "tts": self.tts}.get(which),
        )
        self.device.backlight = self.backlight
        self.device.characters.install(package.build(good_files(), manifest()))
        self.device._stage_event({"event": "ready", "width": 720, "height": 1280, "touch": True})

    async def asyncTearDown(self):
        self.device.touch_ui.hide_all()
        self.dir.cleanup()


class TactileReactionTest(TouchBase):
    async def test_stage_ready_activates_touch_and_renders_pill(self):
        self.assertTrue(self.device.touch_ready)
        pill_cmd = last_overlay(self.stage, "touch-pill")
        self.assertIsNotNone(pill_cmd)
        self.assertEqual(pill_cmd["anchor"], "bottom")
        self.assertEqual(pill_cmd["layer"], 10)
        self.assertTrue(os.path.isfile(os.path.join(self.device.overlays.folder, pill_cmd["image"])))
        cap = last_capture(self.stage)
        self.assertFalse(cap["modal"])
        self.assertIsNotNone(cap["pill"])
        self.assertTrue(cap["edge_swipe"])

    async def test_headpat_triggers_spoken_reaction_with_cooldown(self):
        self.device._stage_event({"event": "touch", "kind": "pet", "zone": "head", "x": 0.5, "y": 0.2})
        await asyncio.sleep(0.15)
        self.assertEqual(len(self.llm.calls), 1)
        self.assertIn("patted your head", self.llm.calls[0][1][-1]["content"])

        # Immediate second headpat respects reaction_cooldown (25s default).
        self.device._stage_event({"event": "touch", "kind": "pet", "zone": "head", "x": 0.5, "y": 0.2})
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.llm.calls), 1)

        # After cooldown elapses, a cheek rub triggers again.
        self.device.last_touch_speech = time.time() - 30.0
        self.device.last_talk = time.time() - 10.0
        self.device._stage_event({"event": "touch", "kind": "pet", "zone": "face", "x": 0.5, "y": 0.35})
        await asyncio.sleep(0.15)
        self.assertEqual(len(self.llm.calls), 2)
        self.assertIn("stroked your cheek", self.llm.calls[1][1][-1]["content"])

    async def test_spoken_reactions_respect_settings_and_missing_provider(self):
        # Background tap logs touch but never speaks.
        self.device._stage_event({"event": "touch", "kind": "tap", "zone": "background", "x": 0.1, "y": 0.1})
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.llm.calls), 0)

        # Turning off spoken_reactions suppresses speech.
        self.device.store.update_settings({"touch": {"spoken_reactions": False}})
        self.device._stage_event({"event": "touch", "kind": "poke", "zone": "face", "x": 0.5, "y": 0.35})
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.llm.calls), 0)

        # Missing LLM key fails silently (no error event, no crash).
        self.device.store.update_settings({"touch": {"spoken_reactions": True}})
        self.device.conversation = None
        self.device.provider_factory = lambda which, d: (_ for _ in ()).throw(ProviderError("no key"))
        before_errors = [e for e in self.device.log if e["kind"] == "error"]
        res = await self.device.react_to_touch("poke", "face")
        self.assertIsNone(res)
        after_errors = [e for e in self.device.log if e["kind"] == "error"]
        self.assertEqual(len(before_errors), len(after_errors))

    async def test_wake_on_touch_lights_sleeping_screen(self):
        self.device.set_screen("off")
        self.assertEqual(self.device.screen_mode, "off")
        self.device._stage_event({"event": "touch_wake"})
        self.assertEqual(self.device.screen_mode, "on")
        self.assertTrue(any(e["kind"] == "touch" and e.get("action") == "wake" for e in self.device.log))


class PillAndDockTest(TouchBase):
    async def test_pill_yields_to_captions_and_returns(self):
        self.device.overlays.caption("Hello there!")
        self.assertIsNone(last_overlay(self.stage, "touch-pill")["image"])
        self.assertIsNone(last_capture(self.stage)["pill"])

        self.device.overlays.hide("caption")
        self.assertIsNotNone(last_overlay(self.stage, "touch-pill")["image"])
        self.assertIsNotNone(last_capture(self.stage)["pill"])

    async def test_edge_swipe_opens_dock_and_backdrop_dismisses(self):
        self.device._stage_event({"event": "ui_touch", "phase": "swipe", "target": "edge", "dir": "up", "x": 0.5, "y": 0.98})
        self.assertEqual(self.device.touch_ui.view, "dock")
        dock_cmd = last_overlay(self.stage, "touch-dock")
        self.assertIsNotNone(dock_cmd["image"])
        self.assertEqual(dock_cmd["slide"], "up")
        self.assertGreater(dock_cmd["scrim"], 0.0)
        cap = last_capture(self.stage)
        self.assertTrue(cap["modal"])
        self.assertIsNotNone(cap["panel"])

        # Backdrop tap dismisses back to pill.
        self.device._stage_event({"event": "ui_touch", "phase": "tap", "target": "backdrop", "x": 0.5, "y": 0.1})
        self.assertEqual(self.device.touch_ui.view, "pill")
        self.assertIsNone(last_overlay(self.stage, "touch-dock")["image"])

    async def test_dock_sliders_mute_captions_and_sleep(self):
        self.device.touch_ui.open_view("dock")

        # Drag volume slider to ~50%.
        vol_hit = self.device.touch_ui._find_action("slider_volume")
        vx = vol_hit[0] + (vol_hit[2] - vol_hit[0]) * 0.25
        vy = (vol_hit[1] + vol_hit[3]) * 0.5
        self.device._stage_event({"event": "ui_touch", "phase": "down", "target": "panel", "x": vx, "y": vy})
        self.device._stage_event({"event": "ui_touch", "phase": "move", "target": "panel",
                                  "x": vol_hit[0] + (vol_hit[2] - vol_hit[0]) * 0.50, "y": vy})
        self.device._stage_event({"event": "ui_touch", "phase": "up", "target": "panel",
                                  "x": vol_hit[0] + (vol_hit[2] - vol_hit[0]) * 0.50, "y": vy})
        self.assertAlmostEqual(self.device.store.settings()["volume"], 0.5, places=2)
        self.assertAlmostEqual(self.device.speaker.volume, 0.5, places=2)

        # Tap brightness slider to ~50% (between 10 and 100 -> 55).
        br_hit = self.device.touch_ui._find_action("slider_brightness")
        bx = br_hit[0] + (br_hit[2] - br_hit[0]) * 0.5
        by = (br_hit[1] + br_hit[3]) * 0.5
        self.device._stage_event({"event": "ui_touch", "phase": "tap", "target": "panel", "x": bx, "y": by})
        self.assertEqual(self.device.store.settings()["screen"]["brightness"], 55)
        self.assertIn(0.55, self.backlight.values)

        # Toggle captions.
        self.assertFalse(self.device.store.settings()["captions"]["on"])
        tap_hit(self.device, "captions")
        self.assertTrue(self.device.store.settings()["captions"]["on"])

        # Toggle mute, and confirm hardware switch blocks unmute.
        tap_hit(self.device, "mute")
        self.assertTrue(self.device.muted)
        self.device.set_switch(True)
        tap_hit(self.device, "mute")
        self.assertTrue(self.device.muted, "hardware mute switch stays in control")
        self.device.set_switch(False)
        tap_hit(self.device, "mute")
        self.assertFalse(self.device.muted)

        # Sleep button dismisses dock and puts screen to sleep.
        tap_hit(self.device, "sleep")
        self.assertEqual(self.device.touch_ui.view, "pill")
        self.assertEqual(self.device.screen_mode, "off")

    async def test_setup_mode_pill_opens_wifi_directly(self):
        self.device.characters.delete("aria")
        self.device.touch_ui.set_setup_mode(True)
        self.device._stage_event({"event": "ui_touch", "phase": "tap", "target": "pill", "x": 0.5, "y": 0.95})
        self.assertEqual(self.device.touch_ui.view, "wifi")

    async def test_active_pill_interrupts_speaking(self):
        self.device.set_state("listening")
        self.device.listening = True
        self.device._stage_event({"event": "ui_touch", "phase": "tap", "target": "pill", "x": 0.5, "y": 0.95})
        self.assertFalse(self.device.listening)


class SheetsTest(TouchBase):
    async def test_character_switcher_pagination_and_activation(self):
        # Install 5 more characters (total 6 -> 2 pages of 4), some with preview thumbnails.
        for idx, cid in enumerate(("mika", "kai", "ren", "sora", "luna")):
            files = dict(good_files())
            if idx % 2 == 0:
                files["preview.png"] = make_preview_png()
            m = manifest()
            m["id"] = cid
            m["name"] = cid.title()
            self.device.characters.install(package.build(files, m))

        self.device.touch_ui.open_view("characters")
        self.assertEqual(self.device.touch_ui.char_page, 0)
        # Swipe left advances to page 1.
        self.device._stage_event({"event": "ui_touch", "phase": "swipe", "target": "panel", "dir": "left", "x": 0.5, "y": 0.7})
        self.assertEqual(self.device.touch_ui.char_page, 1)
        # Tap Prev returns to page 0.
        tap_hit(self.device, "char_prev")
        self.assertEqual(self.device.touch_ui.char_page, 0)

        # Select one of the non-active characters on page 0.
        shown_ids = [h[5] for h in self.device.touch_ui.hits if h[4] == "select_character"]
        other = next(cid for cid in shown_ids if cid != self.device.active_id())
        tap_hit(self.device, "select_character", other)
        self.assertEqual(self.device.active_id(), other)
        self.assertEqual(self.device.touch_ui.view, "pill")

    async def test_timers_sheet_quick_set_and_cancel(self):
        # Top-edge swipe down opens timers directly.
        self.device._stage_event({"event": "ui_touch", "phase": "swipe", "target": "edge", "dir": "down", "x": 0.5, "y": 0.02})
        self.assertEqual(self.device.touch_ui.view, "timers")
        tap_hit(self.device, "quick_timer", (300, "5m"))
        self.assertIn("5m timer", self.device.timers)

        tap_hit(self.device, "cancel_timer", "5m timer")
        self.assertNotIn("5m timer", self.device.timers)

    async def test_status_sheet_moods_toggles_and_qr(self):
        self.device.touch_ui.open_view("status")
        await asyncio.sleep(0.02)
        tap_hit(self.device, "mood", "happy")
        self.assertIn({"express": "happy"}, self.stage.commands)
        tap_hit(self.device, "mood", "wave")
        self.assertIn({"gesture": "wave"}, self.stage.commands)

        tap_hit(self.device, "toggle_spoken_touch")
        self.assertFalse(self.device.store.settings()["touch"]["spoken_reactions"])
        tap_hit(self.device, "toggle_heard_captions")
        self.assertTrue(self.device.store.settings()["captions"]["heard"])
        self.assertTrue(self.device.store.settings()["captions"]["on"])


class WifiAndKeyboardTest(TouchBase):
    async def test_wifi_scan_open_join_and_secured_keyboard_flow(self):
        self.device.touch_ui.open_view("wifi")
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.device.touch_ui.wifi_networks), 2)

        # Pick secured network -> opens touch keyboard.
        tap_hit(self.device, "wifi_pick", self.device.touch_ui.wifi_networks[0])
        self.assertEqual(self.device.touch_ui.view, "keyboard")
        self.assertEqual(self.device.touch_ui.kb_ssid, "HomeFiber")

        # Type "Abc12!@" using shift, lowercase, num, sym, backspace, and validation.
        tap_hit(self.device, "kb_key", "shift")
        tap_hit(self.device, "kb_key", "a")   # -> "A", shift auto-releases
        tap_hit(self.device, "kb_key", "b")   # -> "Ab"
        tap_hit(self.device, "kb_key", "c")   # -> "Abc"
        self.assertEqual(self.device.touch_ui.kb_text, "Abc")

        # Submitting <8 chars shows inline validation error without calling wifi.join.
        tap_hit(self.device, "kb_key", "submit")
        self.assertIn("8 characters", self.device.touch_ui.kb_error)
        self.assertEqual(self.wifi.joined, [])

        # Toggle password visibility, switch to 123 and #+= layouts, type remaining chars.
        tap_hit(self.device, "kb_toggle_show")
        self.assertTrue(self.device.touch_ui.kb_show_text)
        tap_hit(self.device, "kb_key", "mode_num")
        for ch in "12345":
            tap_hit(self.device, "kb_key", ch)
        tap_hit(self.device, "kb_key", "mode_sym")
        tap_hit(self.device, "kb_key", "!")
        tap_hit(self.device, "kb_key", "back")  # remove "!"
        tap_hit(self.device, "kb_key", "@")
        self.assertEqual(self.device.touch_ui.kb_text, "Abc12345@")

        # Submit valid password -> joins Wi-Fi and dismisses cleanly.
        tap_hit(self.device, "kb_key", "submit")
        await asyncio.sleep(0.05)
        self.assertEqual(self.wifi.joined, [("HomeFiber", "Abc12345@")])
        self.assertEqual(self.device.touch_ui.view, "pill")

    async def test_hidden_ssid_and_caps_lock_and_join_failure(self):
        self.wifi.fail_join = "wrong password"
        self.device.touch_ui.open_view("wifi")
        await asyncio.sleep(0.05)

        tap_hit(self.device, "wifi_hidden")
        self.assertEqual(self.device.touch_ui.kb_target, "wifi_ssid")

        # Empty SSID is rejected cleanly.
        tap_hit(self.device, "kb_key", "submit")
        self.assertIn("network name", self.device.touch_ui.kb_error)

        # Double-tap Shift enables Caps Lock.
        tap_hit(self.device, "kb_key", "shift")
        tap_hit(self.device, "kb_key", "shift")
        self.assertTrue(self.device.touch_ui.kb_caps)
        tap_hit(self.device, "kb_key", "l")
        tap_hit(self.device, "kb_key", "a")
        tap_hit(self.device, "kb_key", "b")
        self.assertEqual(self.device.touch_ui.kb_text, "LAB")
        tap_hit(self.device, "kb_key", "submit")

        # Advances to password entry for "LAB".
        self.assertEqual(self.device.touch_ui.kb_target, "wifi_password")
        self.assertEqual(self.device.touch_ui.kb_ssid, "LAB")
        for ch in "secretpass":
            tap_hit(self.device, "kb_key", ch)
        tap_hit(self.device, "kb_key", "submit")
        await asyncio.sleep(0.05)
        self.assertEqual(self.device.touch_ui.view, "keyboard")
        self.assertIn("wrong password", self.device.touch_ui.kb_error)

        # Clear button resets field for retry.
        tap_hit(self.device, "kb_key", "clear")
        self.assertEqual(self.device.touch_ui.kb_text, "")


class TouchWebApiTest(TouchBase):
    async def test_settings_validation_status_and_touch_endpoint(self):
        client = TestClient(TestServer(make_app(self.device)))
        await client.start_server()
        try:
            h = {"X-Companion": "1"}
            await client.post("/api/setup", json={"password": "a good password"}, headers=h)

            st = await (await client.get("/api/status")).json()
            self.assertEqual(st["touch"], {"ready": True, "enabled": True, "view": "pill"})

            # Validation rejects out-of-range cooldown/auto_hide.
            bad = await client.put("/api/settings", json={"touch": {"reaction_cooldown": 1}}, headers=h)
            self.assertEqual(bad.status, 400)
            bad2 = await client.put("/api/settings", json={"touch": {"auto_hide": 1}}, headers=h)
            self.assertEqual(bad2.status, 400)

            # Valid update persists and pushes touch_config to stage.
            ok = await client.put("/api/settings", json={"touch": {"reaction_cooldown": 45, "effects": False}}, headers=h)
            self.assertEqual(ok.status, 200)
            body = await ok.json()
            self.assertEqual(body["touch"]["reaction_cooldown"], 45.0)
            self.assertFalse(body["touch"]["effects"])
            self.assertIn({"touch_config": {"enabled": True, "character_touch": True, "effects": False}}, self.stage.commands)

            # POST /api/touch opens views, simulates touches, and rejects invalid payloads.
            r = await client.post("/api/touch", json={"view": "dock"}, headers=h)
            self.assertEqual(r.status, 200)
            self.assertEqual(self.device.touch_ui.view, "dock")

            r2 = await client.post("/api/touch", json={"sim": {"phase": "start", "x": 0.5, "y": 0.25}}, headers=h)
            self.assertEqual(r2.status, 200)
            self.assertIn({"touch_sim": {"phase": "start", "x": 0.5, "y": 0.25}}, self.stage.commands)

            r3 = await client.post("/api/touch", json={"kind": "pet", "zone": "head"}, headers=h)
            self.assertEqual(r3.status, 200)
            self.assertIn({"gesture": "headpat"}, self.stage.commands)

            r4 = await client.post("/api/touch", json={"view": "bogus"}, headers=h)
            self.assertEqual(r4.status, 400)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
