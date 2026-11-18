# stage

The program that draws the character on the device's own screen.

It loads a character, either an Inochi2D puppet (`.inp` or `.inx`) or a
Live2D-format model (`.model3.json` with the files it names), keeps it alive
with breathing, blinking and small head and body movement, and moves its mouth
and changes its manner on command from the core service. It tells the two
formats apart by the file's contents, so the device's link can have any name.
It holds no API keys and makes no network connections.

Status: works on a virtual display with software graphics, in both OpenGL ES
and desktop OpenGL modes, and cross-builds for 64-bit Raspberry Pi OS.
**Not yet run on a Raspberry Pi or any real graphics chip**, so its frame
rate there is unknown.

## Build

```
cargo build --release
```

Needs Rust 1.85 or newer (tested with 1.97). The Inox2D renderer and
Ayagami's core (which plays Live2D-format models) are kept in `vendor/`, with
our changes and their exact versions listed in `vendor/PATCHES.md`; nothing but
ordinary crates is fetched at build time. For the Raspberry Pi, see
`.cargo/config.toml` (`cargo build --release --target aarch64-unknown-linux-gnu`).

## Run

```
target/release/stage character.inp --fullscreen
target/release/stage model/model.model3.json --size 720x1280 --socket /run/stage.sock
```

`stage --help` lists all options. `--gl es` forces OpenGL ES, which is what
ARM boards provide; the default tries OpenGL ES first and falls back to
desktop OpenGL.

## Commands

One JSON object per line, on standard input or the local socket:

| Command | Effect |
|---|---|
| `{"state": "idle"}` | Also `listening`, `thinking`, `speaking`. Changes posture and how lively the idle movement is. |
| `{"mouth": 0.7}` | Mouth openness from 0 to 1. The core sends the loudness of the voice being played, about 50 times a second. |
| `{"look": [0.2, -0.1]}` | Turn the head; each axis from -1 to 1. |
| `{"blink": true}` | Blink now. |
| `{"set": {"ParamCheek": 1}, "ease": 0.3}` | Drive named puppet parameters directly, blending in over `ease` seconds (default 0.25). Used for expressions and previews. A value can be a number, `[x, y]`, or `null` to hand the parameter back to the built-in behaviour. |
| `{"clear": true}` | Hand every directly set parameter back to the built-in behaviour. |
| `{"emotion": "happy", "intensity": 0.8}` | Change mood: how the character moves (liveliness, strength of its beats with speech), its resting posture and face, and the gestures it makes by itself. Blends in over about half a second. Moods: neutral, happy, sad, angry, surprised, embarrassed, thinking. |
| `{"gesture": "wave"}` | Play a gesture from `motions/library.json` on top of whatever the character is doing (`intensity` optional). Only gestures the character has the parameters for are accepted; the `ready` event lists them. |
| `{"random_gestures": false}` | Stop (or allow) gestures the mood starts by itself: now and then while speaking or idling, and small nods and tilts while listening. |
| `{"quit": true}` | Exit. |

Several fields can share one line.

## Events

One JSON object per line, on standard output and to socket clients:

| Event | Meaning |
|---|---|
| `ready` | Character loaded. Gives its format (`inochi2d` or `live2d`), its parameters, which controls were connected to which parameters, the moods and the gestures it can make, and the OpenGL version in use. |
| `features` | Live2D-format models only, after `ready`: how many meshes use masks (and inverted masks), culling, additive, multiplicative and newer blend modes, parts drawn off screen, whether there is physics, and the canvas size. |
| `warning` | Something that does not stop the character playing, such as a physics file that cannot be read. |
| `emotion`, `gesture` | A mood took effect; a gesture started, with its cause (`command`, `emotion` for a mood's entry gesture, or `mood` for one it started by itself). |
| `state` | The state changed. |
| `heartbeat` | Once a second: frames per second, and the average milliseconds per frame spent moving the character (`update_ms`) and handing its drawing to the graphics chip (`draw_ms`). The supervisor restarts the stage if these stop. |
| `error` | A command was not understood. |
| `fatal` | The stage cannot run; it exits with a non-zero status. |

## Characters it accepts

**Inochi2D puppets** whose nodes are plain nodes, parts, composites and
simple physics. Files using other node types (for example mesh groups) are
refused with a clear message rather than shown half-working.

**Live2D-format models**: a `.model3.json` and the `.moc3`, textures and
physics it names, read only from the model's own folder (the link to it is
followed first). Ayagami's core (`vendor/ayagami`) works out each frame;
`src/live2d.rs` draws it with OpenGL ES 3: premultiplied, mipmapped
textures; clipping masks, also inverted ones; Cubism's additive and
multiplicative blends; the newer blend modes, worked out in the shader
against a copy of what is already drawn; parts drawn off screen first; and
back-face culling. Textures larger than the graphics chip allows are scaled
down. Motions and expressions in the model are not played yet: the stage
drives the standard parameters itself. `--view` is in canvas pixels for these
models, and `--no-physics` stops hair and clothes swinging (for comparisons).

Controls are connected automatically when the puppet uses conventional
parameter names, either Inochi2D style (`Mouth:: Shape`, `Eye:: Left:: Blink`,
`Head:: Yaw-Pitch`, `Breath`, ...) or Live2D style (`ParamMouthOpenY`,
`ParamEyeLOpen`, `ParamAngleX`, ...). For other names, pass `--map file.json`:

```json
{
  "mouth_open": {"param": "Kuchi", "axis": "y"},
  "blink_left": {"param": "MeL", "invert": true},
  "head_roll": null
}
```

## Tests

```
cargo test --release                       # logic: 30 tests
python3 tools/visual_test.py target/release/stage PUPPET.inp out/ --gl es
python3 tools/compare_formats.py target/release/stage UNPACKED_CHARACTER/ out.png
```

`compare_formats.py` draws a character's Inochi2D puppet and its
Live2D-format copy (`make_character.py --live2d`) in thirteen poses and
reports how well they overlap; the studio's end-to-end test runs it on the
synthetic test figure and requires 0.98 or more. The Live2D drawing was also
checked against Ayagami's own renderer on Live2D's eight sample models, which
between them use every drawing feature above (overlap 0.970 to 0.9997 in
seven poses each; nearly all remaining differences are outline pixels, from
filtering textures in sRGB space as Cubism's OpenGL renderer does). The
sample models are not stored here.

The visual test needs `Xvfb`, Pillow and a rigged puppet with conventional
parameter names. It passes with a hand-rigged model (the "Aka" example from
`Inochi2D/example-models`, by seagetch, CC BY 4.0, distributed through Git
LFS and not stored here) and with puppets produced by the image2live2d
rigger, including its built-in sample (`python -m image2live2d --sample
--fullbody -o sample.inp`). It checks that the
character is drawn and framed, that opening the mouth and blinking each
change only a small area in the right place, and that the picture returns to
rest afterwards.

Those checks have passed puppets that looked wrong, so they are not evidence
of quality. For judging by eye, `tools/pose_sheet.py STAGE PUPPET OUT_DIR`
renders the head close up (using `--view`) and the whole figure in nine
poses (rest, turn, nod, tilt, blink, mouth open) into `sheet.png`, and a
sweep through turn, nod and tilt into `motion.gif`.
