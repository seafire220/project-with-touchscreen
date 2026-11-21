#!/usr/bin/env python3
"""Start Character Studio on Windows, macOS or Linux, and open it in the browser.

    python3 launch.py [--setup-only] [app options, such as --port 8771 or --no-browser]

start.bat (Windows), start-mac.command (a Mac, double-clicked in Finder) and start.sh run this.

The first run makes the studio's own Python environment in ~/.character-studio (on Windows,
C:\\Users\\<you>\\.character-studio; CHARACTER_STUDIO_HOME chooses another folder) and installs into it:
PyTorch, built for this computer, and the studio's packages. That needs several GB and takes a while;
later runs start at once. The part-finding model itself is downloaded from the studio's page.

PyTorch comes as:
- on a Mac, the usual build, which uses the Mac's own graphics (Apple silicon);
- on Windows, the NVIDIA build when an NVIDIA card is found, otherwise the processor-only build;
- on Linux, the usual build (NVIDIA) when an NVIDIA card is found, otherwise the processor-only build,
  which is far smaller.
CHARACTER_STUDIO_TORCH_INDEX names another PyTorch package index (for an older NVIDIA card, say).

Uses only Python's own library, so it runs before anything is installed. Needs Python 3.10 or newer.
"""
import os
import platform
import shutil
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
# Raise when what is installed changes: the next start installs again.
SETUP_VERSION = 2
TORCH_CPU = "https://download.pytorch.org/whl/cpu"
# CUDA 12.6: still built for every current PyTorch and works with older NVIDIA cards and drivers.
TORCH_NVIDIA = "https://download.pytorch.org/whl/cu126"
REQUIREMENTS = ("requirements.txt", "requirements-app.txt", "requirements-model.txt")


def data_dir():
    return os.environ.get("CHARACTER_STUDIO_HOME") or os.path.join(os.path.expanduser("~"), ".character-studio")


def venv_python(env, windows=None):
    """The Python inside the studio's environment."""
    windows = os.name == "nt" if windows is None else windows
    return os.path.join(env, "Scripts", "python.exe") if windows else os.path.join(env, "bin", "python")


def has_nvidia():
    if shutil.which("nvidia-smi"):
        return True
    # Windows puts it here when it is not on the PATH.
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    return os.name == "nt" and os.path.exists(system32)


def torch_index(system=None, nvidia=None, override=None):
    """The package index PyTorch is installed from, or None for the usual one (PyPI)."""
    override = os.environ.get("CHARACTER_STUDIO_TORCH_INDEX") if override is None else override
    if override:
        return override
    system = system or platform.system()
    if system == "Darwin":
        return None
    nvidia = has_nvidia() if nvidia is None else nvidia
    if system == "Windows":
        return TORCH_NVIDIA if nvidia else TORCH_CPU
    return None if nvidia else TORCH_CPU


def install_steps(python, index):
    """The commands that set the environment up, in order."""
    torch = [python, "-m", "pip", "install", "torch", "torchvision"]
    if index:
        torch += ["--index-url", index]
    packages = [python, "-m", "pip", "install"]
    for name in REQUIREMENTS:
        packages += ["-r", os.path.join(HERE, name)]
    return [[python, "-m", "pip", "install", "--upgrade", "pip"], torch, packages]


def setup(env):
    """Make the studio's environment and install into it, unless that is already done."""
    marker = os.path.join(env, ".setup-%d" % SETUP_VERSION)
    if os.path.exists(marker):
        return
    print("Setting up Character Studio. The first time, this downloads PyTorch and the rest (several GB),",
          "and takes a while...", flush=True)
    python = venv_python(env)
    if not os.path.exists(python):
        venv.EnvBuilder(with_pip=True).create(env)
    index = torch_index()
    print("PyTorch from %s" % (index or "the usual place (PyPI)"), flush=True)
    for step in install_steps(python, index):
        result = subprocess.run(step)
        if result.returncode != 0:
            raise SystemExit("Setting up failed (%s). Check the internet connection and try again; what is "
                             "already downloaded is kept." % " ".join(step[1:5]))
    with open(marker, "w", encoding="utf-8") as f:
        f.write("set up by launch.py\n")


def main(argv):
    if sys.version_info < (3, 10):
        raise SystemExit("Character Studio needs Python 3.10 or newer; this is %s. Install a newer one from "
                         "https://www.python.org/downloads/ and start it again." % platform.python_version())
    setup_only = "--setup-only" in argv
    argv = [a for a in argv if a != "--setup-only"]
    data = data_dir()
    os.makedirs(data, exist_ok=True)
    env = os.path.join(data, "venv")
    setup(env)
    if setup_only:
        print("Character Studio is set up in %s" % env, flush=True)
        return 0
    # UTF-8 everywhere (Windows otherwise reads and writes text in its own older encodings).
    environ = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    command = [venv_python(env), os.path.join(HERE, "app.py"), "--data", data] + argv
    if os.name == "nt":
        # Windows: run it as a child, so this window shows it and closing the window stops it.
        try:
            return subprocess.call(command, env=environ)
        except KeyboardInterrupt:
            return 0
    os.execve(command[0], command, environ)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
