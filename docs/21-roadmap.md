# Roadmap: what is done, what comes next, how to resume

Status: 2026-11-18. A living plan: update the status column as items are
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
  (`13`, `18`), and the stage, which plays Inochi2D puppets with Inox2D and
  Live2D-format models with Ayagami (D-044). The core shows a character's
  Live2D-format copy when it has one; buyers can add their own
  Live2D-format models as a zipped model folder.
- Measuring and review tools: `studio/reveal.py` (uncovered area, gaps,
  made-up filler shown, outline movement), `stage/tools/pose_strips.py`.
- Conversations and memory (`31-memory.md`): conversations with clear
  ends, each summed up; lasting memories the model keeps up to date; plans
  followed up; a diary; all shown and editable on the Memory tab. The
  language model can be a cloud service or one on the owner's own computer
  (`28-user-guide.md`).
- Licensing check for the Live2D format (`19`); owner's decision: Ayagami
  plays everything on the device, Inox2D stays as a fallback (D-044). Six
  questions remain for a lawyer before selling.

## Next, in order

| # | Item | Done when | Status |
|---|---|---|---|
| 1 | **Board survey** (`22-board-options.md`): boards with a graphics chip Mesa supports (GL ES 3), ≥1 GB, Wi-Fi, sold in Australia, AUD prices | The owner can order one or two boards to test | done: Pi 5 1GB as reference, Radxa Zero 3W 2GB to measure |
| 2 | **Ayagami on the device**: the stage plays `visual/live2d/model.model3.json` with Ayagami's core and our OpenGL drawing (masks, blend modes, draw order), Inox2D kept for `.inp` and screen cards; the core prefers the Live2D-format copy; buyers can upload their own Live2D models | A converted character drawn by the stage matches the Inochi2D drawing (alpha overlap ≥ 0.98) in pose strips; core, studio and stage tests pass; the device image builds and passes `check-image.sh` | done in software (D-044): overlap ≥ 0.989 in 13 poses; matches Ayagami's own renderer on 8 sample models; all tests pass; textures packed (158 → 68 MB). The image build and a Pi run moved to item 8 (no base image or ARM emulation in the session) |
| 3 | **Drawing workflow, first test** (`23-drawing-workflow.md`): free, local tools only, making parts for the rig (not pictures): See-through's completed transparent layers, arms cut into pieces that turn at the joints, alternate part drawings only where deformation cannot reach. Assess **every** candidate in the owner's research handoff (`live2d_automatic_rigging_research_handoff.md`, 2026-11-18): direct rigging (Image2Live2D, already our rigger and `.moc3` writer; PSD2Live; Bunraku; Anime2.5DRig; Iki; See-through) and multi-view generation (Qwen Image Edit Multiple Angles, THA3, DiffPortrait360, PAniC-3D, CharacterGen, Rotate Your Character, Character 12-View), using its search terms (novel view synthesis, multi-view diffusion, character turnarounds, occlusion-aware inpainting, mesh keyform prediction) to find newer ones | A written assessment answering the handoff's questions (what duplicates ours, licences of code and weights, measured versus reported memory, smallest adapter to our rig), with sample pictures, costs and a recommended method | assessment written (`23`); method corrected to free, local, parts-only (owner, 2026-11-18); jointed arms done by deformation (true shoulder and elbow rotation, rounded elbows, body painted in behind, each character's own wave and hip poses; `24-motion.md`); See-through's completed layers next, on an original character only |
| 4 | **Motion on a generic skeleton** (D-045; from the owner's look at a friend's VTubing app): write up how VTubing apps make any model move well (standard humanoid skeleton, retargeting, smoothing filters and curves, expression rules), then grow the stage's controls into an upper-body skeleton with arms and hands; author idle motion and talking gestures once against it, including motion recorded from real people; smooth every control (filters, springs); fit buyers' models to it with a calibration step; play models' own motions and expressions | A written design (`24-motion.md`), then the same gesture set playing naturally on our characters and on imported models, judged in side-by-side clips | design written; built: springs and 1€ filter, more controls, gaze shifts, drifting posture, beats with speech, seven moods and eighteen gestures that follow the conversation's emotion tags, gestures the mood starts by itself; checked end to end with the real core and stage; elbows and each character's own wave and hip poses; movement settings on the settings page (any character: which parameter each movement uses, reversed or off, tested live); mouth shapes for each syllable and movements on their words, with the feeling guessed when the model leaves out its tags (the director's steps 1 and 2); gestures on different parts of the body at once, with a budget per minute (step 3). 2026-11-19: the rest of the director: idle life and times of day, dozing, listening and reactions, clips with variations, mirroring and stand-ins, temperament per character, the Animation tab (live view and gesture editor), and gestures recorded from video (`26-animation-director.md`). Played on all eleven test characters (`27-character-tests.md`): arms that did not show whole now stay still (D-046), the shrug plays on the forearms. Done, apart from checks on real hardware |
| 4c | **VRM avatars** (D-047, `30-vrm.md`): buyers add their own 3D avatars (`.vrm`, VRM 1.0 and 0.x), matched to the same rig and animated by the same library | Any avatar moves, talks and feels like the 2D characters; fits 1 GB | done in software (2026-11-19): the stage draws VRM (skinning, face shapes, MToon look, outlines, spring bones, constraints, look-at, framing); the core imports, shrinks and checks uploads and shows the maker's terms; four real avatars play all 37 clips and pass the conversation check. Full-body style (D-048): 30 built-in VRM Animation clips (idle loops per mood and state, gestures, idle actions), the owner's own `.vrma` clips, failsafes for heavy avatars (import budget, lite drawing, frame-rate watchdog, crash fallback), a shot setting. 2026-11-19 (D-049): any VRM works with no rigging (six avatars from four makers, 101 to 357 bones, 161 to 204 MB); points shared between parts kept once (an ordinary VRoid avatar was refused before); four stepping turn clips (turn around, twirl, turn aside, look back) for the full-body style. Still to do: measure on a Pi; matcap and UV animation |
| 4b | **Product essentials** (`25-product-review.md`): a free local voice (sherpa-onnx, Kokoro or Piper) as the default; a guided personality form; memory that lasts (an archive of dated conversation summaries, recalled by the owner's words) | A buyer with only a language-model key can talk with a character that remembers last month | done (2026-11-18): free on-device voice (Piper LibriTTS-R, 24 surveyed voices, default); personality form on the settings page; lasting memory (one dated summary per conversation, recalled by the owner's words, editable), checked with a real model (`25`). Invented stage directions ("[smile]", "*giggles*") become feelings and gestures instead of being spoken. 2026-11-19: **memory, second version** (D-051, `31-memory.md`): conversations with clear ends, lasting memories as items (category, importance, dates) the model adds, updates and retires, plans that come back once their day has passed, a diary in the character's voice, the whole Memory tab; checked over eleven days with a real cloud model and a model on the owner's computer. **A model on the owner's own computer** (D-050): Ollama natively, eight other servers as OpenAI-compatible, found on the home network. Still to do: speaking first, matching by meaning |
| 5 | **Head-turn polish**: split the front hair into fringe, left and right; the far side drops behind the face at strong turns (draw order by angle, also carried into the Live2D format); keep strands from getting too thin; clean light halos from background removal; review the tilt; close the arm gaps at a full body turn | Pose strips clean at ±100% on the test characters; reveal numbers no worse | |
| 6 | **Drawing workflow, built**: one-click laptop app (`studio/app.py`): picture in, completed hidden areas, jointed arms and alternate part drawings for the gesture library, review page, send to device; free and local (a GPU makes it faster; without one, the slower path or today's fills) | A buyer-style run on an ordinary laptop, no paid services | started (2026-11-18): `studio/app.py` and `studio/start.sh` make a character from a dropped picture with progress, a software-drawn preview of it moving, arm choices, the personality form, and send it to the device over the home network (checked into the virtual device). Still to come: See-through's completed layers and alternate part drawings, a Windows launcher, a run on the owner's own laptop |
| 7 | **90° turns**: generated profile artwork (side nose, lips, fill), ±50/±60 keys, corner tilt transfer, masks and draw-order changes (`20-head-turns.md`) | Strips at ±60 look like a profile, with no folds | |
| 8 | **Hardware bring-up** on the boards bought in item 1 (step by step: `29-hardware-setup.md`; tests: `15-hardware-test-plan.md`), including the device image with the new stage (`build-image.sh`, `check-image.sh`), frame rate with our characters and with mask-heavy imported models | Measurements filled in `16-measurements.md` | |
| 9 | **Before selling**: original default character (needs commissioned art), signed updates from the settings page, support access, user guide (first version: `28-user-guide.md`), the six lawyer questions in `19` (do not advertise Live2D-model import before the Cubism Editor question is answered) | | |

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
5. **Ayagami** is vendored in `stage/vendor/ayagami` (commit in
   `stage/vendor/PATCHES.md`); its own renderer, used once to check our
   drawing, is in the upstream repository (https://github.com/AyagamiDev/ayagami).
6. **Checks before committing**: studio tests (`cd studio && PYTHONPATH=../core
   python -m unittest discover`; with the stage built, this includes the
   two-format comparison on the synthetic test figure), core tests,
   `cargo test` in `stage/`, then pose strips and `reveal.py` on at least
   two test characters for anything that changes movement.
