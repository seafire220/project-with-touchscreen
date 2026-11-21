#!/usr/bin/env python3
"""Start Character Studio on Windows, macOS or Linux.

Two ways in:

- **The Character Studio app**, which buyers install (`studio/packaging/`): it runs
  `launch.py --desktop` with its own Python. Nothing shows but the browser. A page there says what is
  happening (the first time, the one-time download, with its progress), then the studio opens in its
  place. The studio's Quit button stops it, and so does leaving its page closed for a while. Opening the
  app again while it runs just shows the page again.
- **From the project's files** (developers): `python3 launch.py [app options]`, which start.sh,
  start.bat and start-mac.command run, with what it does written in the window.

Either way, the first start makes the studio's own Python environment in ~/.character-studio (on Windows,
C:\\Users\\<you>\\.character-studio; CHARACTER_STUDIO_HOME chooses another folder) and installs into it
PyTorch, built for this computer, and the studio's packages: about 1 GB (3 GB with an NVIDIA card) and a
few minutes. Later starts take seconds. The part-finding model itself is downloaded from the studio's page.

PyTorch comes as:
- on a Mac, the usual build, which uses the Mac's own graphics (Apple silicon);
- on Windows, the NVIDIA build when an NVIDIA card is found, otherwise the processor-only build;
- on Linux, the usual build (NVIDIA) when an NVIDIA card is found, otherwise the processor-only build,
  which is far smaller.
CHARACTER_STUDIO_TORCH_INDEX names another PyTorch package index (for an older NVIDIA card, say).

`--self-test` runs the app's way in without a browser, checks each step answers, and quits (the
"Make the Character Studio apps" workflow runs it on each installed app). `--setup-only` sets up and stops.

Uses only Python's own library, so it runs before anything is installed. Needs Python 3.10 or newer.
"""
import http.server
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
# Raise when what is installed changes: the next start installs again.
SETUP_VERSION = 2
TORCH_CPU = "https://download.pytorch.org/whl/cpu"
# CUDA 12.6: still built for every current PyTorch and works with older NVIDIA cards and drivers.
TORCH_NVIDIA = "https://download.pytorch.org/whl/cu126"
REQUIREMENTS = ("requirements.txt", "requirements-app.txt", "requirements-model.txt")
# The app's ports: its own small page first, then the studio's (the next free ones if these are taken).
CONTROL_PORT = 8769
STUDIO_PORT = 8770
# Started from the app, the studio stops by itself once its page has been closed this long.
IDLE_MINUTES = 15
# Windows: start helper programs without a console window of their own.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Requests to this computer never go through a proxy.
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def data_dir():
    return os.environ.get("CHARACTER_STUDIO_HOME") or os.path.join(os.path.expanduser("~"), ".character-studio")


def env_dir(data):
    """The studio's environment, one per Python version (an app update with a newer Python makes a new one)."""
    return os.path.join(data, "venv-%d.%d" % sys.version_info[:2])


def marker_path(env):
    return os.path.join(env, ".setup-%d" % SETUP_VERSION)


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


def download_size(index):
    """Roughly how much the first start downloads, for the page."""
    return "about 3 GB" if index == TORCH_NVIDIA or (index is None and platform.system() == "Linux") else "about 1 GB"


def install_steps(python, index, raw_progress=False):
    """The commands that set the environment up, in order: (what the page calls it, command)."""
    progress = ["--progress-bar", "raw"] if raw_progress else []
    torch = [python, "-m", "pip", "install", *progress, "torch", "torchvision"]
    if index:
        torch += ["--index-url", index]
    packages = [python, "-m", "pip", "install", *progress]
    for name in REQUIREMENTS:
        packages += ["-r", os.path.join(HERE, name)]
    return [
        ("Get the installer ready", [python, "-m", "pip", "install", "--upgrade", "pip"]),
        ("Download PyTorch, the AI library", torch),
        ("Download the studio's other parts", packages),
    ]


