# stage

The program that draws the character on the device's own screen.

It loads an Inochi2D puppet (`.inp` or `.inx`), keeps it alive with
breathing, blinking and small head and body movement, and moves its mouth and
changes its manner on command from the core service. It holds no API keys and
makes no network connections.

Status: works on a virtual display with software graphics, in both OpenGL ES
and desktop OpenGL modes. **Not yet run on a Raspberry Pi or any real
graphics chip**, so its frame rate there is unknown.

## Build

```
cargo build --release
```

Needs Rust (tested with 1.97). The Inox2D renderer is kept in `vendor/` with
our changes listed in `vendor/PATCHES.md`; nothing but ordinary crates is
fetched at build time.

## Run

```
target/release/stage character.inp --fullscreen
target/release/stage character.inp --size 720x1280 --socket /run/stage.sock
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
| `{"quit": true}` | Exit. |

Several fields can share one line.

## Events

One JSON object per line, on standard output and to socket clients:

| Event | Meaning |
|---|---|
| `ready` | Puppet loaded. Lists which controls were connected to which puppet parameters, and the OpenGL version in use. |
| `state` | The state changed. |
| `heartbeat` | Once a second, with frames per second. The supervisor restarts the stage if these stop. |
| `error` | A command was not understood. |
| `fatal` | The stage cannot run; it exits with a non-zero status. |

## Puppets it accepts

Any Inochi2D puppet whose nodes are plain nodes, parts, composites and simple
physics. Files using other node types (for example mesh groups) are refused
with a clear message rather than shown half-working.

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
cargo test --release                       # logic: 18 tests
python3 tools/visual_test.py target/release/stage PUPPET.inp out/ --gl es
```

The visual test needs `Xvfb`, Pillow and a rigged puppet with conventional
parameter names. It passes with a hand-rigged model (the "Aka" example from
`Inochi2D/example-models`, by seagetch, CC BY 4.0, distributed through Git
LFS and not stored here) and with puppets produced by the image2live2d
rigger, including its built-in sample (`python -m image2live2d --sample
--fullbody -o sample.inp`). It checks that the
character is drawn and framed, that opening the mouth and blinking each
change only a small area in the right place, and that the picture returns to
rest afterwards.
