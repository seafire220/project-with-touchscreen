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

**On a read-only system** (images built with power-cut protection, `33-finishing.md`), the installer
makes the system partition writable when it starts, and read-only again when it is done. A power cut in
between is handled as above. The device's data, on its own partition, is never touched.

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

## Set up (done, 2026-11-20)

| | |
|---|---|
| **Your key pair** | Made with `release.py keygen`. The public half is `device/config/update-key.pem`, fingerprint **3D92 866F 8686 CCB3**. The private half is on your computer, normally `~/companion-signing/update-key-private.pem` |
| **The update address** | [seafire220/update-repo](https://github.com/seafire220/update-repo), a public repository just for updates. `device/config/update.json` points devices at `https://github.com/seafire220/update-repo/releases/latest/download/latest.json`, which always serves the newest release's files. Until the first release it answers "not found", which devices take as "up to date" |

Build the device images you sell from now on. `device/check-image.sh` fails an image that has no update key.
A device made before this can only be updated by re-flashing its card.

### Your keys

The two `.pem` files are **plain text**. Nothing opens them, and nothing needs to:
- Double-clicking one on a Mac starts Keychain Access, which can't use this kind of key. That's expected and harmless. Keychain and passkeys play no part here.
- To look at the public key, open it in TextEdit. Never paste the private key anywhere: not in a chat, an email, GitHub or a cloud note.
- The release tool reads the private key by its place on disk. Leave it in `~/companion-signing` (in Finder: **Go → Home → companion-signing**), and the tool finds it by itself.

**Back the private key up** somewhere safe and offline-ish: an encrypted USB stick, or a password manager that stores files (1Password, Bitwarden). Lose it, and you can never update the devices you have sold. Whoever has it can update all of them.

**Check it**, in Terminal, in the project folder:

```bash
python3 device/release.py check
```

It prints both keys' fingerprints and says whether they match; it should say `3D92 866F 8686 CCB3` twice.
Nothing here needs OpenSSL: the tool signs in plain Python (`device/ed25519.py`), with exactly the bytes OpenSSL makes (tested). That matters on a Mac, whose `openssl` may not do this kind of key.

## Releasing an update

The update is built on GitHub, and signed on your computer, so the private key never leaves it.

1. **Build it.** On GitHub, in the project repository: **Actions → Make an update → Run workflow**. Give the version, newer than the last (dates work well: `2026.12.1`; a second one that day is `2026.12.1.2`), and what changed. The workflow (`.github/workflows/make-update.yml`) runs every test, builds the screen program for the Pi, and makes `companion-2026.12.1.unsigned.update`. About fifteen minutes.
2. **Download it.** On the finished run's page, under *Artifacts*, download `companion-2026.12.1-unsigned` and unzip it. It also holds the screen program on its own (`stage-aarch64`), for building device images.
3. **Sign it**, in Terminal, in the project folder:

   ```bash
   python3 device/release.py sign ~/Downloads/companion-2026.12.1-unsigned/companion-2026.12.1.unsigned.update
   ```

   It shows the version, notes and size, checks the update carries your public key and the update address (so devices can still update after installing it), and writes `companion-2026.12.1.update` and `latest.json` next to it.
4. **Try it** on your own device first: **Device → Software → choose an update file**.
5. **Publish it.** In [seafire220/update-repo](https://github.com/seafire220/update-repo): **Releases → Draft a new release**, tag `v2026.12.1`, attach both files, **Publish release**. Devices pick it up within half a day, and install it the next night.

Building on your own computer instead also works, if it has a cross-compiler for the Pi (`stage/README.md`):

```bash
python3 device/release.py build --version 2026.12.1 --stage-binary stage/target/aarch64-unknown-linux-gnu/release/stage --notes "Kinder greetings"
```

It refuses to sign with a key that doesn't match `device/config/update-key.pem`, because devices would refuse that update.

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
