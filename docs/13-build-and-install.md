# Building and installing the device

Status: written 2026-11-17 from the design and from tests in a Debian 13
environment and under ARM emulation. **Not yet followed on real hardware.**
Steps that depend on the hardware are marked *check on first build*;
correct this guide as you go.

## 1. Parts

The prototype parts are in the hardware document (`05-hardware-and-bom.md`,
configuration B, about A$239): Raspberry Pi 4 Model B 1 GB, Raspberry Pi
Touch Display 2 (5"), Seeed ReSpeaker Lite with a 4 Ω 5 W speaker, a 32 GB
microSD card, the official 5 V 3 A USB-C supply, two push buttons and four
female jumper leads.

## 2. Wiring

| Part | Connects to |
|---|---|
| Touch Display 2 ribbon | the Pi's DSI display connector |
| Touch Display 2 power lead | Pi header 5 V (pin 2 or 4) and ground (pin 6) |
| ReSpeaker Lite (USB-C) | a USB 2.0 port on the Pi |
| Speaker | the ReSpeaker Lite's speaker connector |
| Listen button | GPIO17 (pin 11) and ground (pin 9) |
| Power button | GPIO3 (pin 5) and ground (pin 14) |

The buttons need no resistors: the Pi's own pull-ups are switched on in the
boot settings. Pressing the power button shuts the Pi down cleanly; pressing
it again starts it.

## 3. Prepare the microSD card

1. Install Raspberry Pi Imager on your computer.
2. Choose **Raspberry Pi OS Lite (64-bit)**. Not the desktop version.
3. In Imager's settings, set a user name and password, and turn on SSH.
   Setting Wi-Fi here is optional: without it, the device opens its own
   setup hotspot on first start.
4. Write the card, put it in the Pi, connect a keyboard or use SSH, and
   start the Pi.

## 4. Build the character program for the Pi (on a Linux PC)

The stage program is written in Rust. Building it on a 1 GB Pi is slow and
can run out of memory, so build it on a PC:

```bash
sudo apt install gcc-aarch64-linux-gnu
```

```bash
rustup target add aarch64-unknown-linux-gnu
```

```bash
cd stage && cargo build --release --target aarch64-unknown-linux-gnu
```

The result is `stage/target/aarch64-unknown-linux-gnu/release/stage`
(about 4 MB). Copy the whole repository, including that file, to the Pi.
For example, from the repository's parent folder:

```bash
scp -r repo pi-user@raspberrypi.local:
```

A Mac can build it the same way after installing a cross-linker; or build on
the Pi itself if it has Rust (the installer does this when no binary is
found).

## 5. Install

On the Pi:

```bash
cd ~/repo && sudo ./device/install.sh
```

It installs the system packages, creates the `companion` service user,
installs the software in `/opt/companion`, downloads the on-device speech
recognition model, installs the services and adds the button and display
lines to `/boot/firmware/config.txt`. It takes 10–20 minutes, mostly
downloads. Then:

```bash
sudo reboot
```

*Check on first build:*

- **Display.** The installer adds `dtoverlay=vc4-kms-dsi-ili9881-5inch` for
  the 5" Touch Display 2. Check this against the Raspberry Pi documentation
  for your display; the 7" version uses `...-7inch`, and an HDMI screen needs
  neither line. Remove or change the line in `/boot/firmware/config.txt`.
- **Sound device names.** `/etc/default/companion` names the ReSpeaker Lite
  as `plughw:CARD=Lite`. Run `aplay -l` and `arecord -l` and put the card's
  real name there, then run `sudo systemctl restart companion-core`.

## 6. First start

1. The screen shows **Set up Wi-Fi** with a network name such as
   `Companion-1A2B` and a password. Join that network with your phone and
   open `http://10.42.0.1`. (If the Pi already has Wi-Fi, the screen shows
   its address instead.)
2. Set a password for the settings page.
3. Under **Device → Wi-Fi**, choose your home network. The device joins it
   and shows its new address on screen. Reconnect your phone to your home
   Wi-Fi and open that address.
4. Under **AI services**, choose a language model and a voice, paste your
   keys and press **Test** on each. Speech recognition defaults to the free
   on-device model.
5. Under **Characters**, add a `.char` file (see
   `14-making-characters.md`). The character appears on the screen.
6. Press the listen button and speak. Press it again to stop listening;
   press it while the character speaks to interrupt.

## 7. Updating

Copy a newer version of the repository to the Pi (with a newly built stage
program), then:

```bash
cd ~/repo && sudo ./device/update.sh
```

If the new version does not start, it goes back to the old one by itself.
To go back by hand:

```bash
sudo ./device/update.sh --rollback
```

Characters, memories, keys and settings live in `/var/lib/companion` and are
never touched by an update.

## Where things are

| What | Where |
|---|---|
| The software | `/opt/companion` |
| Characters, memories, settings, keys | `/var/lib/companion` (keys in `config/secrets.json`, readable only by the service) |
| Service settings (sound devices) | `/etc/default/companion` |
| Logs | `journalctl -u companion-core -u companion-stage` |
| Boot settings | `/boot/firmware/config.txt` (lines between the "Character device" markers) |
