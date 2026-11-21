#!/usr/bin/env python3
"""Start Character Studio as a buyer would (launch.py), check that its page and its status answer, and
stop it. Run by the "Character Studio" workflow on Windows, macOS and Linux, after the studio is set up.

    python studio/smoke_test.py [--port 8779]

Uses only Python's own library.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read().decode("utf-8")


def stop(process):
    """Stop the launcher and the studio it started (on Windows the studio is its child)."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8779)
    args = parser.parse_args(argv)
    base = "http://127.0.0.1:%d" % args.port
    process = subprocess.Popen([sys.executable, os.path.join(HERE, "launch.py"), "--no-browser", "--port", str(args.port)])
    try:
        deadline = time.time() + 180
        while True:
            if process.poll() is not None:
                raise SystemExit("the studio stopped by itself (exit %s)" % process.returncode)
            try:
                status, page = get(base + "/")
                break
            except OSError:
                if time.time() > deadline:
                    raise SystemExit("the studio did not answer within three minutes")
                time.sleep(1)
        assert status == 200 and "<title>Character Studio</title>" in page, "the page is not the studio's"
        status, body = get(base + "/api/status")
        state = json.loads(body)
        missing = state["finder"]["missing"]
        print("status:", json.dumps(state["finder"]))
        assert "PyTorch" not in missing, "PyTorch was not installed"
        assert set(missing) <= {"model code", "model weights"}, missing
        print("Character Studio started and answered on %s" % sys.platform)
        return 0
    finally:
        stop(process)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
