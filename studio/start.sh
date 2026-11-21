#!/usr/bin/env bash
# Start Character Studio, the character maker, and open it in the browser (Linux and macOS).
#
# The first run sets up the studio's own Python environment in ~/.character-studio
# (several GB with PyTorch; takes a while). Later runs start at once. The part-finding
# model itself is downloaded from the studio's page. See launch.py, which does the work
# (start.bat does the same on Windows).
#
# Needs Python 3.10 or newer. Options are passed on to app.py
# (for example --port 8771 or --no-browser).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$HERE/launch.py" "$@"
