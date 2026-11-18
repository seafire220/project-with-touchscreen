#!/usr/bin/env bash
# Start Character Studio, the character maker, and open it in the browser.
#
# The first run sets up the studio's own Python environment in ~/.character-studio
# (several GB with PyTorch; takes a while). Later runs start at once. The part-finding
# model itself is downloaded from the studio's page.
#
# Needs Python 3.10 or newer, and git. Options are passed on to app.py
# (for example --port 8771 or --no-browser).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${CHARACTER_STUDIO_HOME:-$HOME/.character-studio}"
VENV="$DATA/venv"
PYTHON="${PYTHON:-python3}"
SETUP_VERSION=1

mkdir -p "$DATA"
if [ ! -f "$VENV/.setup-$SETUP_VERSION" ]; then
  echo "Setting up Character Studio (first run: downloads PyTorch and the rigger; this takes a while)..."
  [ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  # PyTorch: on Linux without an NVIDIA card the processor-only build is far smaller.
  if [ "$(uname -s)" = "Linux" ] && ! command -v nvidia-smi >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu
  else
    "$VENV/bin/python" -m pip install -q torch torchvision
  fi
  "$VENV/bin/python" -m pip install -q -r "$HERE/requirements.txt" -r "$HERE/requirements-app.txt" \
    -r "$HERE/requirements-model.txt"
  touch "$VENV/.setup-$SETUP_VERSION"
fi
exec "$VENV/bin/python" "$HERE/app.py" --data "$DATA" "$@"
