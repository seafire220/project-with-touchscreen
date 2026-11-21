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
#   --writable-system    the earlier layout: one writable system partition, no
#                        separate data partition (no power-cut protection)
#
# Power-cut protection (the default, docs/33-finishing.md): the system partition
# is mounted read-only, so a power cut cannot damage it, and everything the
# device saves (characters, memories, settings, keys, saved Wi-Fi, the time zone)
# goes on a third partition, "companion-data", which grows to fill the card at
# the first start. Updates make the system writable only while they install.
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
READ_ONLY=1
DATA_SIZE=512M      # the data partition's first size; it grows to fill the card at the first start
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --stage-binary) STAGE_BINARY="$2"; shift 2 ;;
        --grow) GROW="$2"; shift 2 ;;
        --extra-ca) EXTRA_CA="$2"; shift 2 ;;
        --compress) COMPRESS=1; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        --https-sources) HTTPS_SOURCES=1; shift ;;
        --writable-system) READ_ONLY=0; shift ;;
        -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
[ ${#ARGS[@]} -eq 2 ] || { sed -n '2,36p' "$0"; exit 2; }
SOURCE="${ARGS[0]}"
OUT="${ARGS[1]}"

say() { printf '\n== %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "run this with sudo" >&2; exit 1; }
for tool in xz sfdisk losetup e2fsck resize2fs mkfs.ext4 mtype mcopy; do
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
# Only what the installer reads (not the whole folder: an image being built may sit in it).
(cd "$REPO" && tar --exclude='__pycache__' --exclude='*.pyc' -cf - core device stage/motions stage/THIRD_PARTY_LICENSES.txt THIRD_PARTY.md) | tar -xf - -C "$SRC"
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
if [ "$READ_ONLY" = 0 ]; then
    rm -f "$ROOT/etc/resolv.conf"
    if [ -e "$RESOLV_BACKUP" ] || [ -L "$RESOLV_BACKUP" ]; then cp -a "$RESOLV_BACKUP" "$ROOT/etc/resolv.conf"; fi
fi
rm -rf "$ROOT/root/.cache" "$ROOT/var/lib/apt/lists/"*

if [ "$READ_ONLY" = 1 ]; then
    say "Power-cut protection: a read-only system and a data partition"
    DATA_STAGE="$WORK/data"
    mkdir -p "$DATA_STAGE/system/nm-connections" "$DATA_STAGE/system/time" "$DATA_STAGE/system/bluetooth"
    CUID="$(chroot "$ROOT" id -u companion)"
    CGID="$(chroot "$ROOT" id -g companion)"
    # The models the device comes with stay on the read-only system (safe even if the data partition has to
    # be made again); models an update brings go on the data partition, and are preferred.
    if [ -d "$ROOT/var/lib/companion/models" ]; then
        rm -rf "$ROOT/opt/companion/models"
        mv "$ROOT/var/lib/companion/models" "$ROOT/opt/companion/models"
        chown -R root:root "$ROOT/opt/companion/models"
        chmod -R a+rX,go-w "$ROOT/opt/companion/models"
    fi
    mv "$ROOT/var/lib/companion" "$DATA_STAGE/companion"
    install -d -m 0750 -o "$CUID" -g "$CGID" "$ROOT/var/lib/companion"
    install -d -m 0700 "$ROOT/var/lib/bluetooth"
    if ls "$ROOT"/etc/NetworkManager/system-connections/* >/dev/null 2>&1; then
        mv "$ROOT"/etc/NetworkManager/system-connections/* "$DATA_STAGE/system/nm-connections/"
    fi
    zone="$(readlink "$ROOT/etc/localtime" | sed 's#.*/zoneinfo/##')"
    ln -sfn "/usr/share/zoneinfo/${zone:-Etc/UTC}" "$DATA_STAGE/system/time/localtime"
    ln -sfn /data/system/time/localtime "$ROOT/etc/localtime"
    # NetworkManager writes the name servers in /run; /etc/resolv.conf points there.
    ln -sfn /run/NetworkManager/resolv.conf "$ROOT/etc/resolv.conf"
    RESOLV_BACKUP=""
    install -d "$ROOT/data"
    sed -i -E 's#^([^ ]+ +/ +ext4 +)defaults,noatime( |$)#\1defaults,noatime,ro\2#' "$ROOT/etc/fstab"
    sed -i -E 's#^([^ ]+ +/boot/firmware +vfat +)defaults( |$)#\1defaults,ro\2#' "$ROOT/etc/fstab"
    cat >> "$ROOT/etc/fstab" <<'FSTAB'
# Power-cut protection (docs/33-finishing.md): the system is read-only; what the device saves is on the
# data partition; /var's changes are kept in memory.
LABEL=companion-data  /data  ext4  defaults,noatime,nofail,x-systemd.device-timeout=30  0  2
overlay  /var  overlay  lowerdir=/var,upperdir=/run/companion-var/upper,workdir=/run/companion-var/work,x-systemd.requires=companion-var-dirs.service  0  0
/data/companion  /var/lib/companion  none  bind,nofail,x-systemd.requires-mounts-for=/data  0  0
/data/system/nm-connections  /etc/NetworkManager/system-connections  none  bind,nofail,x-systemd.requires-mounts-for=/data  0  0
/data/system/bluetooth  /var/lib/bluetooth  none  bind,nofail,x-systemd.requires-mounts-for=/data  0  0
FSTAB
    install -m 0644 "$REPO"/device/readonly/companion-var-dirs.service "$REPO"/device/readonly/companion-data-check.service \
        "$REPO"/device/readonly/companion-firstboot.service "$ROOT/etc/systemd/system/"
    install -d "$ROOT/etc/systemd/journald.conf.d"
    install -m 0644 "$REPO/device/readonly/journald-readonly.conf" "$ROOT/etc/systemd/journald.conf.d/zz-companion-readonly.conf"
    chroot "$ROOT" systemctl enable companion-data-check.service companion-firstboot.service
    # First-start jobs that would write to the system, and timers with nothing to do on a read-only one.
    for unit in rpi-resize.service systemd-firstboot.service apt-daily.timer apt-daily-upgrade.timer man-db.timer \
            dpkg-db-backup.timer; do
        chroot "$ROOT" systemctl mask "$unit" >/dev/null 2>&1 || true
    done
    if [ -f "$ROOT/etc/default/fake-hwclock" ]; then
        sed -i 's#^\#\?FILE=.*#FILE=/data/system/fake-hwclock.data#' "$ROOT/etc/default/fake-hwclock"
    fi
fi
for m in dev/pts dev proc sys; do umount -l "$ROOT/$m"; done
umount "$ROOT"
losetup -d "$LOOP"
LOOP=""

if [ "$READ_ONLY" = 1 ]; then
    say "Adding the data partition"
    truncate -s +"$DATA_SIZE" "$OUT"
    echo "start=$(( (ROOT_START + ROOT_SIZE) / 512 )), type=83" | sfdisk --no-reread --quiet --append "$OUT"
    read -r DATA_START DATA_BYTES < <(part 3)
    LOOP="$(losetup -f --show -o "$DATA_START" --sizelimit "$DATA_BYTES" "$OUT")"
    mkfs.ext4 -q -L companion-data "$LOOP"
    mkdir -p "$WORK/datamnt"
    mount "$LOOP" "$WORK/datamnt"
    cp -a "$DATA_STAGE/." "$WORK/datamnt/"
    chown "$CUID:$CGID" "$WORK/datamnt/companion" "$WORK/datamnt/system/time"
    chmod 0750 "$WORK/datamnt/companion"
    chmod 0700 "$WORK/datamnt/system/nm-connections" "$WORK/datamnt/system/bluetooth"
    umount "$WORK/datamnt"
    losetup -d "$LOOP"
    LOOP=""
fi

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
if [ "$READ_ONLY" = 1 ]; then
    # Raspberry Pi OS's first-start "resize" grows the system partition, which the data partition now
    # follows: the data partition is grown instead (companion-firstboot). The system starts read-only.
    mtype -i "$BOOT" ::cmdline.txt | tr -d '\r\n' | sed -e 's/ resize\b//' -e 's/ ro\b//' > "$WORK/cmdline.txt"
    printf '%s ro\n' "$(cat "$WORK/cmdline.txt")" > "$WORK/cmdline.txt.new"
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