def venv_home(env):
    """The folder of the Python the environment was made from (its pyvenv.cfg says)."""
    try:
        with open(os.path.join(env, "pyvenv.cfg"), encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() == "home":
                    return value.strip()
    except OSError:
        pass
    return None


def base_home():
    """The folder of the Python running this (the app's own, or the developer's)."""
    return os.path.dirname(getattr(sys, "_base_executable", None) or sys.executable)


def same_folder(a, b):
    return bool(a and b) and os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def make_env(env):
    """Make the environment, or point it at this Python again if it was made from one somewhere else (the
    app moved: a Mac app from Downloads to Applications, or an AppImage, which opens at a new place each
    time). The packages in it stay: the gigabytes are never downloaded again for that."""
    # Links to the Python, as `python -m venv` makes them (a copy of the app's Python would not find its
    # library on a Mac); Windows has its own small starter programs instead.
    links = os.name != "nt"
    if not os.path.exists(os.path.join(env, "pyvenv.cfg")):
        venv.EnvBuilder(with_pip=True, clear=os.path.isdir(env), symlinks=links).create(env)
        return
    if same_folder(venv_home(env), base_home()) and os.path.exists(venv_python(env)):
        return
    if os.name != "nt":
        # Its pythons point at the old place; venv keeps those that are there, so take them away first.
        bindir = os.path.join(env, "bin")
        for name in os.listdir(bindir):
            if re.fullmatch(r"python(\d+(\.\d+)?)?", name):
                os.remove(os.path.join(bindir, name))
    venv.EnvBuilder(upgrade=True, symlinks=links).create(env)


class SetupError(Exception):
    pass


# ------------------------------------------------------------------------------------------------
# From the project's files (developers)
# ------------------------------------------------------------------------------------------------

def setup(env):
    """Make the studio's environment and install into it, unless that is already done."""
    if os.path.exists(marker_path(env)):
        make_env(env)
        return
    print("Setting up Character Studio. The first time, this downloads PyTorch and the rest (%s)," %
          download_size(torch_index()), "and takes a while...", flush=True)
    make_env(env)
    python = venv_python(env)
    index = torch_index()
    print("PyTorch from %s" % (index or "the usual place (PyPI)"), flush=True)
    for _, step in install_steps(python, index):
        result = subprocess.run(step)
        if result.returncode != 0:
            raise SystemExit("Setting up failed (%s). Check the internet connection and try again; what is "
                             "already downloaded is kept." % " ".join(step[1:5]))
    with open(marker_path(env), "w", encoding="utf-8") as f:
        f.write("set up by launch.py\n")


# ------------------------------------------------------------------------------------------------
# The app's way in: a page in the browser while it sets up and starts, then the studio
# ------------------------------------------------------------------------------------------------

PIP_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)")
PIP_DOWNLOAD = re.compile(r"Downloading (\S+) \(([\d.,]+ [kMG]?B)\)")


def package_name(file_or_url):
    """`.../torch-2.15.0%2Bcpu-cp312-...whl` -> `torch`."""
    name = file_or_url.rstrip("/").rsplit("/", 1)[-1]
    return re.split(r"-\d", name, maxsplit=1)[0]


