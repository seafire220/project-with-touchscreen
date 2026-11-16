# Review of the owner's earlier work

Date: 2026-11-16. Source: a handoff brief the owner supplied, written at the
end of an earlier attempt at this project with another assistant.

Only the brief itself was supplied. The source archive, test packs and
evidence it refers to were not, so everything it reports is recorded here as
**claimed, not verified**. Nothing in this project depends on those claims
being true.

## What the brief says exists

| Area | Claimed state |
|---|---|
| Device software | An engineering release for two tiers: ESP32-P4 firmware for the cheaper tier, and a Linux controller with a browser kiosk for the premium tier. Conversation, startup and recovery code written; tested against simulated services only. |
| Hardware | Nothing physically built or tested. |
| Flat image to character | A working chain on paper: See-through splits the image, an open-source rigger builds the puppet. One real image went through it and failed visual review. A 24-image trial never ran because of a graphics-card quota. |
| Laptop companion | Scripts and a local browser page; not a finished application; no Mac path for the layer-splitting step. |

## Where it agrees with this project

The earlier work arrived independently at nearly the same parts and design,
which is reassuring:

- Cheaper tier on an ESP32-P4 screen board; premium tier on a Radxa Zero 3W
  with an HDMI screen, ReSpeaker Lite and a 5 W speaker.
- Inochi2D-family puppets, not Live2D.
- Owner-supplied API keys kept out of character files; no maker-run cloud.
- Mouth movement from the loudness of the audio being played.
- No camera, no battery, no on-device language model.

## What it adds

1. **An existing rigger.** `image2live2d` (Apache-2.0) turns named layers
   into a puppet with blink, mouth, head turn, body sway, breathing and
   hair/cloth physics, and writes an Inochi2D-family `.inp` file. This
   corrects an earlier statement in these documents that no such tool
   existed. Reading its source shows it writes only plain nodes, parts and
   simple physics, all of which the stage supports. It has not been run here.
2. **Where the real difficulty is.** Rigging is not the blocker. The step
   that turns a flat picture into separate layers is: it needs an NVIDIA
   graphics card, and on the one image actually tried it lost the head
   ornaments and changed the clothing, so the character was no longer
   faithful.
3. **The owner's laptop is an Apple Silicon Mac with 24 GB.** See-through
   targets NVIDIA cards. A Mac route is unproven.
4. **Sharper requirements**, now reflected in the specification:
   - An ordinary, unfamiliar anime image must become an attractive,
     recognisable animated character. Uploading a ready-rigged model does not
     count as meeting this.
   - Judged on independent artwork with fixed settings, failures kept. A
     file that builds, or pixels that move, is not evidence of a good result.
   - The customer tool should be a proper local laptop program, not a public
     demo site or a notebook.
   - Full-body characters.
5. **Useful discipline.** Its separation of "implemented", "executed",
   "visually accepted", "hardware-tested" and "production-ready" is adopted
   for status reporting here.

## Where this project differs, and why

| Topic | Earlier work | This project | Reason |
|---|---|---|---|
| Premium board | Radxa Zero 3W, 2 GB | Raspberry Pi 4, 1 GB (owner's choice), Radxa as fallback | Cheapest in Australian stock; lower risk |
| How the character is drawn | A puppet runtime compiled for the browser, shown by Chromium in kiosk mode | A small native program | A browser does not fit comfortably in 1 GB and starts slowly |
| Puppet runtime | nicxlive (C++) | Inox2D (Rust), with our fixes for OpenGL ES | Inox2D runs natively and was tested here; both read the same family of files |
| Build order | Both tiers in parallel | Premium tier first, microcontroller tier after | Owner's decision |

## What is needed from the owner

The source archive (`character-device-v0.8.0.zip`) and its evidence folders.
With them I can check what actually works and reuse it instead of writing it
again, in particular the ESP32-P4 firmware, the provider adapters, the layer
importer and the saved test images. Until then, new code is limited to parts
that are needed whichever way that review turns out.

## Test artwork

The owner supplied a full-body character illustration to test with. It
depicts an existing commercial character, so it is kept out of this
repository and will not appear in committed test data or screenshots. It is
a demanding case: plate armour, a cape, and long hair hanging in front of the
body.
