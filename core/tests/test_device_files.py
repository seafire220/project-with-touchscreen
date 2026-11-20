"""The device's own files: the USB connection to a computer, and how updates install system files."""
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion.device import usb_status  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GADGET = os.path.join(REPO, "device", "usb", "companion-usb-gadget")


def run_gadget(folder, mode="ncm", udc="fe980000.usb", serial="10000000abcd1234"):
    """The gadget program against stand-in folders for configfs and the board's USB controller."""
    udcs = os.path.join(folder, "udc")
    os.makedirs(udcs, exist_ok=True)
    if udc:
        open(os.path.join(udcs, udc), "w").close()
    with open(os.path.join(folder, "serial"), "w") as f:
        f.write(serial + "\0")
    env = dict(os.environ, COMPANION_USB=mode, COMPANION_GADGET=os.path.join(folder, "gadget"),
               COMPANION_UDC_DIR=udcs, COMPANION_SERIAL_FILE=os.path.join(folder, "serial"))
    return subprocess.run(["bash", GADGET], env=env, capture_output=True, text=True, timeout=30)


def read(*parts):
    with open(os.path.join(*parts)) as f:
        return f.read().strip()


class UsbGadgetTest(unittest.TestCase):
    def test_the_board_shows_itself_as_a_network_adapter_with_the_same_addresses_each_time(self):
        with tempfile.TemporaryDirectory() as d:
            done = run_gadget(d)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("10.12.194.1", done.stdout)
            g = os.path.join(d, "gadget")
            self.assertEqual(read(g, "UDC"), "fe980000.usb", "switched on, on the board's controller")
            self.assertEqual(read(g, "idVendor"), "0x1d6b")
            self.assertEqual(read(g, "strings", "0x409", "serialnumber"), "10000000abcd1234")
            self.assertTrue(os.path.islink(os.path.join(g, "configs", "c.1", "ncm.usb0")))
            host = read(g, "functions", "ncm.usb0", "host_addr")
            device = read(g, "functions", "ncm.usb0", "dev_addr")
            self.assertRegex(host, r"^02(:[0-9a-f]{2}){5}$")
            self.assertEqual(host[3:], device[3:], "both from the serial number")
            with tempfile.TemporaryDirectory() as d2:
                run_gadget(d2)
                self.assertEqual(read(d2, "gadget", "functions", "ncm.usb0", "host_addr"), host, "the same every time")
            again = run_gadget(d)
            self.assertEqual(again.returncode, 0)
            self.assertIn("already set up", again.stdout)

    def test_off_or_without_a_usb_device_port_it_does_nothing(self):
        for mode, udc, says in (("off", "fe980000.usb", "switched off"), ("ncm", "", "no USB device port"),
                                ("bluetooth", "fe980000.usb", "must be")):
            with tempfile.TemporaryDirectory() as d:
                done = run_gadget(d, mode=mode, udc=udc)
                self.assertEqual(done.returncode, 0, "it never stops the device starting")
                self.assertIn(says, done.stdout + done.stderr)
                self.assertFalse(os.path.exists(os.path.join(d, "gadget", "UDC")))

    def test_other_kinds_for_other_computers(self):
        for mode in ("ecm", "rndis"):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(run_gadget(d, mode=mode).returncode, 0)
                self.assertTrue(os.path.islink(os.path.join(d, "gadget", "configs", "c.1", mode + ".usb0")))

    def test_the_status_says_when_a_computer_is_connected(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(usb_status(os.path.join(d, "usb0")), {"available": False})
            os.makedirs(os.path.join(d, "usb0"))
            self.assertFalse(usb_status(os.path.join(d, "usb0"))["connected"], "a link that is down")
            with open(os.path.join(d, "usb0", "carrier"), "w") as f:
                f.write("1\n")
            self.assertEqual(usb_status(os.path.join(d, "usb0")),
                             {"available": True, "connected": True, "address": "http://10.12.194.1"})


class SystemFilesTest(unittest.TestCase):
    def test_updates_install_the_new_system_files_networkmanagers_readable_by_root_only(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["COMPANION_ETC"] = os.path.join(d, "root")
            os.environ["COMPANION_APP"] = os.path.join(d, "opt")
            try:
                spec = importlib.util.spec_from_file_location(
                    "updater_under_test", os.path.join(REPO, "device", "updater", "companion-update.py"))
                updater = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(updater)
            finally:
                del os.environ["COMPANION_ETC"], os.environ["COMPANION_APP"]
            release = os.path.join(d, "release")
            os.makedirs(os.path.join(release, "system"))
            for name, source in (("companion-usb.nmconnection", "device/config/companion-usb.nmconnection"),
                                 ("companion-usb.service", "device/systemd/companion-usb.service"),
                                 ("99-companion-backlight.rules", "device/config/99-companion-backlight.rules")):
                with open(os.path.join(REPO, source), "rb") as src, open(os.path.join(release, "system", name), "wb") as dst:
                    dst.write(src.read())
            updater.install_system_files(release)
            nm = os.path.join(d, "root", "usr", "lib", "NetworkManager", "system-connections", "companion-usb.nmconnection")
            self.assertEqual(stat.S_IMODE(os.stat(nm).st_mode), 0o600)
            unit = os.path.join(d, "root", "etc", "systemd", "system", "companion-usb.service")
            self.assertEqual(stat.S_IMODE(os.stat(unit).st_mode), 0o644)
            self.assertTrue(os.path.isfile(os.path.join(d, "root", "etc", "udev", "rules.d", "99-companion-backlight.rules")))

    def test_the_release_tool_and_the_updater_agree_on_the_system_files(self):
        spec = importlib.util.spec_from_file_location("release_tool_check", os.path.join(REPO, "device", "release.py"))
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        spec = importlib.util.spec_from_file_location("updater_check", os.path.join(REPO, "device", "updater", "companion-update.py"))
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        self.assertEqual(set(release.SYSTEM_FILES) - {"companion-update.py"}, set(updater.SYSTEM_FILES))
        for source in release.SYSTEM_FILES.values():
            self.assertTrue(os.path.isfile(os.path.join(REPO, source)), source)




class ReadOnlySystemTest(unittest.IsolatedAsyncioTestCase):
    """Power-cut protection (docs/33-finishing.md): the device's side of a read-only system."""

    async def test_the_time_zone_is_kept_on_the_data_partition(self):
        import companion.device as device_module
        from companion.audio import Speaker
        from companion.device import Device
        sys.path.insert(0, os.path.dirname(__file__))
        from fakes import FakeStage
        with tempfile.TemporaryDirectory() as d:
            zoneinfo = os.path.join(d, "zoneinfo")
            for zone in ("Etc/UTC", "Australia/Perth"):
                os.makedirs(os.path.dirname(os.path.join(zoneinfo, zone)), exist_ok=True)
                open(os.path.join(zoneinfo, zone), "w").close()
            time_dir = os.path.join(d, "data", "system", "time")
            os.makedirs(time_dir)
            os.symlink(os.path.join(zoneinfo, "Etc/UTC"), os.path.join(time_dir, "localtime"))
            localtime = os.path.join(d, "etc-localtime")
            os.symlink(os.path.join(time_dir, "localtime"), localtime)
            old = (device_module.TIME_DIR, device_module.LOCALTIME, device_module.ZONEINFO)
            device_module.TIME_DIR, device_module.LOCALTIME, device_module.ZONEINFO = time_dir, localtime, zoneinfo
            ran = []

            async def run(*args, **kwargs):
                ran.append(args)
            try:
                device = Device(os.path.join(d, "dev"), speaker=Speaker(command=None, realtime=False), stage=FakeStage(),
                                run=run)
                self.assertEqual(device.timezone(), "Etc/UTC")
                real_zoneinfo = "/usr/share/zoneinfo/Australia/Perth"
                if os.path.isfile(real_zoneinfo):       # the zone is checked against the real zone files
                    await device.set_timezone("Australia/Perth")
                    self.assertEqual(ran, [], "not through timedatectl, which would write to the read-only system")
                    self.assertEqual(device.timezone(), "Australia/Perth")
                    self.assertEqual(os.readlink(localtime), os.path.join(time_dir, "localtime"), "/etc/localtime is untouched")
            finally:
                device_module.TIME_DIR, device_module.LOCALTIME, device_module.ZONEINFO = old

    def test_models_an_update_brings_are_preferred_to_those_the_device_came_with(self):
        import companion.device as device_module
        from companion.audio import Speaker
        from companion.device import Device
        sys.path.insert(0, os.path.dirname(__file__))
        from fakes import FakeStage
        with tempfile.TemporaryDirectory() as d:
            factory = os.path.join(d, "factory")
            os.makedirs(os.path.join(factory, "stt"))
            old = device_module.FACTORY_MODELS
            device_module.FACTORY_MODELS = factory
            try:
                device = Device(os.path.join(d, "dev"), speaker=Speaker(command=None, realtime=False), stage=FakeStage())
                self.assertEqual(device.model_dir("stt"), os.path.join(factory, "stt"))
                self.assertEqual(device.model_dir("tts"), os.path.join(d, "dev", "models", "tts"), "neither: the data folder")
                os.makedirs(os.path.join(d, "dev", "models", "stt"))
                self.assertEqual(device.model_dir("stt"), os.path.join(d, "dev", "models", "stt"))
            finally:
                device_module.FACTORY_MODELS = old

    def test_an_update_makes_the_system_writable_only_while_it_works(self):
        with tempfile.TemporaryDirectory() as d:
            spec = importlib.util.spec_from_file_location(
                "updater_ro", os.path.join(REPO, "device", "updater", "companion-update.py"))
            updater = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(updater)
            mounts = os.path.join(d, "mounts")
            with open(mounts, "w") as f:
                f.write("/dev/mmcblk0p2 / ext4 ro,noatime 0 0\n/dev/mmcblk0p3 /data ext4 rw,noatime 0 0\n")
            self.assertTrue(updater._read_only("/", mounts))
            self.assertFalse(updater._read_only("/data", mounts))
            calls = os.path.join(d, "calls")
            fake_mount = os.path.join(d, "mount")
            with open(fake_mount, "w") as f:
                f.write("#!/bin/sh\necho \"$*\" >> %s\n" % calls)
            os.chmod(fake_mount, 0o755)
            updater.MOUNT, updater.ETC = fake_mount, "/"
            updater._read_only = lambda path="/", mounts="/proc/mounts": True
            with updater.system_writable():
                with open(calls) as f:
                    self.assertEqual(f.read().split("\n")[0], "-o remount,rw /")
            with open(calls) as f:
                self.assertEqual(f.read().strip().split("\n"), ["-o remount,rw /", "-o remount,ro /"])
            os.remove(calls)
            updater._read_only = lambda path="/", mounts="/proc/mounts": False
            with updater.system_writable():
                pass
            self.assertFalse(os.path.exists(calls), "a writable system is left alone")

    async def test_the_settings_page_says_when_the_storage_had_to_be_made_again(self):
        from aiohttp.test_utils import TestClient, TestServer
        from companion.audio import Speaker
        from companion.device import Device
        from companion.web import make_app
        sys.path.insert(0, os.path.dirname(__file__))
        from fakes import FakeStage
        with tempfile.TemporaryDirectory() as d:
            device = Device(d, speaker=Speaker(command=None, realtime=False), stage=FakeStage())
            self.assertFalse(device.status()["storage_recovered"])
            open(os.path.join(d, "storage-recovered"), "w").close()
            self.assertTrue(device.status()["storage_recovered"])
            client = TestClient(TestServer(make_app(device)))
            await client.start_server()
            try:
                h = {"X-Companion": "1"}
                await client.post("/api/setup", json={"password": "a good password"}, headers=h)
                r = await client.post("/api/storage-recovered/seen", json={}, headers=h)
                self.assertEqual(r.status, 200)
                self.assertFalse(device.status()["storage_recovered"])
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
