# Low-cost AI character device

An independently designed, lower-cost alternative to the SyBran CODE27
Companion Hub: a desk device that shows a 2D anime-style character you can
talk to. Built from commodity hardware and original software, using the
owner's own AI service keys, with no lock-in to one AI or voice provider.

Two tiers: **Lite** plays pre-rendered 2D animation; **Standard** drives a
rigged 2D puppet. Standard is being built first.

## Status

| Phase | State |
|---|---|
| 1. Reference product research | First pass done |
| 2. Requirements interview | Answered |
| 3. Requirements specification | Draft 2 |
| 4. Hardware selection and BOM | Prototype board chosen: Raspberry Pi 4, 1 GB. Nothing bought yet |
| 5. Architecture | Revision 2 |
| 6. Software | Written and tested off the device: the stage (character drawing), the core service (conversation, providers, memory, characters, timers and alarms, web search, emotions and gestures, Wi-Fi setup), the web settings page, and character making from one picture |
| 7. Install, boot and appliance behaviour | Ready-to-flash device image builder, installer, services, setup screens with QR codes, Wi-Fi hotspot setup, resets, update/rollback. Built from the official Raspberry Pi OS image and checked under emulation; not yet on a Pi |
| 8. Guides | Build and install, making characters, hardware test plan |

**Tested so far:** 25 stage tests, 48 character-making tests, 54 core tests (one with the real on-device speech model),
11 browser checks of the settings page, the real core driving the real stage through a spoken reply (`core/tests/stack_check.py`), the installer run in a Debian 13
environment, and the Pi build of the stage started under ARM emulation.
Characters were judged by eye on eleven pictures, on software graphics.
**Not yet tested:** anything on real hardware; live AI services (no keys
here); the character maker on a Mac.

Estimated prototype cost: about A$239 (Raspberry Pi 4 option) or A$294
(Radxa Zero 3W option), against roughly A$850 for the reference product.

## Code

- [`stage/`](stage/README.md): draws and animates the character on the
  device screen (Rust, Inochi2D puppets, OpenGL ES). Cross-builds for the
  Pi from a PC.
- [`core/`](core/): the device's service (Python): conversation pipeline,
  provider adapters (OpenAI-compatible chat, speech and transcription;
  Anthropic; ElevenLabs with voice cloning; on-device speech recognition),
  character store and package checks, memory, timers and alarms, Wi-Fi
  setup, and the web settings page. Run it without hardware or keys with
  `core/tests/virtual_device.py`.
- [`studio/`](studio/): character making on a laptop.
  `make_character.py` turns one picture into a `.char` package: it finds
  the body parts with the See-through model (`parts_model.py`), removes a
  plain background (`prepare.py`), cuts the picture into layers and draws
  the closed eyes and open mouth it lacks (`partsplit.py`), rigs it with
  image2live2d, and refines head movement and the mouth (`refine.py`).
- [`device/`](device/): `build-image.sh` makes a ready-to-flash card image
  from the official Raspberry Pi OS Lite image; `check-image.sh` checks one;
  `install.sh` sets up a Pi by hand; services and system settings.

## Documents

1. [Reference product research](docs/01-reference-product-research.md)
2. [Requirements interview and answers](docs/02-requirements-interview.md)
3. [Requirements specification](docs/03-requirements-spec.md)
4. [Technology research](docs/04-technology-research.md)
5. [Hardware options and bill of materials](docs/05-hardware-and-bom.md)
6. [System architecture](docs/06-architecture.md)
7. [Test: Inochi2D on Linux](docs/07-spike-inochi2d.md)
8. [Review of the owner's earlier work](docs/08-prior-work-review.md)
9. [Experiment: flat image to puppet without repainting](docs/09-flat-image-experiment.md)
10. [Trial on five unfamiliar images](docs/10-generalisation-trial.md)
11. [Finding the parts with an existing model](docs/11-part-labelling-model.md)
12. [Trial on five fresh images, and the third head-movement design](docs/12-fresh-image-trial.md)
13. [Building and installing the device](docs/13-build-and-install.md)
14. [Making a character from a picture](docs/14-making-characters.md)
15. [Hardware test plan and troubleshooting](docs/15-hardware-test-plan.md)
16. [Measurements](docs/16-measurements.md)
17. [Evaluation: Ayagami, Umamo and Godot](docs/17-engine-evaluation.md)
18. [How the device works out of the box](docs/18-out-of-the-box.md)
19. [Licensing check: Live2D-format models without Live2D's software](docs/19-live2d-format-licensing.md)
20. [How heads turn](docs/20-head-turns.md)
21. [Roadmap: what is done, what comes next, how to resume](docs/21-roadmap.md)
22. [Board options for the Standard device](docs/22-board-options.md)
23. [Drawing workflow: hidden areas, alternate poses, new views (candidate assessment)](docs/23-drawing-workflow.md)
24. [Motion: a generic skeleton every character is fitted to](docs/24-motion.md)
25. [Does the whole product fit together?](docs/25-product-review.md)
- [Decision log](docs/decision-log.md)

## Awaiting the owner

- A verdict on the new head movement, blinks and mouths (review images and
  motion clips sent on 2026-11-17).
- Buying the prototype parts, so the hardware test plan can start.
- AI service keys, to test the providers against the real services (they
  are entered on the device, never in this repository).

## Known gaps

- No part has been bought or tested; every hardware statement is from
  documentation. The display overlay line and the sound card's name must be
  checked on first build.
- Memory use, boot time, frame rate and speech-recognition speed on the Pi
  are estimates until measured.
- The provider adapters follow each service's documentation and are tested
  against stand-ins only.
- Interrupting by speaking is an option, off by default, until the sound
  card's echo cancellation is confirmed on the device (the button always
  interrupts).
- Arm gestures are left out: the rig's arm swings leave smears behind the
  arm (D-035). Head, body and blush gestures work.
- Faces partly in profile show a small patch beside the face at the far
  ends of a head turn; tiny, heavily compressed pictures show faint lines
  round the eyes when enlarged.
- Lite tier, and a background-removal model for busy backgrounds, are not
  started.
- Compliance cost for selling in Australia has not been researched.
