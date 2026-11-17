# Evaluation: Ayagami, Umamo and Godot (and the ChatGPT handoff)

Date: 2026-11-17. The owner asked whether Godot, Umamo or Ayagami would help
the higher-end (Standard) device, even at the cost of rewriting, and whether
a summary of an earlier ChatGPT investigation is useful. A snapshot of
everything before this evaluation is on GitHub as branch
`snapshot-2026-11-17` and was given to the owner as a zip.

## What was done

| Tool | Done here | Result |
|---|---|---|
| **Ayagami** (renderer for Live2D-format models; Rust; MIT/Apache-2.0) | Cloned (commit 0d1d7aa, Sept 2026), built, benchmarked, rendered | Builds cleanly. Deformation maths for Live2D's own sample models (Hiyori, Haru, Mark, Natori, Mao): 0.03–0.20 ms per frame on one core. Rendered Hiyori correctly offscreen (software Vulkan): rest, head turn, tilt, blink and mouth all right. Demo renderer binary 15 MB. |
| **Inox2D** (our current renderer), same test | Benchmarked on three of our generated characters | 0.11 ms per frame, plus 11 ms to load |
| **Ayagami-gd** (Godot plugin for Ayagami) | Read source and README | Imports Live2D models, motions and expressions into Godot 4.7, but needs a **custom-patched Godot 4.7.1** for correct blending until a Godot change is merged |
| **Umamo** (editor; Kotlin, Java 21) | Read source and README | Alpha. Edits Live2D's *source* format (`.cmo3`); no animation yet. Has a **command-line converter from `.cmo3` to the playback format `.moc3`**. Desktop builds for Linux, Windows and Mac (Intel and Apple Silicon). Not built here (its build downloads are blocked in this session). |
| **Ayatsuri2D** (another editor; Rust) | Checked licence and status | Active (Nov 2026). Reads and writes Live2D files including physics, motions and expressions. **GPL-3.0**: fine as a separate tool, but its runtime cannot be built into closed device software. |
| **Godot** | Researched only | Runs on a Pi 4 with its Compatibility (OpenGL ES 3) renderer. Reports differ on whether official ARM64 export templates are included. Inochi2D has an official Godot plugin (written in D). No Pi 4 benchmarks found. |

Live2D's site is blocked from this session, so its licence texts could not
be read directly; see "Licensing" below.

## What each could do for the device

### Ayagami: worth adding, as a second format, not as a replacement

- **What it adds:** the device could show **Live2D-format models people
  already own** (many VTubers and buyers of ready-made models have them).
  Professionally hand-rigged models move far better than anything made
  automatically from one picture, as the Hiyori renders show.
- **What it does not add:** it does not make characters from a picture look
  better. A renderer only shows what the rig contains; our generated
  characters would look the same in either renderer. The same is true of
  Godot.
- **Speed:** its deformation maths costs about the same as Inox2D's. On a
  Pi 4, expect about 1–2 ms per frame: not the limit. Drawing speed is the
  thing to measure on the device.
- **Graphics:** it draws with wgpu, which on a Pi 4 would use the Mesa
  Vulkan driver (v3dv) or OpenGL ES. Not tested on a Pi.
- **Fits our code:** it is Rust, like the stage, and keeps its maths
  separate from its drawing. Two ways to add it:
  1. Inside our stage: write a small OpenGL ES renderer for its output, or
     move the stage to wgpu. Moderate work; keeps the device light.
  2. Through Godot with Ayagami-gd: needs a patched Godot build (below).
- **Bonus:** our core already uses Live2D's standard parameter names
  (`ParamAngleX`, `ParamMouthOpenY`, `ParamEyeLOpen`...), so emotions,
  gestures, blinking and lip movement would work on Live2D models with no
  change.

### Umamo: worth keeping in view as a free editor, not for the device

- If characters are ever made in Live2D's format, Umamo would let a person
  fix a generated rig by hand (for example the arms) and convert it for
  playback, with no Cubism Editor. Our rigger can already write `.cmo3`
  without using any Live2D sample files, so a fully open chain is possible:
  picture → our cutting → rigger → `.cmo3` → Umamo (optional fixes) →
  `.moc3` → Ayagami. **Untested**: both the rigger's `.cmo3` writer and
  Umamo's converter are early.
- For our current format, the equivalent editor is Inochi Creator.

### Godot: not now

- **What it adds:** a full application framework on the screen: menus,
  text, touch, transitions, backgrounds, particle effects, an animation
  editor. Through plugins it could show both Inochi2D (official plugin)
  and Live2D-format (Ayagami-gd) characters in one program.
- **What it costs:**
  - Memory and start-up time on a 1 GB Pi that also runs speech
    recognition (the core already takes about 220–360 MB; Godot would add
    an estimated 100–200 MB, to be measured).
  - A custom-patched Godot build for Ayagami-gd, and the Inochi2D plugin
    built from Inochi2D's D source, whose main branch failed to build when
    tried here two days ago. Both would need building for ARM64.
  - A rewrite of the stage, and of the gesture work just done.
