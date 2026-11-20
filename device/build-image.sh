#!/bin/bash
# Build a ready-to-flash SD card image of the character device.
#
#   sudo ./device/build-image.sh RASPIOS_LITE_ARM64.img.xz OUT.img [options]
#
# Starts from the official Raspberry Pi OS Lite (64-bit) image, installs
# everything inside it (packages, the core, the stage, the speech model,
# services and boot settings) and writes OUT.img. Flash OUT.img to every
# unit's card: on first power-on the unit shows its setup screen with no
# other step. Each unit makes its own hotspot password and the buyer sets the
# settings-page password, so nothing secret is shared between units.
#
# Options:
#   --stage-binary PATH  the stage built for the Pi (default: the cross-build
#                        in stage/target/aarch64-unknown-linux-gnu/release/stage)
#   --grow SIZE          extra space for the software (default 2G)
#   --extra-ca FILE      trust an extra certificate authority while building
#                        (for a company proxy); removed from the image afterwards
#   --https-sources      fetch packages over https while building (for proxies
#                        that refuse plain http); the image keeps its usual sources
#   --compress           also write OUT.img.xz and its SHA-256 sum
#   --version V          the software's version (as in its releases; default:
#                        core/companion/VERSION). Sold devices compare it with
#                        updates (docs/32-updates.md)
#
# Runs on a Linux PC (x86 or ARM) as root. Needs: xz, sfdisk, losetup,
# e2fsck, resize2fs, mtools, and ARM64 emulation (qemu-user-static with
# binfmt registered; on Debian or Ubuntu: apt install qemu-user-static).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE_BINARY="$REPO/stage/target/aarch64-unknown-linux-gnu/release/stage"
GROW=2G
EXTRA_CA=""
COMPRESS=0
VERSION=""
HTTPS_SOURCES=0
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --stage-binary) STAGE_BINARY="$2"; shift 2 ;;
        --grow) GROW="$2"; shift 2 ;;
        --extra-ca) EXTRA_CA="$2"; shift 2 ;;
        --compress) COMPRESS=1; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        --https-sources) HTTPS_SOURCES=1; shift ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
