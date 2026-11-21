"""Tests for the licences and notices: what the device is made of, and the terms each part comes with."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from companion import notices  # noqa: E402
from companion.audio import Speaker  # noqa: E402
from companion.device import Device  # noqa: E402
from companion.web import make_app  # noqa: E402
from fakes import FakeStage  # noqa: E402

STATUS = """Package: libc6
Status: install ok installed
Version: 2.41-12
Source: glibc

Package: espeak-ng
Status: install ok installed
Version: 1.52.0+dfsg-5

Package: removed-thing
Status: deinstall ok config-files
Version: 1.0
"""


class NoticesTest(unittest.TestCase):
    def test_python_packages_come_with_their_licence_files(self):
        packages = {p["name"].lower(): p for p in notices.python_packages()}
        self.assertIn("aiohttp", packages)
        self.assertTrue(packages["aiohttp"]["texts"], "aiohttp carries its licence file")
        text = notices.python_licences()
        self.assertIn("aiohttp", text)
        self.assertIn("[1]", text)

    def test_operating_system_packages_with_their_copyright_files_each_once(self):
        with tempfile.TemporaryDirectory() as d:
            status = os.path.join(d, "status")
            with open(status, "w") as f:
                f.write(STATUS)
            for name in ("libc6", "espeak-ng"):
                os.makedirs(os.path.join(d, "doc", name))
                with open(os.path.join(d, "doc", name, "copyright"), "w") as f:
                    f.write("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nLicense: GPL-3+\n")
            self.assertEqual(notices.os_packages(status), [("espeak-ng", "1.52.0+dfsg-5", "espeak-ng"),
                                                           ("libc6", "2.41-12", "glibc")])
            text = notices.os_licences(status, os.path.join(d, "doc"))
            self.assertIn("source package: glibc", text)
            self.assertEqual(text.count("License: GPL-3+"), 1, "the same copyright text is given once")
            self.assertNotIn("removed-thing", text)

    def test_the_device_notice_names_the_image_and_where_its_source_code_is(self):
        with tempfile.TemporaryDirectory() as d:
            image = os.path.join(d, "image")
            with open(image, "w") as f:
                f.write("2026.11.21\n")
            with mock.patch.object(notices, "IMAGE_FILE", image):
                text = notices.device_notice()
        self.assertIn("device-image-2026.11.21", text)
        self.assertIn("WITHOUT ANY WARRANTY", text)
        self.assertIn("Live2D is a registered trademark of Live2D Inc.", text)
        self.assertNotIn("{", text, "every blank is filled")

    def test_the_models_are_credited(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "stt"))
            with open(os.path.join(d, "stt", "LICENSE"), "w") as f:
                f.write("MIT License\nCopyright (c) Useful Sensors\n")
            text = notices.model_licences([("stt", os.path.join(d, "stt")), ("tts", os.path.join(d, "none"))])
        self.assertIn("CSTR VCTK Corpus", text)
        self.assertIn("CC BY 4.0", text)
        self.assertIn("Useful Sensors", text)


class PagesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.device = Device(self.dir.name, speaker=Speaker(command=None, realtime=False), stage=FakeStage())
        self.client = TestClient(TestServer(make_app(self.device)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.dir.cleanup()

    async def test_anyone_at_home_can_read_them_without_logging_in(self):
        r = await self.client.get("/licences")
        self.assertEqual(r.status, 200)
        page = await r.text()
        for key in notices.DOCUMENTS:
            self.assertIn("/licences/%s.txt" % key, page)
            r = await self.client.get("/licences/%s.txt" % key)
            self.assertEqual(r.status, 200, key)
            self.assertTrue((await r.text()).strip(), key)
        r = await self.client.get("/licences/stage.txt")
        self.assertIn("libraries", await r.text())
        r = await self.client.get("/licences/secrets.txt")
        self.assertEqual(r.status, 404)


if __name__ == "__main__":
    unittest.main()
