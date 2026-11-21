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

- **Anatomical hit zones & software rotation**: Normalized screen coordinates are
  optionally rotated (`screen.rotation` ∈ `0|90|180|270`) before mapping to `head`,
  `face`, `body`, and `background`, calibrated to the active framing (`bust`,
  `upper`, `full`) for 2D Inochi2D, `.model3.json`, and 3D VRM models.
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
- **Multi-touch gestures (`stage/src/touch.rs`)**:
  - **Two-finger pinch in / out**: Cycles 3D VRM camera framing live
    (`bust ↔ upper ↔ full`) via `Command::Shot` without restarting `stage`.
  - **Two-finger horizontal swipe**: Switches directly to the next or previous
    installed character. Parallel-motion disambiguation prevents sequential finger
    packets during a two-finger swipe from false-triggering a pinch.
- **Per-character bond, persona style & Care/Treats (`core/companion/device.py`)**:
  - Each character tracks headpats, cheek rubs, pokes, treats, and high-fives in
    `characters/<cid>/touch-stats.json`, advancing bond tiers (`New friend` → `Warm`
    → `Close` → `Bestie`) and inferring a tactile style (`shy`, `playful`, `warm`)
    from its persona to nuance spoken touch replies.
  - **Care & Treats** (`Warm Tea`, `Snack`, `Gold Star`, `High-5`) in the Moods &
    Care sheet trigger native GPU celebration bursts (`touch_fx` `"celebrate"` /
    `"hearts"`), happy animations, a harmonic chime, and an optional spoken reaction.
- **Wake-on-touch**: When the screen is off, dim, or in Nightstand Mode, the first
  tap wakes the display and backlight immediately (`touch_wake`) and is consumed so
  it never accidentally presses a control underneath.
- **Ambient edge glow**: While listening (cyan) or speaking (violet), a soft audio-reactive
  glow breathes along the bottom edge of the screen behind the overlays.
- **Subtle tactile UI sounds (`core/companion/sounds.py`)**: Zero-dependency cached
  24 kHz S16LE synthesized harmonic cues (`tap`, `open`, `close`, `listen_start`,
  `listen_stop`, `headpat`, `poke`, `gift`, `timer`, `test`). Controlled by
  `touch.sounds` (default `true`) and automatically suppressed while speaking or
  recording so cues never clash with voice.
- **Optional spoken reactions (`core/companion/device.py`)**: Tactile animations and
  effects always play immediately. When `touch.spoken_reactions` is enabled (default
  on), headpats, cheek rubs, pokes, and treats can also trigger a brief in-character
  spoken reply — guarded by a configurable cooldown (`touch.reaction_cooldown`,
  default 25 s), idle-only gating, family-safe rules, and silent fallback if no
  language model key is configured yet.

### 2. Auto-hiding translucent glass dock (`core/companion/touch_ui.py`)

- **Opening & dismissing**: Swipe up from the bottom edge or tap the floating bottom
  pill to slide open the frosted-glass Quick Controls Dock. Tap the dimmed backdrop,
  swipe down on the sheet, tap the close button, or simply leave it idle for
  `touch.auto_hide` seconds (default 8 s) to fade back to the clean character view.
- **One-tap interrupt / stop**: While listening or speaking, the bottom pill switches
  to an active cyan/violet state (`Listening · Tap to send/stop` or `Speaking · Tap to stop`)
  so a single tap interrupts or finishes the turn without opening a menu.
- **Fast Pi 4 slider dragging**: The static dock base layer (glass panel, header,
  hero buttons, and 2×3 tile grid) is cached as a single 1× RGBA image (~2.1 MB,
  released immediately when the dock closes) and slider drags are throttled to 45 ms,
  only compositing the two thin slider strips so Volume and Brightness drag smoothly.
