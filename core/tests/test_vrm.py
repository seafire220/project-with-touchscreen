"""VRM avatars: checking, fitting to the device, packaging, installing, showing and uploading."""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from companion import package, vrm  # noqa: E402
from companion.characters import Characters  # noqa: E402
from vrm_sample import sample_vrm  # noqa: E402


class VrmTest(unittest.TestCase):
    def test_vrm_files_are_told_apart(self):
        self.assertTrue(vrm.is_vrm(sample_vrm(1)))
        self.assertTrue(vrm.is_vrm(sample_vrm(0)))
        self.assertFalse(vrm.is_vrm(b"glTF\x02\x00\x00\x00" + b"\x00" * 30))
        self.assertFalse(vrm.is_vrm(b"PK\x03\x04 a zip"))

    def test_an_avatar_becomes_a_character_package_with_its_terms_and_feelings(self):
        for version in (1, 0):
            pkg = package.open_package(io.BytesIO(package.from_vrm(sample_vrm(version))))
            self.assertEqual(pkg.id, "sample")
            self.assertIn(package.VRM_MODEL, pkg.files)
            m = pkg.manifest
            self.assertTrue(m["capabilities"]["vrm"] and m["capabilities"]["blink"] and m["capabilities"]["speak"])
            self.assertIn("Test Maker", m["licence"])
            self.assertIn("anyone may use it as an avatar", m["licence"])
            self.assertIn("responsible", m["licence"])
            self.assertEqual(m["author"], "Test Maker")
            feelings = pkg.json("visual/emotions.json")
            self.assertEqual(feelings["happy"], "happy")
            self.assertEqual(feelings["embarrassed"], "Blush", "a custom expression named for a blush")
            self.assertIn("preview.png", pkg.files, "the avatar's own thumbnail")
            self.assertIn("{name}".replace("{name}", "Sample"), pkg.files["persona.md"].decode())

    def test_large_textures_are_scaled_down_once_and_the_rest_is_kept(self):
        from PIL import Image
        original = sample_vrm(1, texture_side=2048)
        doc0, bin0 = vrm.read_glb(original)
        data = package.open_package(io.BytesIO(package.from_vrm(original, texture_side=1024))).files[package.VRM_MODEL]
        doc, binary = vrm.read_glb(data)
        view = doc["bufferViews"][doc["images"][0]["bufferView"]]
        with Image.open(io.BytesIO(binary[view["byteOffset"]:view["byteOffset"] + view["byteLength"]])) as im:
            self.assertEqual(im.size, (1024, 1024))
        # The mesh's own data is carried over unchanged.
        for k in (0,):
            a, b = doc0["bufferViews"][k], doc["bufferViews"][k]
            self.assertEqual(bin0[a["byteOffset"]:a["byteOffset"] + a["byteLength"]],
                             binary[b["byteOffset"]:b["byteOffset"] + b["byteLength"]])
            self.assertEqual(b["byteOffset"] % 4, 0)
        self.assertTrue(0 <= len(binary) - doc["buffers"][0]["byteLength"] < 4, "the chunk is padded to 4 bytes")
        small = package.from_vrm(sample_vrm(1, texture_side=256), texture_side=1024)
        doc, _ = vrm.read_glb(package.open_package(io.BytesIO(small)).files[package.VRM_MODEL])
        self.assertEqual(len(doc["images"]), 2)

    def test_unusable_avatars_are_refused_with_a_reason(self):
        with self.assertRaisesRegex(package.PackageError, "leftHand"):
            package.from_vrm(sample_vrm(1, drop_bone="leftHand"))
        with self.assertRaisesRegex(package.PackageError, "separate file"):
            package.from_vrm(sample_vrm(1, external=True))
        with self.assertRaisesRegex(package.PackageError, "API key"):
            package.from_vrm(sample_vrm(1, meta={"otherLicenseUrl": "sk-ant-api03-" + "a" * 40}))
        with self.assertRaises(package.PackageError):
            package.from_vrm(b"glTF\x02\x00\x00\x00\x14\x00\x00\x00" + b"\x00" * 8)

    def test_an_avatar_only_its_maker_may_use_is_marked(self):
        pkg = package.open_package(io.BytesIO(package.from_vrm(sample_vrm(1, meta={"avatarPermission": "onlyAuthor"}))))
        self.assertIn("only its maker", pkg.manifest["licence_note"].replace("allows only themselves", "only its maker"))
        pkg = package.open_package(io.BytesIO(package.from_vrm(sample_vrm(0))))
        self.assertIn("no commercial use", pkg.manifest["licence"])

    def test_an_installed_avatar_offers_its_expressions_and_is_drawn_as_3d(self):
        with tempfile.TemporaryDirectory() as d:
            chars = Characters(d)
            cid = chars.install(package.from_vrm(sample_vrm(1)))
            self.assertEqual(chars.drawing(cid), "vrm")
            self.assertEqual(set(chars.expressions(cid)), {"happy", "sad", "aa", "blink", "Blush", "Hmm"})
            self.assertEqual(chars.emotion_map(cid)["embarrassed"], "Blush")
            listed = next(c for c in chars.list() if c["id"] == cid)
            self.assertEqual(listed["drawing"], "vrm")
            self.assertIn("Test Maker", listed["licence"])
            cid0 = chars.install(package.from_vrm(sample_vrm(0), name="Old Sample"))
            self.assertEqual(set(chars.expressions(cid0)), {"happy", "aa", "blink", "Blush"})


if __name__ == "__main__":
    unittest.main()
