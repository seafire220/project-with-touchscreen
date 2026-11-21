"""Tests for launch.py: which PyTorch each kind of computer gets, where the environment lives, and the app's
way in (its page, its progress, finding an app already running, an environment that moved)."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import venv
from unittest import mock

import launch

LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


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
        self.assertTrue(launch.env_dir("D").endswith("venv-%d.%d" % sys.version_info[:2]), "one per Python version")

    def test_setting_up_installs_pytorch_then_the_studios_packages(self):
        steps = launch.install_steps("py", launch.TORCH_CPU, raw_progress=True)
        names = [name for name, _ in steps]
        self.assertEqual(len(names), 3)
        torch = steps[1][1]
        self.assertEqual(torch[-2:], ["--index-url", launch.TORCH_CPU])
        self.assertIn("raw", torch, "the app shows real download progress")
        files = [a for a in steps[2][1] if a.endswith(".txt")]
        self.assertEqual([os.path.basename(f) for f in files], list(launch.REQUIREMENTS))
        for f in files:
            self.assertTrue(os.path.exists(f), f)
        self.assertNotIn("--index-url", launch.install_steps("py", None)[1][1])
        self.assertNotIn("raw", launch.install_steps("py", None)[1][1])

    def test_the_rigger_is_fetched_without_git(self):
        with open(os.path.join(launch.HERE, "requirements-app.txt"), encoding="utf-8") as f:
            line = next(x for x in f if x.startswith("image2live2d"))
        self.assertIn("/archive/", line)
        self.assertNotIn("git+", line)

    def test_a_set_up_studio_starts_without_installing_again(self):
        with tempfile.TemporaryDirectory() as home:
            env = launch.env_dir(home)
            os.makedirs(env)
            open(launch.marker_path(env), "w").close()
            with mock.patch.dict(os.environ, {"CHARACTER_STUDIO_HOME": home}), \
                    mock.patch.object(launch.subprocess, "run") as run, mock.patch.object(launch, "make_env") as make:
                self.assertEqual(launch.main(["--setup-only"]), 0)
            run.assert_not_called()
            make.assert_called_once_with(env)

    def test_a_failed_download_says_so_and_can_be_tried_again(self):
        with tempfile.TemporaryDirectory() as home:
            env = launch.env_dir(home)
            failed = mock.Mock(returncode=1)
            with mock.patch.object(launch.subprocess, "run", return_value=failed), \
                    mock.patch.object(launch, "make_env"):
                with self.assertRaises(SystemExit) as stopped:
                    launch.setup(env)
            self.assertIn("try again", str(stopped.exception))
            self.assertFalse(os.path.exists(launch.marker_path(env)))


class AppWayTest(unittest.TestCase):
    def test_pips_output_becomes_progress_for_the_page(self):
        p = launch.Progress()
        p.line("Collecting torch")
        self.assertEqual(p.state["detail"], "Looking up torch")
        p.line("Downloading https://download.pytorch.org/whl/cpu/torch-2.15.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl (183.8 MB)")
        self.assertEqual((p.state["detail"], p.state["fraction"]), ("Downloading torch (183.8 MB)", 0.0))
        p.line("Progress 45950000 of 183800000")
        self.assertAlmostEqual(p.state["fraction"], 0.25)
        p.line("Installing collected packages: numpy, torch")
        self.assertIsNone(p.state["fraction"], "installing: no measure, the bar just moves")
        self.assertEqual(launch.package_name("opencv_python_headless-4.12.0.88-cp37-abi3-win_amd64.whl"),
                         "opencv_python_headless")

    def test_the_apps_page_answers_this_computer_only(self):
        p = launch.Progress()
        p.set(phase="failed", error="It broke")
        port = launch.free_port(18769)
        log = open(os.devnull, "w")
        server = launch.make_control_server(p, port, log)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % port
        try:
            with LOCAL.open(base + "/", timeout=5) as r:
                self.assertIn("<title>Character Studio</title>", r.read().decode())
            with LOCAL.open(base + "/launcher/status", timeout=5) as r:
                self.assertEqual(json.loads(r.read())["error"], "It broke")
            # Try again needs the page's own header; another site cannot add it.
            with self.assertRaises(urllib.error.HTTPError) as refused:
                LOCAL.open(urllib.request.Request(base + "/launcher/retry", data=b"", method="POST"), timeout=5)
            self.assertEqual(refused.exception.code, 403)
            self.assertFalse(p.retry.is_set())
            LOCAL.open(urllib.request.Request(base + "/launcher/repair", data=b"", method="POST",
                                              headers={"X-Studio": "1"}), timeout=5).close()
            self.assertTrue(p.retry.is_set() and p.repair)
            # A page reached under another name (DNS rebinding) is refused.
            with self.assertRaises(urllib.error.HTTPError) as refused:
                LOCAL.open(urllib.request.Request(base + "/launcher/status", headers={"Host": "evil.example:%d" % port}),
                           timeout=5)
            self.assertEqual(refused.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            log.close()

    def test_opening_the_app_again_finds_the_one_running(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(launch.already_running(home))
            p = launch.Progress()
            port = launch.free_port(18779)
            log = open(os.devnull, "w")
            server = launch.make_control_server(p, port, log)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                launch.write_running(home, control=port, studio=port + 50)
                self.assertEqual(launch.already_running(home), "http://127.0.0.1:%d/" % port,
                                 "still setting up: its page")
            finally:
                server.shutdown()
                server.server_close()
                log.close()

    def test_an_environment_made_somewhere_else_is_pointed_at_this_python(self):
        with tempfile.TemporaryDirectory() as home:
            env = os.path.join(home, "venv")
            venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(env)
            self.assertTrue(launch.same_folder(launch.venv_home(env), launch.base_home()))
            # As if the app had been moved since (or opened from a new place).
            cfg = os.path.join(env, "pyvenv.cfg")
            old = launch.venv_home(env)
            with open(cfg, encoding="utf-8") as f:
                text = f.read()
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(text.replace(old, os.path.join(home, "gone", "bin")))
            self.assertFalse(launch.same_folder(launch.venv_home(env), launch.base_home()))
            open(os.path.join(env, "kept.txt"), "w").close()
            if os.name != "nt":
                # Its python links point where the old Python was (an AppImage opened before, say).
                python = launch.venv_python(env)
                os.remove(python)
                os.symlink(os.path.join(home, "gone", "bin", "python3"), python)
                self.assertFalse(os.path.exists(python))
            launch.make_env(env)
            self.assertTrue(launch.same_folder(launch.venv_home(env), launch.base_home()), "pointed at this Python")
            self.assertTrue(os.path.exists(os.path.join(env, "kept.txt")), "and nothing in it lost")
            out = launch.subprocess.run([launch.venv_python(env), "-c", "import sys; print(sys.prefix)"],
                                        capture_output=True, text=True)
            self.assertTrue(launch.same_folder(out.stdout.strip(), env), "and its Python runs in it")
            if os.name != "nt":
                self.assertTrue(os.path.islink(launch.venv_python(env)), "a link to the Python, not a copy")

    def test_a_step_that_fails_says_which_in_plain_words(self):
        p = launch.Progress()
        with tempfile.TemporaryDirectory() as home, mock.patch.object(launch, "make_env"), \
                mock.patch.object(launch, "run_logged", side_effect=[True, False]):
            with self.assertRaises(launch.SetupError) as failed:
                launch.app_setup(launch.env_dir(home), p, open(os.devnull, "w"), os.devnull)
        self.assertEqual(str(failed.exception), "Could not finish this step: download PyTorch, the AI library. "
                         "Check the internet connection, then Try again: what is already downloaded is kept.")
        self.assertEqual(p.state["step"], 2)
        self.assertTrue(p.state["first_run"])

    def test_the_studios_python_can_be_asked_for(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"CHARACTER_STUDIO_HOME": home}), \
                mock.patch("builtins.print") as said:
            self.assertEqual(launch.main(["--print-python"]), 0)
        self.assertEqual(said.call_args[0][0], launch.venv_python(launch.env_dir(home)))


if __name__ == "__main__":
    unittest.main()
