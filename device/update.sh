#!/bin/bash
# For development: update a device's software from a copy of this repository over SSH, or go back.
# (Sold devices update themselves from signed updates: docs/32-updates.md.)
#
#   sudo ./device/update.sh            install the software from this copy, as a new version
#   sudo ./device/update.sh --rollback go back to the version before
#
# Characters, memories, keys and settings in /var/lib/companion are never touched.
set -euo pipefail
APP=/opt/companion
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }

swap_back() {
    local previous current
    previous="$(readlink "$APP/previous" 2>/dev/null || true)"
    current="$(readlink "$APP/current" 2>/dev/null || true)"
    [ -n "$previous" ] && [ -d "$APP/$previous" ] || { echo "there is no earlier version to go back to" >&2; exit 1; }
    ln -sfn "$previous" "$APP/current.new" && mv -T "$APP/current.new" "$APP/current"
    ln -sfn "$current" "$APP/previous"
    systemctl restart companion-core companion-stage
}

if [ "${1:-}" = "--rollback" ]; then
    swap_back
    echo "Back on the previous version."
    exit 0
fi

# A development build gets its own version, older than any signed release, so releases still apply.
"$REPO/device/install.sh" --no-model --version "0.$(date +%Y%m%d%H%M%S)" "$@"
systemctl restart companion-core companion-stage
sleep 8
if systemctl is-active --quiet companion-core && curl -fsS http://127.0.0.1/api/health >/dev/null; then
    echo "Updated. If something is wrong, run: sudo $0 --rollback"
else
    echo "The new version did not start; going back." >&2
    swap_back
    exit 1
fi
