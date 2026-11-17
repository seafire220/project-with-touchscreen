# Roadmap: what is done, what comes next, how to resume

Status: 2026-11-17. A living plan: update the status column as items are
finished. Work in this order unless the owner says otherwise; each item
lists what "done" means.

## Where things stand

Done and tested in software (not yet on real hardware):

- Character making on a laptop, one command (`studio/make_character.py`):
  picture → parts → layers (with closed eyes, open mouth, hair behind the
  head, tapered neck) → rig → refined head and body movement
  (`20-head-turns.md`) → `.char` package, optionally with a Live2D-format
  copy (`--live2d`, `studio/live2d_export.py`).
- The device software: core service, settings page (buyers' own keys),
  Wi-Fi setup, buttons, resets, updates, ready-made Raspberry Pi OS image
  (`13`, `18`), Inox2D stage.
- Measuring and review tools: `studio/reveal.py` (uncovered area, gaps,
  made-up filler shown, outline movement), `stage/tools/pose_strips.py`.
- Licensing check for the Live2D format (`19`); owner's decision: Ayagami
  plays everything on the device, Inox2D stays as a fallback (D-040, plan
  of 2026-11-17).

## Next, in order

| # | Item | Done when | Status |
|---|---|---|---|
| 1 | **Board survey** (`22-board-options.md`): boards with a graphics chip Mesa supports (GL ES 3), ≥1 GB, Wi-Fi, sold in Australia, AUD prices | The owner can order one or two boards to test | done: Pi 5 1GB as reference, Radxa Zero 3W 2GB to measure |
| 2 | **Ayagami on the device**: the stage plays `visual/live2d/model.model3.json` with Ayagami's core and our OpenGL drawing (masks, blend modes, draw order), Inox2D kept for `.inp` and screen cards; the core prefers the Live2D-format copy; buyers can upload their own Live2D models | A converted character drawn by the stage matches the Inox2D drawing (alpha overlap ≥ 0.98) in pose strips; core, studio and stage tests pass; the device image builds and passes `check-image.sh` | in progress |
| 3 | **Drawing workflow, first test** (`23-drawing-workflow.md`): try generating alternate arm poses and head side views with the owner's Gemini key (image models), and See-through's hidden-area completion; assess the candidates in the owner's research notes (THA3, Qwen multiple angles, PSD2Live, Anime2.5DRig, Iki, Bunraku) | A written assessment with sample pictures, costs and licences; a recommended method | |
| 4 | **Head-turn polish**: split the front hair into fringe, left and right; the far side drops behind the face at strong turns (draw order by angle, also carried into the Live2D format); keep strands from getting too thin; clean light halos from background removal; review the tilt; close the arm gaps at a full body turn | Pose strips clean at ±100% on Alice and t3; reveal numbers no worse | |
| 5 | **Drawing workflow, built**: one-click laptop app (`studio/app.py`): picture in, completed hidden areas, alternate arm poses with gestures, review page, send to device; local GPU or the buyer's own key | A buyer-style run on a laptop without a GPU, using a key | |
| 6 | **90° turns**: generated profile artwork (side nose, lips, fill), ±50/±60 keys, corner tilt transfer, masks and draw-order changes (`20-head-turns.md`) | Strips at ±60 look like a profile, with no folds | |
| 7 | **Hardware bring-up** on the boards bought in item 1 (`15-hardware-test-plan.md`) | Measurements filled in `16-measurements.md` | |
| 8 | **Before selling**: original default character (needs commissioned art), signed updates from the settings page, support access, user guide, the lawyer's questions in `19` | | |

## How to resume in a fresh session

The repository holds everything that matters; the session's scratch area
(test pictures, labels, virtual environments, cloned tools) is lost when a
cloud container is recycled. To rebuild:

1. **Test pictures**: the owner's own pictures (Alice, t1–t5, f1–f5) are not
   in the repository (D-024). Re-upload them; labels are remade with the
   part-finding model (`14-making-characters.md`, about 30 s each on a
   CPU), or with `--labels` if the `.npz` files were kept.
2. **Studio**: `python3 -m venv venv && venv/bin/pip install -r
   studio/requirements.txt "git+https://github.com/Wzhang3912/image2live2d@714e7cc"`
   (add `-r studio/requirements-model.txt` and PyTorch for the part
   finder).
3. **Core**: `venv-core/bin/pip install aiohttp sherpa-onnx anthropic qrcode
   numpy pillow`; tests: `core/tests` with `python -m unittest discover`.
4. **Stage**: `cargo build --release` in `stage/` (Rust 1.85 or newer);
   the Pi build needs the `aarch64-unknown-linux-gnu` target and linker
   (`stage/.cargo/config.toml`).
5. **Ayagami** (until it is vendored in item 2): clone
   https://github.com/AyagamiDev/ayagami.
6. **Checks before committing**: studio tests (`cd studio && PYTHONPATH=../core
   python -m unittest discover`), core tests, `cargo test` in `stage/`,
   then pose strips and `reveal.py` on at least Alice and t3 for anything
   that changes movement.
