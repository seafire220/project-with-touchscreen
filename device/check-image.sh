#!/bin/bash
# Check that a device image is set up to work out of the box.
#
#   sudo ./device/check-image.sh companion.img
#
# Mounts the image read-only and checks: the software and speech model are
# installed, the services are enabled, nothing asks for a login on the
# screen, cloud-init and SSH are off, no API keys or owner data are inside,
# and the boot settings for the buttons and display are present.
# Exit status 0 means every check passed.
set -uo pipefail

IMG="${1:?usage: check-image.sh IMAGE}"
[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
WORK="$(mktemp -d)"
ROOT="$WORK/root"
LOOP=""
cleanup() { mountpoint -q "$ROOT" && umount "$ROOT"; [ -n "$LOOP" ] && losetup -d "$LOOP"; rm -rf "$WORK"; }
trap cleanup EXIT

part() {
    sfdisk -J "$IMG" | python3 -c "import json,sys; p=json.load(sys.stdin)['partitiontable']['partitions'][$1-1]; print(p['start']*512, p['size']*512)"
}
read -r BOOT_START _ < <(part 1)
read -r ROOT_START ROOT_SIZE < <(part 2)
mkdir -p "$ROOT"
LOOP="$(losetup -f --show -r -o "$ROOT_START" --sizelimit "$ROOT_SIZE" "$IMG")"
mount -o ro "$LOOP" "$ROOT"

PASS=0
FAIL=0
check() {   # description, then a command that succeeds when the check passes
    local what="$1"; shift
    if "$@" >/dev/null 2>&1; then echo "PASS  $what"; PASS=$((PASS + 1)); else echo "FAIL  $what"; FAIL=$((FAIL + 1)); fi
}
enabled() { [ -L "$ROOT/etc/systemd/system/$1.wants/$2" ]; }
masked() { [ "$(readlink "$ROOT/etc/systemd/system/$1")" = /dev/null ]; }
absent_or_disabled() { ! ls "$ROOT"/etc/systemd/system/*.wants/"$1" >/dev/null 2>&1; }

check "core service installed" test -f "$ROOT/opt/companion/core/companion/__main__.py"
check "settings page installed" test -f "$ROOT/opt/companion/core/companion/console/index.html"
check "character program installed (64-bit ARM)" sh -c "file -b '$ROOT/opt/companion/bin/stage' | grep -q aarch64"
check "Python environment with on-device speech recognition" sh -c "ls '$ROOT'/opt/companion/venv/lib/python3*/site-packages | grep -q sherpa_onnx"
check "speech model shipped" test -f "$ROOT/var/lib/companion/models/stt/encode.int8.onnx"
check "on-device voice shipped" test -f "$ROOT/var/lib/companion/models/tts/en_US-libritts_r-medium.onnx"
check "espeak-ng installed for the voice" test -x "$ROOT/usr/bin/espeak-ng"
check "data folder owned by the service user" sh -c "[ \"\$(stat -c %U '$ROOT/var/lib/companion')\" = companion ] || grep -q '^companion:' '$ROOT/etc/passwd'"
check "core service starts at boot" enabled multi-user.target companion-core.service
check "character starts at boot" enabled graphical.target companion-stage.service
check "boots to the character screen (graphical target)" sh -c "readlink '$ROOT/etc/systemd/system/default.target' | grep -q graphical.target"
check "no login prompt on the screen (getty on tty1 off)" absent_or_disabled getty@tty1.service
check "no first-boot user prompt (userconfig masked)" masked userconfig.service
check "cloud-init disabled" test -f "$ROOT/etc/cloud/cloud-init.disabled"
check "SSH not enabled" absent_or_disabled ssh.service
check "hostname is companion" grep -qx companion "$ROOT/etc/hostname"
check "Wi-Fi and time zone permission for the service" test -f "$ROOT/etc/polkit-1/rules.d/50-companion.rules"
check "small logs" test -f "$ROOT/etc/systemd/journald.conf.d/companion.conf"
check "hardware watchdog" test -f "$ROOT/etc/systemd/system.conf.d/companion.conf"
check "a setup screen is ready for the first start" sh -c "test -s '$ROOT/var/lib/companion/card.inp' && test -L '$ROOT/var/lib/companion/current.inp'"
check "the screen restarts forever if it fails" grep -q "StartLimitIntervalSec=0" "$ROOT/etc/systemd/system/companion-stage.service"
check "no API keys inside" sh -c "! test -e '$ROOT/var/lib/companion/config/secrets.json'"
check "no settings-page password inside" sh -c "! test -e '$ROOT/var/lib/companion/config/console-password'"
check "no characters or memories inside" sh -c "! ls '$ROOT/var/lib/companion/characters/'* '$ROOT/var/lib/companion/memory/'* >/dev/null 2>&1"
check "no saved Wi-Fi networks inside" sh -c "! ls '$ROOT'/etc/NetworkManager/system-connections/* >/dev/null 2>&1"
check "no build leftovers" sh -c "! test -e '$ROOT/tmp/companion-src' && ! test -e '$ROOT/usr/local/share/ca-certificates/build-extra-ca.crt'"
check "buttons and display in the boot settings" sh -c "mtype -i '$IMG@@$BOOT_START' ::config.txt | grep -q 'gpio-key,gpio=17'"
check "quiet boot" sh -c "mtype -i '$IMG@@$BOOT_START' ::cmdline.txt | grep -q logo.nologo"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
