"""Tests for launch.py: which PyTorch each kind of computer gets, and where the environment lives."""
import os
import tempfile
import unittest
from unittest import mock

import launch


class LaunchTest(unittest.TestCase):
    def test_each_computer_gets_the_pytorch_for_its_graphics(self):
        self.assertIsNone(launch.torch_index("Darwin", nvidia=False, override=""), "a Mac: the usual build (Apple graphics)")
        self.assertEqual(launch.torch_index("Windows", nvidia=True, override=""), launch.TORCH_NVIDIA)
        self.assertEqual(launch.torch_index("Windows", nvidia=False, override=""), launch.TORCH_CPU)
        self.assertIsNone(launch.torch_index("Linux", nvidia=True, override=""), "Linux with NVIDIA: the usual build")
        self.assertEqual(launch.torch_index("Linux", nvidia=False, override=""), launch.TORCH_CPU)
        self.assertEqual(launch.torch_index("Windows", nvidia=True, override="https://example.org/whl/cu118"),
                         "https://example.org/whl/cu118", "the owner's choice wins")

    def test_the_environments_python_is_where_each_system_puts_it(self):
        self.assertEqual(launch.venv_python("E", windows=True), os.path.join("E", "Scripts", "python.exe"))
        self.assertEqual(launch.venv_python("E", windows=False), os.path.join("E", "bin", "python"))

    def test_setting_up_installs_pytorch_then_the_studios_packages(self):
        steps = launch.install_steps("py", launch.TORCH_CPU)
        self.assertEqual(steps[1][-2:], ["--index-url", launch.TORCH_CPU])
        files = [a for a in steps[2] if a.endswith(".txt")]
        self.assertEqual([os.path.basename(f) for f in files], list(launch.REQUIREMENTS))
        for f in files:
            self.assertTrue(os.path.exists(f), f)
        self.assertNotIn("--index-url", launch.install_steps("py", None)[1])

    def test_the_rigger_is_fetched_without_git(self):
        with open(os.path.join(launch.HERE, "requirements-app.txt"), encoding="utf-8") as f:
            line = next(x for x in f if x.startswith("image2live2d"))
        self.assertIn("/archive/", line)
        self.assertNotIn("git+", line)

    def test_a_set_up_studio_starts_without_installing_again(self):
        with tempfile.TemporaryDirectory() as home:
            env = os.path.join(home, "venv")
            os.makedirs(env)
            open(os.path.join(env, ".setup-%d" % launch.SETUP_VERSION), "w").close()
            with mock.patch.dict(os.environ, {"CHARACTER_STUDIO_HOME": home}), \
                    mock.patch.object(launch.subprocess, "run") as run, mock.patch.object(launch.venv, "EnvBuilder") as builder:
                self.assertEqual(launch.main(["--setup-only"]), 0)
            run.assert_not_called()
            builder.assert_not_called()

    def test_a_failed_download_says_so_and_can_be_tried_again(self):
        with tempfile.TemporaryDirectory() as home:
            env = os.path.join(home, "venv")
            failed = mock.Mock(returncode=1)
            with mock.patch.object(launch.subprocess, "run", return_value=failed), \
                    mock.patch.object(launch.venv, "EnvBuilder"), mock.patch.object(launch.os.path, "exists",
                                                                                 side_effect=lambda p: False):
                with self.assertRaises(SystemExit) as stopped:
                    launch.setup(env)
            self.assertIn("try again", str(stopped.exception))
            self.assertFalse(os.path.exists(os.path.join(env, ".setup-%d" % launch.SETUP_VERSION)))


if __name__ == "__main__":
    unittest.main()
