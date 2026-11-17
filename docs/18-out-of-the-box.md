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

| Where | What | Changes when |
|---|---|---|
| `/opt/companion/core` | The core service: conversation, settings page, Wi-Fi setup | Software update |
| `/opt/companion/venv` | Its Python libraries (on-device speech recognition, Anthropic's library) | Software update |
| `/opt/companion/bin/stage` | The program that draws the character | Software update |
| `/var/lib/companion/models/stt` | The on-device speech model (shipped in the image) | Software update; kept by a reset |
| `/var/lib/companion/config/settings.json` | Choices: AI services, volume, listening mode | The owner, in the settings page |
| `/var/lib/companion/config/secrets.json` | **The owner's API keys**, readable only by the service | The owner, in the settings page |
| `/var/lib/companion/config/console-password` | The settings-page password, hashed | The owner |
| `/var/lib/companion/characters/<id>/` | Installed characters (unpacked `.char` files) | The owner |
| `/var/lib/companion/memory/<id>/` | What each character remembers (conversation, notes) | Conversations; the owner can edit or clear |
| `/var/lib/companion/current.inp` | Link to what the screen shows: the active character, or a message card | The device |
| `/etc/systemd/system/companion-*.service` | Starts the core, and the character full screen on the display | Software update |
| `/etc/default/companion` | Optional: force a particular sound card | Rarely |
| `/etc/polkit-1/rules.d/50-companion.rules` | Lets the service manage Wi-Fi and the time zone | Software update |
| `/boot/firmware/config.txt` | The two buttons, the display, no rainbow screen | Rarely |

Everything the owner adds lives in `/var/lib/companion`; everything shipped
lives elsewhere. That separation is what lets updates replace the software
without touching characters, keys or memories, and lets a reset remove the
owner's things without removing the software.

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
   - choose a voice and paste its key;
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
| A software update fails to start | Nothing (with `device/update.sh`) | It goes back to the previous version |

## Still needed before selling

1. **An original default character**, so a new unit greets the buyer with a
   character rather than text. Needs artwork the owner commissions or draws
   (no existing character may ship, D-024).
2. **Updates without a computer**: a signed update file uploaded on the
   settings page, checked against a key built into the image. Designed, not
   built; today updates use `device/update.sh` over SSH.
3. **Support access**: a way for the owner to switch on remote maintenance
   for a unit with the buyer's agreement. Off by default.
4. **Testing on real hardware**, starting with the bring-up tests in
   `15-hardware-test-plan.md`.

## What has been tested

See the end of this document, updated after the image build.