class Progress:
    """What the app is doing, for its page. Shared between the work and the page's server."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"phase": "starting", "first_run": False, "size": "", "steps": [], "step": -1,
                      "detail": "", "fraction": None, "error": None, "log": "", "studio": None}
        self.retry = threading.Event()
        self.repair = False
        self.last_poll = time.monotonic()

    def set(self, **changes):
        with self.lock:
            self.state.update(changes)

    def snapshot(self):
        with self.lock:
            self.last_poll = time.monotonic()
            return dict(self.state)

    def line(self, text):
        """A line from pip: what it is downloading, and how far."""
        m = PIP_PROGRESS.match(text)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            if total > 0:
                self.set(fraction=min(1.0, done / total))
            return
        m = PIP_DOWNLOAD.search(text)
        if m:
            self.set(detail="Downloading %s (%s)" % (package_name(m.group(1)), m.group(2)), fraction=0.0)
        elif text.startswith("Installing collected packages"):
            self.set(detail="Installing (a minute or two)", fraction=None)
        elif text.startswith("Collecting "):
            self.set(detail="Looking up %s" % re.split(r"[ <>=!~\[;@]", text[len("Collecting "):], maxsplit=1)[0])


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Character Studio</title>
<style>
  :root { color-scheme: light dark; --bg: #f6f5f2; --card: #fff; --ink: #1d1d1f; --muted: #6b6b70; --accent: #5b5bd6; }
  @media (prefers-color-scheme: dark) { :root { --bg: #17171a; --card: #222227; --ink: #ececf1; --muted: #a0a0aa; } }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 560px; margin: 10vh auto; padding: 0 16px; }
  .card { background: var(--card); border-radius: 16px; padding: 28px; box-shadow: 0 2px 16px rgba(0,0,0,.08); }
  h1 { font-size: 1.5rem; margin: 0 0 6px; }
  .muted { color: var(--muted); }
  ol { padding-left: 1.4em; } li { margin: 4px 0; } li.done { color: var(--muted); } li.now { font-weight: 600; }
  li.done::after { content: "  \\2713"; color: #2e9d52; }
  progress { width: 100%; height: 10px; accent-color: var(--accent); }
  .error { color: #c0362c; white-space: pre-wrap; }
  button { font: inherit; padding: 8px 16px; border-radius: 8px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; }
  button.secondary { background: transparent; color: var(--accent); }
  pre { max-height: 220px; overflow: auto; font-size: 12px; background: rgba(127,127,127,.12); padding: 8px; border-radius: 6px; white-space: pre-wrap; }
</style>
</head>
<body>
<main><div class="card">
  <h1>Character Studio</h1>
  <p id="what" class="muted">Opening Character Studio&hellip;</p>
  <ol id="steps" hidden></ol>
  <progress id="bar" max="1"></progress>
  <p id="detail" class="muted"></p>
  <div id="failed" hidden>
    <p id="error" class="error"></p>
    <p><button id="retry">Try again</button> <button id="repair" class="secondary">Repair (download again)</button></p>
    <details><summary>Details for support</summary><pre id="log"></pre></details>
  </div>
</div></main>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
async function act(path) { await fetch(path, { method: "POST", headers: { "X-Studio": "1" } }); }
$("retry").onclick = () => act("/launcher/retry");
$("repair").onclick = () => act("/launcher/repair");
async function poll() {
  let s;
  try { s = await (await fetch("/launcher/status", { cache: "no-store" })).json(); }
  catch (e) { $("what").textContent = "Character Studio has stopped. You can close this tab."; $("bar").hidden = true; return; }
  if (s.phase === "ready" && s.studio) { location.replace(s.studio); return; }
  $("what").textContent = s.first_run
    ? "Setting up, the first time only: it downloads its AI tools (" + s.size + ") and takes a few minutes. " +
      "Leave this page open; the studio opens here when it is ready."
    : "Opening Character Studio\\u2026";
  const steps = $("steps");
  steps.hidden = !s.first_run;
  steps.replaceChildren(...s.steps.map((name, i) => {
    const li = document.createElement("li");
    li.textContent = name;
    li.className = i < s.step ? "done" : i === s.step ? "now" : "";
    return li;
  }));
  const bar = $("bar");
  if (s.fraction === null || s.fraction === undefined) bar.removeAttribute("value"); else bar.value = s.fraction;
  bar.hidden = s.phase === "failed";
  $("detail").textContent = s.phase === "failed" ? "" : s.detail;
  $("failed").hidden = s.phase !== "failed";
  $("error").textContent = s.error || "";
  $("log").textContent = s.log || "";
  setTimeout(poll, 700);
}
poll();
</script>
</body>
</html>
"""


def make_control_server(progress, port, log):
    """The app's own small page and its status, on this computer only."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.write("page: " + (fmt % args) + "\n")

        def _host_ok(self):
            return self.headers.get("Host") in ("127.0.0.1:%d" % port, "localhost:%d" % port)

        def _send(self, code, body, kind):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, "only on this computer", "text/plain")
            if self.path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if self.path == "/launcher/status":
                return self._send(200, json.dumps(progress.snapshot()), "application/json")
            return self._send(404, "not found", "text/plain")

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Studio") != "1":
                return self._send(403, "not allowed", "text/plain")
            if self.path in ("/launcher/retry", "/launcher/repair"):
                progress.repair = self.path.endswith("repair")
                progress.retry.set()
                return self._send(200, "{}", "application/json")
            return self._send(404, "not found", "text/plain")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def free_port(first, avoid=()):
    for port in range(first, first + 30):
        if port in avoid:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name != "nt":
                # As the servers do: a port just closed (still in TIME_WAIT) is free to use.
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SetupError("No free port on this computer for the studio")


def get_json(url, timeout=2.0):
    try:
        with LOCAL.open(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")) if r.status == 200 else None
    except (OSError, ValueError):
        return None


def running_file(data):
    return os.path.join(data, "running.json")


def already_running(data):
    """The page of an app already running (the studio's, or its setup page), if there is one."""
    try:
        with open(running_file(data), encoding="utf-8") as f:
            ports = json.load(f)
    except (OSError, ValueError):
        ports = {}
    studio = int(ports.get("studio") or STUDIO_PORT)
    control = int(ports.get("control") or CONTROL_PORT)
    status = get_json("http://127.0.0.1:%d/api/status" % studio, timeout=1.0)
    if isinstance(status, dict) and "finder" in status:
        return "http://127.0.0.1:%d/" % studio
    status = get_json("http://127.0.0.1:%d/launcher/status" % control, timeout=1.0)
    if isinstance(status, dict) and "phase" in status:
        return "http://127.0.0.1:%d/" % control
    return None


def write_running(data, **ports):
    try:
        with open(running_file(data), "w", encoding="utf-8") as f:
            json.dump(dict(ports, pid=os.getpid()), f)
    except OSError:
        pass


def open_log(data):
    """The app's log, for support (the app has no window to write in). Started afresh when it grows large."""
    path = os.path.join(data, "launcher.log")
    try:
        if os.path.getsize(path) > 5 * 1024 * 1024:
            os.replace(path, path + ".old")
    except OSError:
        pass
    log = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    log.write("\n== %s: Character Studio starting (Python %s, %s)\n" %
              (time.strftime("%Y-%m-%d %H:%M:%S"), platform.python_version(), platform.platform()))
    return log, path


def tail(path, lines=40):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def run_logged(command, progress, log):
    """Run one setup step, its output to the log and its progress to the page. True if it worked."""
    environ = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1",
                   PIP_NO_INPUT="1")
    log.write("$ %s\n" % " ".join(command))
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               env=environ, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    for text in process.stdout:
        text = text.rstrip()
        if not PIP_PROGRESS.match(text):
            log.write(text + "\n")
        progress.line(text.strip())
    return process.wait() == 0


