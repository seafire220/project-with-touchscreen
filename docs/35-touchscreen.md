# Touchscreen edition: tactile interaction and on-screen glass controls

Status: 2026-11-21. Built and tested across `stage` (Rust/OpenGL ES 3.0) and `core` (Python).

This document describes the touchscreen experience on the premium version of the
character device. The Raspberry Pi Touch Display 2 (5" or 7", 720×1280 portrait)
already has a built-in capacitive touch controller wired through the DSI ribbon,
which `cage` forwards to `stage` via Wayland `wl_touch`. Desktop mouse clicks and
drags are also mapped to the same touch path for development and testing.

Physical listen and mute buttons remain 100% supported alongside the touchscreen,
and become optional on touchscreen units.

---

## Design goals

1. **Character-first canvas**: At rest, the screen belongs to the character. Only a
   minimal translucent capsule sits at the bottom edge (showing the clock, microphone
   status dot, and active timer countdown if any) and yields automatically whenever
   captions are displayed.
2. **Zero-latency tactile feedback**: Touch recognition, eye tracking toward the
   finger, petting physics, reaction animations, expanding ripples, hearts, sparkles,
   and ambient listening/speaking edge glow run natively at 60 fps inside `stage` in
   Rust + OpenGL ES 3.0 — no round-trip through Python before pixels move.
3. **1 GB RAM friendly, zero extra dependencies**: On-screen controls are rendered
   by `core` as crisp 2×-supersampled frosted-glass PNG overlays using Pillow (already
   installed) with custom anti-aliased vector icons (no emoji font assumptions on
   Raspberry Pi OS Lite), and composited by `stage` with cubic slide-in transitions
   and modal backdrop scrims.
4. **Full standalone usability**: Everyday controls, character switching, timers,
   moods, settings QR code, and complete Wi-Fi setup (including hidden networks and
   password entry via a full QWERTY/numeric/symbol touch keyboard) work right on the
   screen without needing a phone or physical buttons.

---

## Feature pillars

### 1. Tactile character interaction (`stage/src/touch.rs`, `stage/src/fx.rs`)

- **Anatomical hit zones**: Normalized screen coordinates are mapped to `head`,
  `face`, `body`, and `background`, automatically calibrated to the active framing
  (`bust`, `upper`, `full`) for 2D Inochi2D, `.model3.json`, and 3D VRM models.
- **Headpats & cheek rubs**: Stroking back and forth across the character's head or
  face detects direction reversals and drives smooth continuous petting motion
  (gentle head lean into the hand, happy squinting eyes, soft blush, ear/head bob)
  plus floating rose hearts and 4-point sparkles from the fingertip. Completing a
  stroke plays the `headpat` or `cheek_rub` reaction clip from `stage/motions/library.json`.
- **Pokes, double-taps & finger tracking**:
  - Holding or gliding a finger smoothly pulls the character's eyes (`eye_x`/`eye_y`)
    and subtle head turn toward the fingertip with a soft fingertip aura.
  - Tapping the face or body triggers a crisp tap ripple, sparkles, and
    `poke_surprised` (or `poke_giggle` on a playful double-tap).
  - Tapping the background creates a subtle luminous ripple and glances toward the tap.
- **Wake-on-touch**: When the screen is dim or off at night, the first tap wakes
  the display and backlight immediately (`touch_wake`) and is consumed so it never
  accidentally presses a control underneath.
- **Ambient edge glow**: While listening (cyan) or speaking (violet), a soft audio-reactive
  glow breathes along the bottom edge of the screen behind the overlays.
- **Optional spoken reactions (`core/companion/device.py`)**: Tactile animations and
  effects always play immediately. When `touch.spoken_reactions` is enabled (default
  on), headpats, cheek rubs, and pokes can also trigger a brief in-character spoken
  reply — guarded by a configurable cooldown (`touch.reaction_cooldown`, default 25 s),
  idle-only gating, family-safe rules, and silent fallback if no language model key
  is configured yet.

### 2. Auto-hiding translucent glass dock (`core/companion/touch_ui.py`)

- **Opening & dismissing**: Swipe up from the bottom edge or tap the floating bottom
  pill to slide open the frosted-glass Quick Controls Dock. Tap the dimmed backdrop,
  swipe down on the sheet, tap the close button, or simply leave it idle for
  `touch.auto_hide` seconds (default 8 s) to fade back to the clean character view.
- **One-tap interrupt / stop**: While listening or speaking, the bottom pill switches
  to an active cyan/violet state (`Listening · Tap to send/stop` or `Speaking · Tap to stop`)
  so a single tap interrupts or finishes the turn without opening a menu.