- **Quick controls**:
  - Header with active character name, mood/bond label, compact **Chat** pill button,
    live clock, and close button.
  - **Talk / Stop** primary action button + **Mute** toggle (respects hardware mute
    switch precedence if one is fitted).
  - **Volume** and **Brightness** interactive sliders (tap anywhere or drag smoothly).
  - **2×3 quick tile grid**: Characters, Captions on/off, Sleep (Off / Dim / Nightstand),
    Timers, Wi-Fi, and More & Care.

### 3. Chat & Quick Prompts, Character Switcher, Timers, Moods & Nightstand

- **Chat & Quick Prompts Drawer** (swipe right from the left edge, or tap **Chat** in
  the dock header): Displays recent conversation bubbles directly from `history.jsonl`,
  4 one-tap quick prompts (`How's my day?`, `Fun fact`, `25m focus`, `Cheer me up`),
  a **Type a message…** button launching the touch keyboard in message mode, and a
  **Talk** button.
- **Ambient Nightstand Desk Mode** (`screen.how = "nightstand"` or **Moods & Care → Nightstand**):
  Dims the backlight to ~18%, displays a low-glare warm bedside clock (and next timer
  countdown) at `layer = 90` *above* the night dimming veil, puts the character into a
  soft drowsy breathing state while throttling `stage` rendering to ~12 fps (pausing
  the quality watchdog and refreshing the clock every 30 s) for cool, quiet bedside
  operation. Tapping anywhere wakes smoothly.
- **Character Switcher**: 2×2 card grid displaying each installed character's rounded
  preview thumbnail (or color-coded monogram fallback), 2D/3D format badge, active
  highlight, swipe left/right or Prev/Next pagination, and one-tap switching.
- **Timers & Clock** (also reachable via top-edge swipe-down): Large digital clock
  and date card, quick-set timer buttons (`+1m`, `+5m`, `+10m`, `+15m`, `+30m`),
  live 1-second countdowns, and one-tap cancellation.
- **Moods & Care**: Active bond badge, one-tap expression/gesture triggers (`Happy`,
  `Calm`, `Wow`, `Shy`, `Wave`), interactive **Care & Treats** (`Warm Tea`, `Snack`,
  `Gold Star`, `High-5`), 2×2 quick toggles (`Touch speech`, `Touch sounds`,
  `Wake word`, `Show heard`), a Tools row (**Bluetooth**, **Setup Wizard**,
  **Nightstand**), and a scannable QR card + URL for the local web console.

### 4. On-screen Wi-Fi, Bluetooth Audio, Quick Setup Wizard & Touch Keyboard

- **Works from first boot**: When the device has no Wi-Fi and shows the *Set up Wi-Fi*
  card (or the *Hello!* setup card), the bottom pill displays **Set up Wi-Fi on screen**
  so the owner can connect directly on the display without a phone or USB cable.
- **3-Step Quick Setup Wizard** (**Moods & Care → Setup Wizard**):
  - *Step 1 (Wi-Fi)*: Live network connection status + launcher to the Wi-Fi picker.
  - *Step 2 (Audio & Touch)*: One-tap harmonic **Test chime**, software touch
    rotation selector (`0°`/`90°`/`180°`/`270°`), and an interactive **Touch Calibration
    Target** pad that plots a glowing dot and emits GPU sparkles at the exact tapped
    coordinates.
  - *Step 3 (Ready & Console)*: Live readiness checklist (Wi-Fi, active character, AI
    key) + scannable Settings Console QR card.
- **Bluetooth Audio Pairing (`core/companion/bluetooth.py`)**: Zero-dependency async
  `bluetoothctl` manager with an on-screen pairing sheet (**Moods & Care → Bluetooth**)
  and matching **Device → Bluetooth audio** web console controls to scan, pair,
  trust, connect, and disconnect wireless speakers or headphones (PipeWire routes
  audio automatically).
- **Wi-Fi Picker & Full Touch Keyboard**: Live scan, signal-strength + lock icons,
  hidden SSID entry, full QWERTY (`abc`), Shift/Caps-Lock (`ABC`), numeric (`123`),
  and symbols (`#+=`) layouts supporting Wi-Fi SSIDs, WPA passwords (with show/hide
  eye toggle and 8–63 char validation), and typed chat messages (`Send`).

