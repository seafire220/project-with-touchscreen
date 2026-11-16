# Decision log

One entry per significant decision: what was chosen, why, and what was
rejected. Settled entries are not reopened without new evidence.

## D-001 — Reference product

- Date: 2026-11-16
- Decision: the benchmark is the SyBran CODE27 Character Livehouse / Companion
  Hub (model SyBran-01).
- Why: it is the only SyBran product matching the brief.
- Open: confirm with the project owner that this is what "CODE Sybran" means.

## D-002 — Clean-room boundary

- Date: 2026-11-16
- Decision: reproduce function and user experience from publicly observable
  information only. No vendor firmware, source, character or voice assets,
  trademarks or trade dress. All software in this repository is original or
  from correctly licensed open-source projects.
- Rejected: firmware extraction, asset reuse, visual copies of the vendor's
  characters or interface.

## D-003 — No hardware commitment before requirements sign-off

- Date: 2026-11-16
- Decision: no SBC, display or audio part is selected until the requirements
  interview is answered and written up as a specification.
- Why: budget, depth-effect choice, model complexity and local-versus-cloud
  processing each change the board class. Choosing first would bake in guesses.

## D-004 — Scope changed to 2D, two tiers, for sale

- Date: 2026-11-16. Status: decided by the owner.
- Decision: no 3D or VRM. Lite uses pre-rendered 2D (video loops or frame
  sets); Standard uses a rigged 2D puppet. The design is intended to be sold.
- Consequence: every dependency must allow commercial distribution, and
  prototype and production sourcing are tracked separately.

## D-005 — No Live2D Cubism

- Date: 2026-11-16. Status: decided by the owner; confirmed by research.
- Why: a device that loads arbitrary user models is an "Expandable
  Application", which needs a paid agreement and revenue share regardless of
  business size.

## D-006 — One Linux platform for both tiers first; microcontroller Lite later

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Decision: prototype both tiers on one Linux board with one codebase. Keep
  the character package and web API free of Linux assumptions. Port Lite to
  an ESP32-P4 display board afterwards as a cost-reduction step.
- Why: one codebase that can be tested without hardware reaches a working
  product soonest; the puppet tier needs a graphics processor in any case.
- Rejected: starting Lite on the microcontroller now. It roughly halves Lite
  hardware cost and boots in seconds, but means a second codebase in C++ that
  cannot be tested here, and no on-device speech recognition.

## D-007 — Prototype hardware: Raspberry Pi 4 (1 GB), Touch Display 2 (5"), ReSpeaker Lite

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: cheapest board with a display connector, hardware video decode,
  reliable hotspot mode, first-party screen and compliance documents; the
  audio board removes echo in hardware. About A$239.
- Rejected: 2 GB boards (A$44+ for memory the software is designed not to
  need); Raspberry Pi 5 1 GB (kept as the fallback if recognition is slow);
  Radxa Zero 3W (cheaper overseas, more software risk; a production
  cost-reduction candidate); Pi Zero 2 W (512 MB, no display connector,
  scarce); second-hand tablets (not repairable, unstable supply).

## D-008 — The software must fit in 1 GB of RAM

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: in 2026 memory is the largest price step between otherwise similar
  boards.
- Consequence: lightweight embedded browser by default, small Python
  dependency set, no heavyweight frameworks.

## D-009 — The character is drawn by a web page in a kiosk browser

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Decision: plain JavaScript with canvas and WebGL, shown by WPE WebKit
  (`cog`) inside `cage`. Chromium is the fallback.
- Why: the same drawing code serves the device, the console's live preview
  and automated tests.
- Rejected: native Rust/C++ renderer; Godot; a bare video player.

## D-010 — Standard tier uses our own puppet format and runtime

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: no automatic rigger targets Inochi2D, so the rig generator must be
  written here regardless and it determines the runtime features needed.
  Inochi2D's reference runtime needs desktop OpenGL; its WebGL-capable port
  (Inox2D) describes itself as a prototype not for production use.
- Kept open: an importer for hand-made Inochi2D models later; its format is
  open and BSD-licensed.
- Rejected: Inochi2D runtime, Inox2D, nijilive, Live2D, Spine, Rive, Talking
  Head Anime 4.

## D-011 — Own lightweight conversation pipeline

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: full control of latency, interruption and memory use on a 1 GB
  device; adapters per protocol keep provider choice open.
- Rejected: Pipecat (BSD-licensed and capable, but its core dependency set is
  heavy for this device). To revisit if maintaining adapters becomes a
  burden.

## D-012 — Speech recognition runs on the device by default

- Date: 2026-11-16. Status: proposed, following the owner's stated preference.
- Decision: sherpa-onnx streaming recognition on the device; cloud
  recognition selectable.
- Open: speed on the Pi 4 is not yet measured.

## D-013 — Character creation runs from the device's web UI on the user's keys

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: the seller hosts nothing, pays for no AI usage and holds no user
  data. Processing that the device cannot do happens at the AI provider or in
  the user's browser.
- Rejected: a seller-run cloud service (ongoing cost, liability, lock-in).

## D-014 — Audio over USB

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: no driver or board-specific configuration; replaceable by unplugging;
  works on any future board.
- Rejected: header-pin audio boards (slightly cheaper, tied to one board
  family).

## D-015 — API keys protected by permissions, masking and exclusion, not encryption

- Date: 2026-11-16. Status: proposed, awaiting the owner.
- Why: without a secure element the decryption key would be stored beside
  the data. Keys are write-only in the console, masked in logs, and left out
  of every package, export and backup.
