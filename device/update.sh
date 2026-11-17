#!/bin/bash
# Update the device's software from a newer copy of this repository, or go back.
#
#   sudo ./device/update.sh            install the software from this copy
#   sudo ./device/update.sh --rollback go back to the version before the last update
#
# Characters, memories, keys and settings in /var/lib/companion are never touched.
set -euo pipefail
APP=/opt/companion
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }

if [ "${1:-}" = "--rollback" ]; then
    [ -d "$APP/core.previous" ] || { echo "there is no earlier version to go back to" >&2; exit 1; }
    mv "$APP/core" "$APP/core.failed"
    mv "$APP/core.previous" "$APP/core"
    rm -rf "$APP/core.failed"
    [ -f "$APP/bin/stage.previous" ] && mv "$APP/bin/stage.previous" "$APP/bin/stage"
    systemctl restart companion-core companion-stage
    echo "Back on the previous version."
    exit 0
fi

[ -f "$APP/bin/stage" ] && cp "$APP/bin/stage" "$APP/bin/stage.previous"
"$REPO/device/install.sh" --no-model "$@"
systemctl restart companion-core companion-stage
sleep 5
if systemctl is-active --quiet companion-core; then
    echo "Updated. If something is wrong, run: sudo $0 --rollback"
else
    echo "The new version did not start; going back." >&2
    "$0" --rollback
    exit 1
fi
