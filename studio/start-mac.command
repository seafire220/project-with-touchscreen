#!/usr/bin/env bash
# Double-click this in Finder to start Character Studio on a Mac. A Terminal window opens and shows
# what it is doing; closing that window stops the studio. (The first time, macOS may ask whether to
# open it: Control-click it, choose Open, then Open again.)
cd "$(dirname "$0")"
PYTHON=python3
for candidate in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
done
"$PYTHON" launch.py "$@"
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "Character Studio stopped with a problem (shown above). Press Return to close this window."
  read -r _
fi
exit $status
