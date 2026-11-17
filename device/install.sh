#!/bin/bash
# Turn a fresh Raspberry Pi OS Lite (64-bit) into the character device.
#
#   sudo ./device/install.sh [--stage-binary PATH] [--no-model]
#
# Run it from a copy of this repository on the Pi. It installs the packages
# the device needs, the core service, the stage program and the system
# settings, then asks you to reboot. Running it again updates the software
# and leaves your characters, memories, keys and settings alone.
#
# The stage program is built for the Pi on a Linux PC (see stage/README.md)
# and copied to stage/target/aarch64-unknown-linux-gnu/release/stage, or
# given with --stage-binary. If it is missing and Rust is installed on the
# Pi, it is built here (slow on a 1 GB Pi).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP=/opt/companion
DATA=/var/lib/companion
STAGE_BINARY="$REPO/stage/target/aarch64-unknown-linux-gnu/release/stage"
GET_MODEL=1
# On-device speech recognition model: Moonshine tiny, English, 8-bit (MIT
# licence, Useful Sensors), packaged for sherpa-onnx. About 120 MB.
MODEL_URL="https://huggingface.co/csukuangfj/sherpa-onnx-moonshine-tiny-en-int8/resolve/main"
MODEL_FILES="preprocess.onnx encode.int8.onnx uncached_decode.int8.onnx cached_decode.int8.onnx tokens.txt LICENSE"

while [ $# -gt 0 ]; do
    case "$1" in
        --stage-binary) STAGE_BINARY="$2"; shift 2 ;;
        --no-model) GET_MODEL=0; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

say() { printf '\n== %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
if [ "$(uname -m)" != "aarch64" ]; then
    echo "note: this is not a 64-bit ARM system; continuing for testing only" >&2
fi

say "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q --no-install-recommends \
    cage python3 python3-venv python3-numpy python3-aiohttp python3-pil \
    alsa-utils network-manager polkitd fonts-dejavu-core \
    libegl1 libgles2 libgl1-mesa-dri libwayland-client0 libwayland-egl1 libxkbcommon0 \
    ca-certificates curl

say "Creating the service user"
if ! id companion >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin companion
fi
for group in video render audio input; do
    getent group "$group" >/dev/null && usermod -aG "$group" companion
done
install -d -o companion -g companion -m 0750 "$DATA"

say "Installing the software in $APP"
install -d "$APP" "$APP/bin"
rm -rf "$APP/core.new"
cp -r "$REPO/core" "$APP/core.new"
rm -rf "$APP/core.new/tests" "$APP/core.new"/companion/__pycache__
if [ -d "$APP/core" ]; then rm -rf "$APP/core.previous"; mv "$APP/core" "$APP/core.previous"; fi
mv "$APP/core.new" "$APP/core"

if [ ! -x "$STAGE_BINARY" ]; then
    if command -v cargo >/dev/null; then
        say "Building the stage program (this takes a while)"
        (cd "$REPO/stage" && cargo build --release)
        STAGE_BINARY="$REPO/stage/target/release/stage"
    else
        echo "No stage program found at $STAGE_BINARY. Build it on a PC (see stage/README.md) and pass --stage-binary." >&2
        exit 1
    fi
fi
install -m 0755 "$STAGE_BINARY" "$APP/bin/stage.new"
mv "$APP/bin/stage.new" "$APP/bin/stage"

say "Setting up Python"
if [ ! -x "$APP/venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$APP/venv"
fi
"$APP/venv/bin/pip" install -q --upgrade pip
# sherpa-onnx: on-device speech recognition. anthropic: only loaded if Claude is chosen.
"$APP/venv/bin/pip" install -q sherpa-onnx anthropic || echo "warning: optional Python packages did not install" >&2

if [ "$GET_MODEL" = 1 ] && [ ! -d "$DATA/models/stt" ]; then
    say "Downloading the on-device speech model"
    tmp="$(mktemp -d)"
    ok=1
    for f in $MODEL_FILES; do
        curl -fsSL "$MODEL_URL/$f" -o "$tmp/$f" || { ok=0; break; }
    done
    if [ "$ok" = 1 ]; then
        install -d -o companion -g companion "$DATA/models"
        mv "$tmp" "$DATA/models/stt"
        chown -R companion:companion "$DATA/models"
    else
        echo "warning: could not download the speech model; choose a cloud speech service in the settings page" >&2
        rm -rf "$tmp"
    fi
fi

say "Installing system settings"
install -m 0644 "$REPO/device/systemd/companion-core.service" /etc/systemd/system/
install -m 0644 "$REPO/device/systemd/companion-stage.service" /etc/systemd/system/
install -m 0644 "$REPO/device/config/pam-companion-stage" /etc/pam.d/companion-stage
install -d /etc/polkit-1/rules.d /etc/systemd/journald.conf.d /etc/systemd/system.conf.d
install -m 0644 "$REPO/device/config/polkit-companion.rules" /etc/polkit-1/rules.d/50-companion.rules
install -m 0644 "$REPO/device/config/journald.conf" /etc/systemd/journald.conf.d/companion.conf
install -m 0644 "$REPO/device/config/system.conf" /etc/systemd/system.conf.d/companion.conf
[ -f /etc/default/companion ] || install -m 0644 "$REPO/device/config/default-companion" /etc/default/companion

BOOT=/boot/firmware
[ -d "$BOOT" ] || BOOT=/boot
if [ -f "$BOOT/config.txt" ] && ! grep -q "Character device" "$BOOT/config.txt"; then
    cat "$REPO/device/config/boot-config.txt" >> "$BOOT/config.txt"
fi
if [ -f "$BOOT/cmdline.txt" ] && ! grep -q "logo.nologo" "$BOOT/cmdline.txt"; then
    sed -i '1 s/$/ quiet loglevel=3 logo.nologo vt.global_cursor_default=0/' "$BOOT/cmdline.txt"
fi

say "Enabling the services"
systemctl daemon-reload || true
systemctl disable getty@tty1.service 2>/dev/null || true
systemctl enable NetworkManager.service companion-core.service companion-stage.service
systemctl set-default graphical.target

say "Done. Restart the device with: sudo reboot"
echo "After it restarts, the screen shows how to reach its settings page."