---

## Stage ↔ Core protocol additions

### Core → Stage JSON commands

- `{"overlay": {"slot": "...", "image": "...", "anchor": "bottom", "layer": 30, "slide": "up", "scrim": 0.28}}`
  Extended optional fields (`layer`, `slide`: `"none"|"up"|"down"`, `scrim`: `0..1`)
  for z-ordered frosted-glass sheets and modal backdrops. Overlays with `layer >= 80`
  (such as the Nightstand clock at `layer = 90`) draw cleanly above the night dimming veil.
- `{"screen": "on" | "dim" | "off" | "nightstand"}`
- `{"touch_config": {"enabled": true, "character_touch": true, "effects": true, "rotation": 0}}`
- `{"touch_capture": {"modal": false, "panel": [x0, y0, x1, y1], "pill": [x0, y0, x1, y1], "edge_swipe": true}}`
- `{"touch_fx": {"kind": "hearts|sparkles|celebrate|ripple", "x": 0.5, "y": 0.36}}`
- `{"shot": "bust" | "upper" | "full"}` (live VRM camera framing update without restarting `stage`)
- `{"touch_sim": {"phase": "start|move|end|cancel", "x": 0.5, "y": 0.25}}` (synthetic touch for automated or remote testing)

### Stage → Core JSON events

- `{"event": "ready", "width": 720, "height": 1280, "touch": true}`
- `{"event": "touch_wake"}`
- `{"event": "ui_touch", "phase": "down|move|up|tap|long_press|swipe", "target": "pill|panel|backdrop|edge", "x": 0.5, "y": 0.9, "dir": "up|down|left|right"}`
- `{"event": "touch", "kind": "pet|poke|tap|double_tap|long_press", "zone": "head|face|body|background", "x": 0.5, "y": 0.24}`
- `{"event": "touch_pinch", "dir": "in|out"}`
- `{"event": "touch_swipe2", "dir": "left|right"}`

---

## Settings & Web API

Stored under `settings["touch"]` and `settings["screen"]` in `core/companion/store.py`
and editable on the web console's **Device** tab:

| Key | Default | Meaning |
|---|---|---|
| `touch.enabled` | `true` | Master enable for touchscreen UI and touch interaction |
| `touch.character_touch` | `true` | Headpats, cheek rubs, pokes, pinch framing, and fingertip eye-tracking |
| `touch.effects` | `true` | Procedural GPU ripples, hearts, sparkles, fingertip aura, and ambient glow |
| `touch.sounds` | `true` | Subtle synthesized tactile UI audio cues (suppressed during speech/recording) |
| `touch.spoken_reactions` | `true` | Allow brief spoken in-character replies to petting, poking, and treats |
| `touch.reaction_cooldown` | `25.0` | Minimum seconds between spoken touch reactions (`5`–`300`) |
| `touch.auto_hide` | `8.0` | Idle seconds before the Quick Controls Dock fades back to the pill (`3`–`60`) |
| `screen.how` | `"off"` | Night mode behavior: `"off"`, `"dim"`, or `"nightstand"` |
| `screen.rotation` | `0` | Software touch coordinate rotation compensation (`0`, `90`, `180`, `270`) |

The web console also exposes (behind the normal session cookie + `X-Companion: 1` guard):
- `POST /api/touch`: Open any view (`pill`, `dock`, `prompts`, `characters`, `timers`,
  `status`, `wifi`, `bluetooth`, `setup`, `nightstand`), give a treat (`{"treat": "tea|snack|star|high_five"}`),
  trigger character touch reactions (`{"kind": "pet", "zone": "head"}`), or inject
  synthetic touch samples (`{"sim": {"phase": "start", "x": 0.5, "y": 0.2}}`).
- `GET /api/bluetooth`, `POST /api/bluetooth/scan`, `POST /api/bluetooth/connect`,
  `POST /api/bluetooth/disconnect`: Wireless speaker and headphone pairing & control.