- **Quick controls**:
  - **Talk / Stop** primary action button + **Mute** toggle (respects hardware mute
    switch precedence if one is fitted).
  - **Volume** and **Brightness** interactive sliders (tap anywhere or drag smoothly).
  - **2×3 quick tile grid**: Characters, Captions on/off, Night/Sleep (tap screen to
    wake), Timers, Wi-Fi, and More & QR.

### 3. Character switcher, timers & moods/QR sheets

- **Character Switcher**: 2×2 card grid displaying each installed character's rounded
  preview thumbnail (or color-coded monogram fallback), 2D/3D format badge, active
  highlight, swipe left/right or Prev/Next pagination, and one-tap switching.
- **Timers & Clock** (also reachable via top-edge swipe-down): Large digital clock
  and date card, quick-set timer buttons (`+1m`, `+5m`, `+10m`, `+15m`, `+30m`),
  live 1-second countdowns, and one-tap cancellation.
- **Moods & Console QR**: One-tap expression/gesture triggers (`Happy`, `Calm`,
  `Wow`, `Shy`, `Wave`), instant toggles (`Spoken touch reactions`, `Wake word`,
  `Show what it heard`), and a scannable QR card + URL for the local web console.

### 4. On-screen Wi-Fi setup & full touch keyboard

- **Works from first boot**: When the device has no Wi-Fi and shows the *Set up Wi-Fi*
  card (or the *Hello!* setup card), the bottom pill displays **Set up Wi-Fi on screen**
  so the owner can connect directly on the display without a phone or USB cable.
- **Wi-Fi Picker**: Live scan button, signal-strength + lock vector icons, pagination,
  open-network one-tap join, and **Enter hidden network name…**.
- **Touch Keyboard**: Full QWERTY (`abc`), shifted/Caps-Lock (`ABC`, double-tap Shift
  for Caps Lock), numeric (`123`), and symbols (`#+=`) layouts, password show/hide
  eye toggle, backspace, Clear, 8–63 character WPA validation, and inline error retry.

---

## Stage ↔ Core protocol additions

### Core → Stage JSON commands

- `{"overlay": {"slot": "...", "image": "...", "anchor": "bottom", "layer": 30, "slide": "up", "scrim": 0.28}}`
  Extended optional fields (`layer`, `slide`: `"none"|"up"|"down"`, `scrim`: `0..1`)
  for z-ordered frosted-glass sheets and modal backdrops.
- `{"touch_config": {"enabled": true, "character_touch": true, "effects": true}}`
- `{"touch_capture": {"modal": false, "panel": [x0, y0, x1, y1], "pill": [x0, y0, x1, y1], "edge_swipe": true}}`
- `{"touch_sim": {"phase": "start|move|end|cancel", "x": 0.5, "y": 0.25}}` (synthetic touch for automated or remote testing)

### Stage → Core JSON events

- `{"event": "ready", "width": 720, "height": 1280, "touch": true}`
- `{"event": "touch_wake"}`
- `{"event": "ui_touch", "phase": "down|move|up|tap|long_press|swipe", "target": "pill|panel|backdrop|edge", "x": 0.5, "y": 0.9, "dir": "up|down|left|right"}`
- `{"event": "touch", "kind": "pet|poke|tap|double_tap|long_press", "zone": "head|face|body|background", "x": 0.5, "y": 0.24}`

---

## Settings & Web API

Stored under `settings["touch"]` in `core/companion/store.py` and editable on the web
console's **Device** tab:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Master enable for touchscreen UI and touch interaction |
| `character_touch` | `true` | Headpats, cheek rubs, pokes, and fingertip eye-tracking |
| `effects` | `true` | Procedural GPU ripples, hearts, sparkles, fingertip aura, and ambient glow |
| `spoken_reactions` | `true` | Allow brief spoken in-character replies to petting/poking |
| `reaction_cooldown` | `25.0` | Minimum seconds between spoken touch reactions (`5`–`300`) |
| `auto_hide` | `8.0` | Idle seconds before the Quick Controls Dock fades back to the pill (`3`–`60`) |

The web console also exposes `POST /api/touch` (behind the normal session cookie +
`X-Companion: 1` guard) for triggering views (`{"view": "dock"}`), character touch
reactions (`{"kind": "pet", "zone": "head"}`), or synthetic touch samples
(`{"sim": {"phase": "start", "x": 0.5, "y": 0.2}}`).
