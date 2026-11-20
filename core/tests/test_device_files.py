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


if __name__ == "__main__":
    unittest.main()