[ ${#ARGS[@]} -eq 2 ] || { sed -n '2,28p' "$0"; exit 2; }
SOURCE="${ARGS[0]}"
OUT="${ARGS[1]}"

say() { printf '\n== %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
for tool in xz sfdisk losetup e2fsck resize2fs mtype mcopy; do
    command -v "$tool" >/dev/null || { echo "missing tool: $tool" >&2; exit 1; }
done
[ -x "$STAGE_BINARY" ] || { echo "no stage program at $STAGE_BINARY (see stage/README.md)" >&2; exit 1; }
if [ "$(uname -m)" != "aarch64" ] && [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
    echo "ARM64 emulation is not registered (install qemu-user-static)" >&2
    exit 1
fi

WORK="$(mktemp -d)"
ROOT="$WORK/root"
LOOP=""
cleanup() {
    set +e
    # Stop anything still running inside the image (after an interruption).
    for p in /proc/[0-9]*; do
        [ "$(readlink "$p/root" 2>/dev/null)" = "$ROOT" ] && kill -9 "${p#/proc/}" 2>/dev/null
    done
    for m in dev/pts dev proc sys; do mountpoint -q "$ROOT/$m" && umount -l "$ROOT/$m"; done
    mountpoint -q "$ROOT" && umount "$ROOT"
    [ -n "$LOOP" ] && losetup -d "$LOOP"
    rm -rf "$WORK"
}
trap cleanup EXIT

say "Unpacking $SOURCE"
case "$SOURCE" in
    *.xz) xz -dc "$SOURCE" > "$OUT" ;;
    *) cp "$SOURCE" "$OUT" ;;
esac
truncate -s +"$GROW" "$OUT"
echo ", +" | sfdisk --no-reread --quiet -N 2 "$OUT"

part() {   # start and size in bytes of partition $1
    sfdisk -J "$OUT" | python3 -c "import json,sys; p=json.load(sys.stdin)['partitiontable']['partitions'][$1-1]; print(p['start']*512, p['size']*512)"
}
read -r BOOT_START BOOT_SIZE < <(part 1)
read -r ROOT_START ROOT_SIZE < <(part 2)

say "Growing the system partition"
LOOP="$(losetup -f --show -o "$ROOT_START" --sizelimit "$ROOT_SIZE" "$OUT")"
e2fsck -fy "$LOOP" >/dev/null || true
resize2fs "$LOOP" >/dev/null
mkdir -p "$ROOT"
mount "$LOOP" "$ROOT"
mount -t proc proc "$ROOT/proc"
mount -t sysfs sys "$ROOT/sys"
mount --bind /dev "$ROOT/dev"
mount --bind /dev/pts "$ROOT/dev/pts"
RESOLV_BACKUP="$WORK/resolv.conf"
cp -a "$ROOT/etc/resolv.conf" "$RESOLV_BACKUP" 2>/dev/null || true
rm -f "$ROOT/etc/resolv.conf"
cp /etc/resolv.conf "$ROOT/etc/resolv.conf"

say "Copying the software into the image"
SRC="$ROOT/tmp/companion-src"
mkdir -p "$SRC"
(cd "$REPO" && tar --exclude=./stage/target --exclude=.git --exclude='__pycache__' -cf - .) | tar -xf - -C "$SRC"
install -m 0755 "$STAGE_BINARY" "$SRC/stage-binary"
if [ -n "$EXTRA_CA" ]; then
    install -m 0644 "$EXTRA_CA" "$ROOT/usr/local/share/ca-certificates/build-extra-ca.crt"
    chroot "$ROOT" update-ca-certificates >/dev/null
fi

if [ "$HTTPS_SOURCES" = 1 ]; then
    mkdir -p "$WORK/apt-sources"
    cp -a "$ROOT/etc/apt/sources.list.d" "$WORK/apt-sources/"
    [ -f "$ROOT/etc/apt/sources.list" ] && cp -a "$ROOT/etc/apt/sources.list" "$WORK/apt-sources/"
    find "$ROOT/etc/apt" -maxdepth 2 \( -name '*.list' -o -name '*.sources' \) -exec sed -i 's#http://#https://#g' {} +
fi

say "Installing inside the image (under emulation; this takes a while)"
chroot "$ROOT" env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8 \
    http_proxy="${http_proxy:-}" https_proxy="${https_proxy:-}" \
    HTTP_PROXY="${HTTP_PROXY:-}" HTTPS_PROXY="${HTTPS_PROXY:-}" \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    /tmp/companion-src/device/install.sh --image --stage-binary /tmp/companion-src/stage-binary ${VERSION:+--version "$VERSION"}

say "Tidying up"
rm -rf "$SRC"
if [ "$HTTPS_SOURCES" = 1 ]; then
    rm -rf "$ROOT/etc/apt/sources.list.d"
    cp -a "$WORK/apt-sources/sources.list.d" "$ROOT/etc/apt/"
    [ -f "$WORK/apt-sources/sources.list" ] && cp -a "$WORK/apt-sources/sources.list" "$ROOT/etc/apt/"
fi
if [ -n "$EXTRA_CA" ]; then
    rm -f "$ROOT/usr/local/share/ca-certificates/build-extra-ca.crt"
    chroot "$ROOT" update-ca-certificates --fresh >/dev/null
fi
rm -f "$ROOT/etc/resolv.conf"
if [ -e "$RESOLV_BACKUP" ] || [ -L "$RESOLV_BACKUP" ]; then cp -a "$RESOLV_BACKUP" "$ROOT/etc/resolv.conf"; fi
rm -rf "$ROOT/root/.cache" "$ROOT/var/lib/apt/lists/"*
for m in dev/pts dev proc sys; do umount -l "$ROOT/$m"; done
umount "$ROOT"
losetup -d "$LOOP"
LOOP=""

say "Boot settings"
BOOT="$OUT@@$BOOT_START"
mtype -i "$BOOT" ::config.txt > "$WORK/config.txt"
if ! grep -q "Character device" "$WORK/config.txt"; then
    printf '\n' >> "$WORK/config.txt"
    cat "$REPO/device/config/boot-config.txt" >> "$WORK/config.txt"
    mcopy -o -i "$BOOT" "$WORK/config.txt" ::config.txt
fi
mtype -i "$BOOT" ::cmdline.txt | tr -d '\r\n' > "$WORK/cmdline.txt"
if ! grep -q "logo.nologo" "$WORK/cmdline.txt"; then
    printf '%s quiet loglevel=3 logo.nologo vt.global_cursor_default=0\n' "$(cat "$WORK/cmdline.txt")" > "$WORK/cmdline.txt.new"
    mcopy -o -i "$BOOT" "$WORK/cmdline.txt.new" ::cmdline.txt
fi

if [ "$COMPRESS" = 1 ]; then
    say "Compressing"
    xz -T0 -k -f "$OUT"
    sha256sum "$OUT.xz" > "$OUT.xz.sha256"
fi
say "Done: $OUT"
echo "Flash it with Raspberry Pi Imager (\"Use custom\") or any image writer. Do not use Imager's"
echo "customisation settings: the device sets itself up through its own setup screen."