def app_setup(env, progress, log, log_path):
    """Set the environment up for the app, showing each step on the page. Raises SetupError."""
    if progress.repair and os.path.isdir(env):
        log.write("Repair: making the environment again\n")
        shutil.rmtree(env, ignore_errors=True)
    progress.repair = False
    if os.path.exists(marker_path(env)):
        make_env(env)
        return
    index = torch_index()
    steps = install_steps(venv_python(env), index, raw_progress=True)
    names = ["Make its own copy of Python"] + [name for name, _ in steps] + ["Start the studio"]
    progress.set(first_run=True, size=download_size(index), steps=names, step=0, detail="", fraction=None,
                 error=None)
    log.write("PyTorch from %s\n" % (index or "PyPI"))
    try:
        make_env(env)
    except Exception as error:   # venv reports problems in several ways
        raise SetupError("Could not make the studio's own Python environment (%s)" % error)
    for i, (name, command) in enumerate(steps, start=1):
        progress.set(step=i, detail="", fraction=None)
        if not run_logged(command, progress, log):
            raise SetupError("Could not finish this step: %s. Check the internet connection, then Try again: "
                             "what is already downloaded is kept." % (name[0].lower() + name[1:]))
    with open(marker_path(env), "w", encoding="utf-8") as f:
        f.write("set up by the Character Studio app\n")
    progress.set(step=len(names) - 1, detail="", fraction=None)


def start_studio(env, data, port, log):
    command = [venv_python(env), os.path.join(HERE, "app.py"), "--data", data, "--port", str(port), "--no-browser",
               "--exit-when-idle", str(IDLE_MINUTES)]
    # The app's own files are never written to (an AppImage cannot be; a signed Mac app must not change).
    environ = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    log.write("$ %s\n" % " ".join(command))
    return subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=environ,
                            creationflags=NO_WINDOW)


