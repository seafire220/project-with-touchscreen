# How the device works out of the box

Status: 2026-11-17. Designed and built; tested in software (see "What has
been tested"). Not yet tried on a real Raspberry Pi.

The owner asked whether the files are planned so that a unit works out of
the box once set up, and confirmed that buyers bring their own AI keys. This
document is the answer: what is on the card, what happens from the first
power-on, how units are made, and how they are reset and recovered.

## Making units: one image, flashed to every card

1. On a Linux PC, build the device image once per software version:

   ```
   sudo ./device/build-image.sh 2026-10-06-raspios-trixie-arm64-lite.img.xz companion.img --compress
   ```

   It starts from the official Raspberry Pi OS Lite (64-bit) image and
   installs everything inside it: system packages, the core service, the
   character program, the on-device speech model, the services, the button
   and display settings. It also switches off what a keyboard-less product
   must not have: Raspberry Pi OS's first-boot "choose a user name" prompt,
   cloud-init (which can create a login with a default password), and SSH.
2. Flash `companion.img` to each unit's microSD card with any image writer
   (Raspberry Pi Imager: "Use custom", no customisation settings).
3. Optionally power each unit once for a quick check (the first tests in
   `15-hardware-test-plan.md`).

Nothing secret is shared between units: each unit makes its own setup
hotspot name (from the Pi's serial number) and a new random hotspot
password at each start, and each buyer sets their own settings-page
password. Raspberry Pi OS makes new SSH host keys on each unit's first
boot, though SSH is off anyway.

For development, `device/install.sh` does the same on a Pi that is already
running Raspberry Pi OS (`13-build-and-install.md`).

## What is on the card

The card has three partitions (images built with power-cut protection, the default since 2026-11-20;
`33-finishing.md`):

| Partition | Mounted | Holds |
|---|---|---|
| 1, `bootfs` (512 MB, FAT) | `/boot/firmware`, read-only | The Pi's firmware, kernel and boot settings |
| 2, `rootfs` (about 4.3 GB) | `/`, **read-only** | Raspberry Pi OS, the device's software and its versions, the models it came with (`/opt/companion/models`) |
| 3, `companion-data` (512 MB in the image; fills the card from the first start) | `/data` | `/data/companion` (mounted at `/var/lib/companion`), saved Wi-Fi (at `/etc/NetworkManager/system-connections`), the time zone |

`/var`'s other changes and the logs are kept in memory. Updates make partition 2 writable only while
they install.

| Where | What | Changes when |
|---|---|---|
| `/opt/companion/releases/<version>/` | One folder per software version; `current` and `previous` point at two of them, and `core`, `bin` and `share` point into `current` (`32-updates.md`) | Software update |
| `/opt/companion/core` | The core service: conversation, settings page, Wi-Fi setup, updates | Software update |
| `/opt/companion/venv` | Its Python libraries (on-device speech recognition, Anthropic's library) | Software update |
| `/opt/companion/bin/stage` | The program that draws the character | Software update |
| `/opt/companion/updater/` | The installer for updates, run as root when the service asks | Software update |
| `/opt/companion/share/update-key.pem`, `update.json` | The public half of the owner's update key, and where updates come from | Software update |
| `/var/lib/companion/updates/` | An update waiting to be installed, and what the installer last did | The device; kept by a reset |
| `/opt/companion/models/` | The models the device comes with: speech recognition, the voice, matching by meaning, the wake word (in `/var/lib/companion/models` on a device installed by hand) | Rarely |
| `/var/lib/companion/models/` | Models an update brings, used in place of those above | Software update; kept by a reset |
| `/var/lib/companion/config/settings.json` | Choices: AI services, volume, listening mode | The owner, in the settings page |
| `/var/lib/companion/config/secrets.json` | **The owner's API keys**, readable only by the service | The owner, in the settings page |
| `/var/lib/companion/config/console-password` | The settings-page password, hashed | The owner |
| `/var/lib/companion/characters/<id>/` | Installed characters (unpacked `.char` files) | The owner |
| `/var/lib/companion/current-map.json` | The movement settings of the character on the screen, for the stage | Rewritten when the character changes |
| `/var/lib/companion/current-stage.json` | A 3D avatar's animation style, animation folders, drawing cost and shot, for the stage | Rewritten when the character or its settings change |
| `/opt/companion/share/vrma/` | The built-in full-body animations for 3D avatars | Software update |
| `/var/lib/companion/memory/<id>/` | What each character remembers: conversations and their words, lasting memories, its diary, the owner's notes (`31-memory.md`) | Conversations; the owner can edit or clear |
| `/var/lib/companion/current.inp` | Link to what the screen shows: the active character, or a message card | The device |
| `/etc/systemd/system/companion-*.service` | Starts the core, and the character full screen on the display | Software update |
| `/etc/default/companion` | Optional: force a particular sound card | Rarely |
| `/etc/polkit-1/rules.d/50-companion.rules` | Lets the service manage Wi-Fi and the time zone | Software update |
| `/boot/firmware/config.txt` | The two buttons, the display, no rainbow screen | Rarely |

Everything the owner adds lives in `/var/lib/companion`; everything shipped
lives elsewhere. That separation is what lets updates replace the software
without touching characters, keys or memories, and lets a reset remove the
owner's things without removing the software.

## How much storage it needs

No separate storage module: the microSD card is the device's storage. On the Radxa Zero 3W, it is the board's own 16 GB.

| What | Size |
|---|---|
| Raspberry Pi OS Lite and the packages the device adds | about 3 GB (the system partition is 4.3 GB, with 2 GB left free for software versions; the image is 5.7 GB) |
| The device's software: core, settings page, stage program (5 MB), animations | under 15 MB a version; two versions are kept for going back, plus one update waiting (30 to 50 MB) |
| Models: speech recognition 120 MB, voice 80 MB, matching by meaning 30 MB | 230 MB |
| The wake-word model | 5 MB |
| The data partition's own space | 512 MB at first; then the rest of the card |
| Logs | in memory, at most 20 MB (on the card, at most 40 MB, on images without power-cut protection) |
| **A 2D character** (picture-made, Live2D or Inochi2D) | 5 to 50 MB each |
| **A 3D avatar** (VRM, after import shrinks its textures) | 10 to 160 MB each, typically 20 to 60 |
| **Memory**: conversations, every word, memories, diary | about 5 MB per character per year of daily talk |
| While making a backup | a temporary copy of the characters and memories |

So the software takes about 3.5 GB:
- **A 16 GB card** leaves about 12 GB, room for well over a hundred 3D avatars, or decades of memory.
- **The 32 GB A1 card** in the parts list (`05-hardware-and-bom.md`) leaves plenty of headroom, and a name-brand A1 or A2 card matters more than its size.
- A buyer who wants a bigger card can move everything with **Backup** and **Restore**.

## The first power-on, as the buyer sees it

1. **Power on.** The screen goes straight to the setup screen: no rainbow,
   no text console, no login. (Boot time is still to be measured.)
2. **Set up Wi-Fi.** With no known network, after about 40 seconds the
   screen shows "Set up Wi-Fi", the device's own network name and password,
   and a QR code. Scanning it joins the phone to the device's network. The
   phone opens `http://10.42.0.1`, the buyer chooses a settings-page password,
   then picks their home Wi-Fi in **Device → Wi-Fi**.
3. **Open the settings page at home.** The device joins the home network
   and shows "Hello!" with its address and a QR code for the settings page.
   It can also be reached as `http://companion.local` on most phones and
   computers.
4. **Getting started.** The settings page's home tab lists what is left:
   - choose a language model and paste its key;
   - keep the free on-device voice, or choose a voice service and paste its key;
   - add a character;
   - press the button and say hello.

   Each step links to where it is done. The page also gives the device the
   phone's time zone, so alarms ring at the right time.
5. **Talk.** Press the listen button and speak.

## API keys (the buyer's own)

- Units ship with **no keys**. The buyer pastes their own on the settings
  page under **AI services → Keys**, one per service, and presses **Test**.
- A key can be replaced or removed there but is never shown again, by the
  page or by anything else. It is stored only on the device, in a file only
  the service can read, and never goes into character packages, exports,
  logs or the screen.
- Typing a long key on the device's small touch screen would be painful, so
  the screen shows a QR code instead and the buyer pastes keys on their
  phone or computer.

## Recovery, reset and resale

| Situation | What to do | What happens |
|---|---|---|
| Forgot the settings-page password, or moved house | Hold the listen button for 12 seconds | The password and saved Wi-Fi are forgotten; characters, memories and keys stay. The setup screens come back |
| Selling or giving the device away | Settings page → Device → Reset everything (password, then type RESET) | Characters, memories, keys, settings, timers and saved Wi-Fi are removed; the software and speech model stay. Like new |
| A character cannot be shown | Nothing | After about 25 seconds the screen explains and asks for another character |
| The service or character program crashes | Nothing | Restarted within seconds |
| The whole system hangs | Nothing | The hardware watchdog restarts the Pi |
| A software update fails to start | Nothing | The installer goes back to the previous version and the settings page says so (`32-updates.md`) |
| The owner wants the previous version back | Settings page → Device → Software → Go back to the previous version | The version before runs again |

## Still needed before selling

1. **An original default character**, so a new unit greets the buyer with a
   character rather than text. Needs artwork the owner commissions or draws
   (no existing character may ship, D-024).
2. ~~**Updates without a computer**~~: built (2026-11-20, `32-updates.md`). Devices look for
   signed updates twice a day and install them at night, going back by themselves if one does not
   start; the owner can also choose an update file. Before building sale images, make the update
   key (`device/release.py keygen`) and set the update address.
3. **Support access**: a way for the owner to switch on remote maintenance
   for a unit with the buyer's agreement. Off by default.
4. **Testing on real hardware**, starting with the bring-up tests in
   `15-hardware-test-plan.md`.

## What has been tested

On 2026-11-17, in this development environment (not on a Pi):

- **The image was built from the official Raspberry Pi OS Lite image**
  (`2026-10-06-raspios-trixie-arm64-lite`, checksum verified) with
  `device/build-image.sh`, running the installer inside it under ARM64
  emulation. Result: a 5.2 GB image; every package, the Python libraries
  (including on-device speech recognition for 64-bit ARM) and the speech
  model installed without error.
- **`device/check-image.sh` passed all 26 checks** on it: software, speech
  model, services enabled, boots to the character screen, no login or
  first-boot user prompt, cloud-init and SSH off, hostname, permissions,
  log limits, watchdog, a setup screen ready for the first start, the screen
  restarting forever, no keys, password, characters, memories, saved Wi-Fi
  or build leftovers inside, and the button and display boot settings.
- **The installed programs were run inside a copy of the image**, as
  64-bit ARM code under emulation:
  - the core service started as its restricted user, answered the settings
    page (HTTP 200, "set a password" on first visit) and put the setup
    screen in place;
  - the character program drew a generated character and the setup screen
    correctly with the image's own graphics libraries (OpenGL ES 3.2,
    software rendering);
  - on-device speech recognition, emulating the Pi 4's processor
    (Cortex-A72), recognised its test recording word for word. Emulating a
    newer processor with extra instructions gave an empty result, an
    emulation artefact to re-check on real hardware if a newer board is
    used.

Two faults were found by building the image and fixed before this build:
the service's start-up never wired in the Wi-Fi setup (the hotspot would
not have opened), and on the first start the screen could stay blank if
the character program started before the service had written the setup
screen.

Not tested: booting the image on a Raspberry Pi; the real display,
buttons, sound card and Wi-Fi hotspot.