- **Verdict:** the gains are mostly looks (fourth in the owner's priority
  order, after repairability, boot speed and idle power). The screens we
  need now (setup instructions, a QR code) the stage can already show.
  Worth revisiting if the higher-end model gets a larger screen with menus
  or touch games, or a board with 2 GB or more.

## The arms

The unnatural arm movement is a character-making problem, not a renderer
problem: swinging an arm uncovers a blurred guess of what was behind it.
No engine fixes that. The fixes are in the studio: better reconstruction of
the body behind the arms, or alternative arm drawings for set gestures
(D-029). Hand-rigged Live2D models avoid it because an artist drew the hidden
parts.

## Licensing

- **Ayagami** is MIT/Apache-2.0 and its authors state it may be used in
  products that load user-supplied models, with no royalties. It is a
  clean-room reimplementation (black-box reverse engineering).
- **Open questions before selling Live2D-format support:**
  1. Whether Live2D Inc. asserts any rights over its file format against
     independent players. Live2D's own SDK needs a separate agreement for
     "embedded use", but Ayagami does not use their SDK.
  2. Whether the Cubism Editor licence restricts which programs may play
     models its users export. This would bind users, not us, but it matters
     for a product advertised to them.
  These need the current licence texts (blocked here) and probably legal
  advice. Until then, the device stays on the open Inochi2D format, as
  decided earlier for licensing reasons.

## The ChatGPT handoff (`Claude_Handoff_2D_Animation_Hardware_2026-11-17.md`)

Useful, and mostly consistent with what was found here. Worth keeping:

- **Live2D's published terms** for apps that load user models ("expandable
  applications"): a contract even for small businesses, ¥300 per sale or
  20%, whichever is higher. This is why the official Live2D runtime stays
  out.
- **E-mote**: the free movie maker excludes corporate commercial use; the
  indie SDK contract is ¥0 under ¥10 million sales but has no confirmed
  Linux ARM or ESP32-P4 runtime.
- **The ESP32-P4 Lite architecture**: prepared animation clips (idle,
  listening, talking, emotions) as JPEG frames, using the P4's hardware JPEG
  decoder (its H.264 hardware is encode-only), played by a small ESP-IDF/LVGL
  program, with optional separate mouth and eye layers. This matches the
  Lite plan in the architecture document and adds the right technical
  detail; adopt it for Lite.

Out of date or superseded:

- It treats the Inox2D route as untested. It has since been built, patched
  and run with generated and hand-made puppets (docs 07, 12).
- Godot 3.6 with GLES2 was suggested; the Pi 4 supports OpenGL ES 3.1, so
  Godot 4's Compatibility renderer would be the choice if Godot is used.
- Ayagami now has physics and a Godot plugin; Umamo now has a
  command-line converter.

## Since this evaluation: characters in the Live2D format

The owner asked for a picture-to-Live2D-format route rather than ready-made
Live2D models. It now exists (D-039): the finished Inochi2D puppet is
converted, movement for movement, into a `.moc3` model, and Ayagami plays it
the same as our stage plays the puppet (checked on all seven test poses, and
by replaying every vertex against Inox2D's maths: within 1.5-1.9 px on
eleven characters). The rigger's own Live2D-format output was also tried; it
uses the older head movement, so converting our puppet is better. Ayagami
deformed the converted Alice in 0.05 ms per frame, as fast as the rigger's
simpler model. The licensing questions are now written up in
`19-live2d-format-licensing.md`.

## Recommendation

1. **No rewrite.** Keep the current stage (Inox2D) and core. They work, they
   are light, and characters made from pictures would not look better in
   another engine.
2. **For the higher-end model, add Live2D-format playback with Ayagami
   inside the existing stage**, so owners can bring models they already
   have. Do this only after the licensing questions above are answered.
3. **Keep Umamo and Ayatsuri2D in mind as optional desktop editors** for
   hand-fixing characters; neither belongs on the device.
4. **Godot later, if ever:** only for a bigger-screen model where rich menus
   or touch play matter, and after measuring its memory on the Pi.
5. **Lite on the ESP32-P4:** follow the handoff's prepared-clip design.

Sources: [Ayagami](https://github.com/AyagamiDev/ayagami),
[Ayagami-gd](https://github.com/AyagamiDev/ayagami-gd),
[Umamo](https://github.com/future2d/umamo),
[Godot system requirements](https://docs.godotengine.org/en/4.5/about/system_requirements.html),
[Godot on Raspberry Pi 4 (forum)](https://forum.godotengine.org/t/godot-4-build-for-raspberry-pi-4/47798),
[Inochi2D (official Godot binding)](https://github.com/Inochi2D/inochi2d),
[Live2D SDK licence page](https://www.live2d.com/en/sdk/license/).