def wait_until_answers(port, process, timeout=180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SetupError("The studio stopped as it started.")
        status = get_json("http://127.0.0.1:%d/api/status" % port, timeout=2.0)
        if isinstance(status, dict) and "finder" in status:
            return
        time.sleep(0.3)
    process.kill()
    raise SetupError("The studio did not start within three minutes.")


def desktop(browser=True, ready=None):
    """The app's way in. Returns when the studio stops. `ready(url)` hears the studio's address (tests)."""
    data = data_dir()
    os.makedirs(data, exist_ok=True)
    log, log_path = open_log(data)
    if sys.stdout is None or os.name == "nt" and sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = log      # no console (pythonw, or an app on a Mac): write to the log
    url = already_running(data)
    if url:
        log.write("Already running: %s\n" % url)
        if browser:
            webbrowser.open(url)
        return 0
    progress = Progress()
    control_port = free_port(CONTROL_PORT)
    if control_port != CONTROL_PORT:
        # Opened twice at once? The first is on the usual port by now.
        time.sleep(0.5)
        url = already_running(data)
        if url:
            log.write("Already starting: %s\n" % url)
            if browser:
                webbrowser.open(url)
            return 0
    server = make_control_server(progress, control_port, log)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    page = "http://127.0.0.1:%d/" % control_port
    write_running(data, control=control_port)
    log.write("Its page: %s\n" % page)
    if browser:
        webbrowser.open(page)
    env = env_dir(data)
    try:
        while True:
            try:
                app_setup(env, progress, log, log_path)
                studio_port = free_port(STUDIO_PORT, avoid=(control_port,))
                if not progress.state["first_run"]:
                    progress.set(steps=["Start the studio"], step=0)
                studio = start_studio(env, data, studio_port, log)
                wait_until_answers(studio_port, studio)
                url = "http://127.0.0.1:%d/" % studio_port
                write_running(data, control=control_port, studio=studio_port)
                progress.set(phase="ready", studio=url)
                log.write("The studio is at %s\n" % url)
                if ready:
                    ready(url)
                code = studio.wait()
                log.write("The studio stopped (%s)\n" % code)
                return 0
            except SetupError as error:
                log.write("Failed: %s\n" % error)
                progress.set(phase="failed", error=str(error), log=tail(log_path), fraction=None)
                progress.retry.clear()
                # Wait for Try again; give up once nobody has looked at the page for half an hour.
                while not progress.retry.wait(timeout=5.0):
                    if time.monotonic() - progress.last_poll > 1800:
                        return 1
                progress.set(phase="starting", error=None, log="")
    finally:
        server.shutdown()
        try:
            os.remove(running_file(data))
        except OSError:
            pass
        log.write("== stopped\n")


def self_test(timeout=2400.0):
    """Start the app's way without a browser, as a buyer's computer would, check its page, the setup, and the
    studio; then quit with the studio's own Quit. For the workflow that builds the apps."""
    data = data_dir()
    found = {}
    started = threading.Event()

    def ready(url):
        found["studio"] = url
        started.set()

    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("code", desktop(browser=False, ready=ready)), daemon=True)
    worker.start()
    deadline = time.monotonic() + 30
    page = None
    while page is None and time.monotonic() < deadline:
        try:
            with open(running_file(data), encoding="utf-8") as f:
                page = "http://127.0.0.1:%d/" % json.load(f)["control"]
        except (OSError, ValueError, KeyError):
            time.sleep(0.2)
    if page is None:
        raise SystemExit("self-test: the app's page did not start")
    with LOCAL.open(page, timeout=10) as r:
        html = r.read().decode("utf-8")
    assert "<title>Character Studio</title>" in html, "self-test: the page is not the app's"
    print("self-test: the app's page answers at %s" % page, flush=True)
    last = None
    while not started.wait(timeout=5.0):
        status = get_json(page + "launcher/status") or {}
        now = (status.get("phase"), status.get("step"), status.get("detail"))
        if now != last:
            print("self-test:", json.dumps({k: status.get(k) for k in ("phase", "step", "detail", "error")}), flush=True)
            last = now
        if status.get("phase") == "failed":
            print(status.get("log", ""), flush=True)
            raise SystemExit("self-test: setting up failed: %s" % status.get("error"))
        if time.monotonic() - deadline > timeout:
            raise SystemExit("self-test: not ready in time")
    status = get_json(found["studio"] + "api/status")
    print("self-test: the studio answers at %s: %s" % (found["studio"], json.dumps(status["finder"])), flush=True)
    assert "PyTorch" not in status["finder"]["missing"], "self-test: PyTorch is missing"
    again = already_running(data)
    assert again == found["studio"], "self-test: a second start would not find the first (%s)" % again
    request = urllib.request.Request(found["studio"] + "api/quit", data=b"", method="POST", headers={"X-Studio": "1"})
    with LOCAL.open(request, timeout=10) as r:
        assert r.status == 200
    worker.join(timeout=60)
    if worker.is_alive() or result.get("code") != 0:
        raise SystemExit("self-test: the app did not stop with the studio's Quit")
    print("self-test: passed (%s, Python %s)" % (platform.platform(), platform.python_version()), flush=True)
    return 0


def main(argv):
    if sys.version_info < (3, 10):
        raise SystemExit("Character Studio needs Python 3.10 or newer; this is %s. Install a newer one from "
                         "https://www.python.org/downloads/ and start it again." % platform.python_version())
    if "--self-test" in argv:
        return self_test()
    if "--print-python" in argv:
        print(venv_python(env_dir(data_dir())))
        return 0
    if "--desktop" in argv:
        return desktop()
    setup_only = "--setup-only" in argv
    argv = [a for a in argv if a != "--setup-only"]
    data = data_dir()
    os.makedirs(data, exist_ok=True)
    env = env_dir(data)
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
