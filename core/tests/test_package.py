"""Tests for character packages."""
import io
import json
import os
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from companion import package  # noqa: E402


def puppet_bytes(header=None):
    payload = json.dumps(header or {"meta": {"name": "x"}, "nodes": {"name": "Root"}}).encode()
    return package.PUPPET_MAGIC + struct.pack(">I", len(payload)) + payload + b"TEX_SECT\0\0\0\0"


def manifest(**extra):
    m = {"format": 1, "id": "aria", "name": "Aria", "kind": "puppet", "author": "test"}
    m.update(extra)
    return m


def good_files():
    return {"persona.md": "You are Aria.", "visual/puppet.inp": puppet_bytes(), "voice.json": "{}"}


def raw_zip(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return io.BytesIO(out.getvalue())


class PackageTest(unittest.TestCase):
    def test_a_built_package_opens_with_its_parts(self):
        data = package.build(good_files(), manifest())
        p = package.open_package(io.BytesIO(data))
        self.assertEqual(p.id, "aria")
        self.assertEqual(p.kind, "puppet")
        self.assertEqual(p.persona, "You are Aria.")
        self.assertTrue(p.files["visual/puppet.inp"].startswith(package.PUPPET_MAGIC))

    def test_paths_that_escape_the_package_are_refused(self):
        for bad in ("../evil.json", "/etc/passwd", "visual\\puppet.inp", "visual/../../x.json"):
            entries = {"manifest.json": json.dumps(manifest()), "persona.md": "x", bad: "{}"}
            with self.assertRaises(package.PackageError, msg=bad):
                package.open_package(raw_zip(entries))

    def test_unknown_files_are_refused(self):
        entries = {"manifest.json": json.dumps(manifest()), "persona.md": "x",
                   "visual/puppet.inp": puppet_bytes(), "run.sh": "rm -rf /"}
        with self.assertRaises(package.PackageError) as e:
            package.open_package(raw_zip(entries))
        self.assertIn("run.sh", str(e.exception))

    def test_api_keys_anywhere_are_refused(self):
        for name, text in (("voice.json", '{"api_key": "abcd1234efgh5678"}'),
                           ("persona.md", "my key is sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX"),
                           ("behaviour.json", '{"note": "xi-api-key: 0123456789abcdef0123"}')):
            files = good_files()
            files[name] = text
            with self.assertRaises(package.PackageError, msg=name):
                package.build(files, manifest())
        files = good_files()
        files["visual/puppet.inp"] = puppet_bytes({"nodes": {}, "meta": {"note": "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA"}})
        with self.assertRaises(package.PackageError):
            package.build(files, manifest())

    def test_a_package_needs_its_manifest_persona_and_visual(self):
        with self.assertRaises(package.PackageError):
            package.open_package(raw_zip({"persona.md": "x"}))
        with self.assertRaises(package.PackageError):
            package.build({"persona.md": "x"}, manifest())
        with self.assertRaises(package.PackageError):
            package.build({"visual/puppet.inp": puppet_bytes()}, manifest())

    def test_bad_manifests_are_explained(self):
        for bad in (manifest(format=2), manifest(id="Bad Id!"), manifest(name=""), manifest(kind="vrm"),
                    manifest(capabilities={"blink": "yes"})):
            with self.assertRaises(package.PackageError):
                package.build(good_files(), bad)

    def test_damaged_puppets_and_pictures_are_refused(self):
        files = good_files()
        files["visual/puppet.inp"] = b"NOTAPUPPET"
        with self.assertRaises(package.PackageError):
            package.build(files, manifest())
        files = good_files()
        files["preview.png"] = b"\x89PNG not really"
        with self.assertRaises(package.PackageError):
            package.build(files, manifest())

    def test_a_zip_bomb_is_refused(self):
        entries = {"manifest.json": json.dumps(manifest()), "persona.md": "x" * 200000,
                   "visual/puppet.inp": puppet_bytes()}
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries.items():
                z.writestr(name, data)
        with self.assertRaises(package.PackageError) as e:
            package.open_package(io.BytesIO(out.getvalue()))
        self.assertIn("compressed", str(e.exception))

    def test_not_a_zip(self):
        with self.assertRaises(package.PackageError):
            package.open_package(io.BytesIO(b"hello"))

    def test_slug(self):
        self.assertEqual(package.slug("Alice the Knight!"), "alice-the-knight")
        self.assertEqual(package.slug("???"), "character")


def live2d_files(**changes):
    """A Live2D-format model as the studio writes it: index, model file, a texture, physics and a motion."""
    png = io.BytesIO()
    from PIL import Image
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(png, "PNG")
    refs = {"Moc": "model.moc3", "Textures": ["textures/00_face.png"], "Physics": "model.physics3.json",
            "DisplayInfo": "model.cdi3.json", "Motions": {"Idle": [{"File": "motions/model.idle.motion3.json"}]}}
    refs.update(changes)
    return {
        "visual/live2d/model.model3.json": json.dumps({"Version": 3, "FileReferences": refs}),
        "visual/live2d/model.moc3": b"MOC3\x01" + b"\0" * 123,
        "visual/live2d/model.physics3.json": "{}",
        "visual/live2d/model.cdi3.json": "{}",
        "visual/live2d/motions/model.idle.motion3.json": "{}",
        "visual/live2d/textures/00_face.png": png.getvalue(),
    }


class Live2DPackageTest(unittest.TestCase):
    def test_a_package_can_carry_both_formats(self):
        files = good_files()
        files.update(live2d_files())
        pkg = package.open_package(io.BytesIO(package.build(files, manifest())))
        self.assertIn("visual/live2d/model.moc3", pkg.files)
        self.assertIn("visual/puppet.inp", pkg.files)

    def test_a_live2d_format_model_alone_is_a_puppet(self):
        files = {"persona.md": "You are Aria.", "voice.json": "{}"}
        files.update(live2d_files())
        package.open_package(io.BytesIO(package.build(files, manifest())))

    def test_the_index_must_name_only_files_that_are_there(self):
        for refs, why in (({"Textures": ["textures/missing.png"]}, "not in the package"),
                          ({"Physics": "../../persona.md"}, "outside the model"),
                          ({"Moc": "other.moc3"}, "model.moc3"),
                          ({"Motions": ["not", "a", "map"]}, "laid out")):
            files = good_files()
            files.update(live2d_files(**refs))
            with self.assertRaises(package.PackageError) as e:
                package.build(files, manifest())
            self.assertIn(why, str(e.exception))

    def test_damaged_or_secret_bearing_model_files_are_refused(self):
        for moc, why in ((b"NOPE" + b"\0" * 124, "not a Live2D-format"),
                         (b"MOC3\x01" + b"\0" * 20 + b"sk-ant-" + b"a" * 40 + b"\0" * 60, "API key")):
            files = good_files()
            files.update(live2d_files())
            files["visual/live2d/model.moc3"] = moc
            with self.assertRaises(package.PackageError) as e:
                package.build(files, manifest())
            self.assertIn(why, str(e.exception))

    def test_other_files_beside_the_model_are_refused(self):
        files = good_files()
        files.update(live2d_files())
        files["visual/live2d/run.sh"] = "echo hi"
        with self.assertRaises(package.PackageError):
            package.build(files, manifest())


if __name__ == "__main__":
    unittest.main()
