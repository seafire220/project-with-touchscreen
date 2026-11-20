# Software updates for sold devices

Status: 2026-11-20. Built and tested in software (`core/tests/test_updates.py`): signing, checking,
downloading, the settings page, and the installer itself switching versions and going back. Not yet
tried on a real Pi.

A device you have sold keeps getting your fixes. It looks for updates twice a day and installs them at
night. Updates must be **signed with your key**: a device installs nothing else. If a new version does
not start properly, the device goes back to the one before **by itself**. Characters, memories, keys,
settings and Wi-Fi are never touched.

## How it works

```
Your computer                         Your update address (any HTTPS host)          Each device
device/release.py build  ──upload──▶  latest.json                    ◀──twice a day── checks
  signs with your private key         companion-2026.12.1.update     ──download──▶    checks the signature
                                                                                      installs at night
```

**The update file** is `companion-<version>.update`. It holds three things:
- the new software (`payload.tar.gz`): the core service, the settings page, the stage program, built-in animations, system files, the updater, and optionally Python packages and models;
- a manifest naming its version and the payload's SHA-256;
- your Ed25519 signature of the manifest.

A valid signature therefore vouches for every byte.

**On the device**, two parts do the work, kept apart on purpose:

| Part | Runs as | Does |
|---|---|---|
| The device's service (`core/companion/updates.py`) | Its own unprivileged user, as now | Looks for updates; downloads and checks them; shows them on the settings page; asks for one to be installed by writing a request file. It cannot change the software |
| The installer (`device/updater/companion-update.py`) | Root, started by systemd when a request appears (`companion-update.path`) | Checks the signature again itself, trusting nothing it was told; puts the new version beside the running one; switches to it; restarts; waits for it to answer; goes back if it does not |

Each version lives in its own folder, `/opt/companion/releases/<version>`:
- `current` points at the running version and `previous` at the one before;
- `core`, `bin` and `share` point into `current`.

Installing switches `current` in one step. Going back switches it again. A version carries its own system files (services, permissions), and those are installed with it, so going back restores them too.

**"Starts properly"** means both of these:
- within two and a half minutes, the service answers `/api/health` with the new version;
- the screen program then stays up, without restarting more than once in 20 seconds.

Otherwise the installer switches back. The settings page then says what happened, for example: "Version 2026.12.1 did not start properly, so the device went back to 2026.11.20."

**If the power goes off during an update**, the next start finishes the job (`companion-update-boot.service`):
- If the switch had happened, the new version gets its health check, and is undone if it fails.
- If it hadn't, the old version simply carries on, and the page says the update was cut short.

The updater itself uses only Python's own library and the `openssl` program, so an update that breaks the device's Python packages can't break the updater.

## What the buyer sees

On the settings page, **Device → Software**:
- the version installed, and whether it is up to date;
- **Check for updates**, and **Install the update** with its notes;
- **Go back to the previous version**;
- two switches, both on by default:
  - *Look for updates automatically* (twice a day, at a random minute, so devices don't all ask at once);
  - *Install them at night* (between 2 and 5 am, and only if nobody has talked to the character for half an hour).
- **Without internet**, the buyer can choose an update file you send them. It is checked exactly like a downloaded one.

While installing, the screen says "Updating". The character comes back in a minute or two.

## Setting up, once

1. **Make your key pair**, on your own computer:

   ```bash
   python3 device/release.py keygen
   ```

   This writes `~/companion-signing/update-key-private.pem` and copies the public half to `device/config/update-key.pem`.
   - **Commit the public key.** Every image and update carries it.
   - **Never commit the private key**, never put it on a device, and keep a backup somewhere safe (a password manager, or an encrypted USB stick).
   - Whoever has the private key can update every device you have sold. Lose it, and you can never update them again.
2. **Choose an update address** and put it in `device/config/update.json`, for example:

   ```json
   {"url": "https://github.com/YOU/companion-updates/releases/latest/download/latest.json"}
   ```

   Any HTTPS host that serves files works:
   - A **public** GitHub repository just for updates, with each update as a release, is free. Its `releases/latest/download/` address always serves the newest release's files.
   - Don't use this code's own repository if it is private: devices can't log in to it.
   - Cloudflare R2 or Pages, S3, or your own website also work.
3. **Build the device images after this.** `device/check-image.sh` now fails an image that has no update key. A device made without the key, or before this change, can only be updated by re-flashing its card.

## Releasing an update

1. Build the stage program for the Pi (`stage/README.md`).
2. Make the update, with a version newer than the last (dates work well; a second update on the same day is `2026.12.1.2`):

   ```bash
   python3 device/release.py build --version 2026.12.1 \
       --stage-binary stage/target/aarch64-unknown-linux-gnu/release/stage \
       --key ~/companion-signing/update-key-private.pem --notes "Kinder greetings; fixes the alarm sound."
   ```

   This writes `dist/companion-2026.12.1.update` and `dist/latest.json`. It refuses to sign with a key that doesn't match `device/config/update-key.pem`, because devices would refuse that update.
3. Try it on your own device first: **Device → Software → choose an update file**.
4. Publish both files: as a new GitHub release, or uploaded to your host with `latest.json` last. Devices pick it up within half a day, and install it the next night.

**Python packages and models.** If a version needs a new Python package, add `--requirements FILE --wheels DIR`. The wheels must be built for 64-bit ARM, and they install from the update itself, never from the internet. To ship a new model, use `--models DIR`.

**System packages.** A new operating-system package (`apt`) can't come in an update. Ship it in the next image, and keep updates working without it.

## Safety

- A device installs only updates signed by your key, for this product (`"product": "companion"`), whose contents match the signed hash, and **newer** than what it runs. That stops anyone replaying an old, signed version with a known bug.
- The key is checked twice: by the service that downloads, and again by the root installer. The installer never trusts the service's word.
- The update file's contents are unpacked only inside the new version's folder. Paths that would escape, and links of any kind, are refused.
- Only a fixed list of system files can be installed: the device's own services, the update units, its permission rule and the updater.
- The update address can be plain or hijacked; it doesn't matter. Only your signature does.
- Updates are fetched by the device, so nothing reaches into it from outside. It still answers only on its home network.

## Developers

`sudo ./device/update.sh` installs the software from a copy of this repository over SSH, as a new version
(`0.<date and time>`, older than any release, so releases still apply). `--rollback` goes back.
`device/install.sh --version V` and `build-image.sh --version V` name the version an image starts with.

## Not done yet

- **A real Pi**: the installer has run as a real process against a stand-in system (`test_updates.py`), not on a device.
- **Updates in stages**: every device takes an update the night after it is published. Releasing to a few devices first would need a list of which ones, or a percentage in `latest.json`.
- **Telling you an update failed**: a device that went back says so on its own settings page, but nothing reports it to you.
