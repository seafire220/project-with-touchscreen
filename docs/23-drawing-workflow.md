# Drawing workflow: completing hidden areas, alternate poses and new views

Status: 2026-11-17. Desk assessment of every candidate in the owner's
research handoff (`live2d_automatic_rigging_research_handoff.md`, prepared
2026-11-18 with ChatGPT), with each project's repository and model records
read in this session. Nothing here has been run yet; the experiments at the
end come next (roadmap item 3). "Checked" means read in the project's own
files today; "reported" means taken from the handoff or a project's own
claims and not verified.

## What we need, and what we already have

The device plays a rig; it does not run image models. What the rig lacks is
artwork the picture never showed: what is behind the arms and hair, arms in
other poses, and the head from the side. Our pipeline today
(`14-making-characters.md`):

| Step | Ours | Measured |
|---|---|---|
| Find the parts | See-through's body-part model (`24yearsold/l2d_sam_iter2`, Apache-2.0), on the picture's own pixels | 32 s, 5.2 GB peak, CPU |
| Cut layers, fill hidden areas | `partsplit.py`: colour fills from nearby pixels, shadow tones for hair and neck behind the face | seconds, CPU |
| Rig | image2live2d's rigger (Apache-2.0) | seconds, CPU |
| Head and body turns | `refine.py` (Live2D-style rules, `20-head-turns.md`) | seconds, CPU |
| Live2D-format copy | `live2d_export.py`, writing with image2live2d's `.moc3` writer | seconds, CPU |

So the handoff's first priority, **Image2Live2D, is already in use** (our
rigger and `.moc3` writer). The missing capability is new artwork: hidden
areas that look drawn rather than smeared, arms in other poses, side views.

## The candidates

| Candidate | What it is (checked) | Licence, code / weights | Runs on | Use for us |
|---|---|---|---|---|
| **Image2Live2D** | Rigger from separated layers to `.inp`, `.moc3`, physics, motions | Apache-2.0 / none needed | CPU (measured, ours) | **In use** (pinned commit 714e7cc) |
| **PSD2Live** | Desktop rigging toolchain (bundled Java runtime): from a layered PSD it builds meshes, deformers, parameters, motions and physics, edited further in its editor; exports `.moc3`/`.cmo3` for Cubism 3.0 to 5.3, its own Rust runtime and other formats; releases for Windows, Linux (x86-64 and arm64) and macOS; very active (commit 2026-11-18) | App, its engine (Umamo) and Cubism/PSD exporters **GPL-3.0**; its rig format, export framework, other exporters and Rust runtime **MIT**. Its Linux build includes Live2D's Cubism Core for preview (`licenses/CubismSdkFor*`) | CPU, desktop (reported) | Run as a **separate program** on the same layers to compare its rigs with ours, and read its MIT rig format and runtime for ideas. Do not ship it or copy its GPL engine into our code; never ship the Cubism Core it bundles |
| **Bunraku** | Research (arXiv 2607.27348): splits an illustration into parts, completes hidden areas, then a small network (5.1 M parameters, reported) predicts meshes and key poses | Repository holds only a README (checked): **no code, weights or licence** | — | Watch for a release; read the paper's mesh and key-pose method |
| **Anime2.5DRig** and the **Auto-live2D-beta** fork | Browser tools: drop a parts-separated PSD and it is rigged and animated: meshes, deformation, physics, blink and mouth from template drawings (`eye_close.psd`, `mouth_close.psd`), pseudo-3D head turn by per-layer depth (parallax and shear), hair-strand detection for physics (up to six per layer), See-through PSDs accepted, OBS output, video export | MIT / — | Browser, CPU (reported) | Ideas, not a component: its hair-strand detection could feed our physics; our head turn already goes further (rounded head, per-part grids). No Live2D or Inochi2D export |
| **Iki** | 2D puppet engine for the web with a plain-text `.iki` format and an MCP server for AI agents, with `auto_rig_from_layers`, `compose_layers_from_parts`, `measure_layers`, `measure_turn_reference`, `render_poses`, `probe_rig` (all present in its code); offered as a Claude Code plugin; very active (commit 2026-11-17) | MIT / — | Browser and Node, CPU (reported) | Reference for agent-driven checking; its turn-reference measuring matches our plan to fit turns to generated side views. Its rigs would need an `.iki` → `.inp` converter |
| **See-through** (full pipeline) | Splits one picture into up to 23 transparent layers with hidden areas repainted, plus pseudo-depth, written as a PSD | Code Apache-2.0; LayerDiff 3D weights **OpenRAIL++-M** (fine-tuned from Animagine XL 4.0, also OpenRAIL++-M: commercial use allowed, with use restrictions passed on to users); depth model's record not readable (Marigold's own weights are OpenRAIL++-M) | NVIDIA GPU, 8 GB with 4-bit weights, 12-16 GB otherwise (reported); a free Hugging Face demo gives 1-2 runs a day | **The hidden-area completion we lack**, as an optional laptop step with a GPU or a hosted run; we already use its part labeller |
| **THA3** (Talking Head Anime 3, and the `tha3` package) | From one front-facing picture, renders the head turned, eyes, mouth, body turn and breathing by numbers; images, not a rig | Code MIT; weights **CC BY 4.0** (attribution required) | Recent NVIDIA GPU with CUDA (RTX 2080/3080 class, its README) | Reference poses to fit our turns against, or pre-drawn frames for the Lite tier; not a rigger |
| **Qwen Image Edit 2511 + Multiple Angles LoRA** | Image editing model; the LoRA turns the camera: 8 horizontal, 4 vertical angles, 3 distances (reported) | Base and LoRA **Apache-2.0** (checked). The newer **Qwen-Image-2.1** LoRA is Apache-2.0 but its base model is under Qwen's **research-only** licence: not for a product without permission | Large local GPU, or hosted (fal, about US$0.035 per megapixel, reported) | Side and three-quarter head views, as fitting targets and as the source of profile artwork for 90° turns |
| **Character 12-View** (Hugging Face space) | Twelve views and poses of a character in one sheet, built on Qwen Image Edit 2511 | Apache-2.0 (space) | Hosted | Prompt and layout reference for multi-view requests |
| **DiffPortrait360** | 360° head view synthesis from one portrait; checkpoints released | Code Apache-2.0 (README); no licence file in the repository | NVIDIA GPU, **30 GB minimum** for 32 frames, 48-80 GB recommended (its README) | Not now: far beyond a buyer's laptop; hosted only if 90° turns need it |
| **PAniC-3D** | 3D anime-head reconstruction (2023 research code, Docker with a GPU) | **No licence** in the repository (all rights reserved by default) | GPU | Not usable |
| **CharacterGen** | Multi-view images, then a 3D character (scripts around VRM and Blender) | Code Apache-2.0; weights' licence to check | GPU | Only if a 3D tier is ever added (`24-motion.md`, section 7) |
| **Rotate Your Character** | Project page with videos of characters turning | No code or weights found | — | Not usable now |

## Answers to the handoff's questions

**What duplicates ours, and what is new?** Image2Live2D is ours already.
PSD2Live, Anime2.5DRig and Iki each rig separated layers, as our rigger and
`refine.py` do; they may do individual things better (PSD2Live's simulation
baking, Anime2.5DRig's hair strands, Iki's checks) and are worth comparing
on the same layers. The new capability is artwork: See-through for hidden
areas; an image-editing model (Qwen 2511, or the buyer's image API) for arm
poses and side views; THA3 and the multi-view models as references.

**Which are usable commercially?** Clear: Image2Live2D, Anime2.5DRig, Iki,
THA3 (with attribution for its weights), Qwen 2511 and its LoRA,
See-through (OpenRAIL++-M use restrictions passed on), CharacterGen's code.
As a separate program only: PSD2Live (GPL-3.0; and it carries Live2D's
Cubism Core, which we must not ship). Not usable: Bunraku (unreleased),
PAniC-3D (no licence), Qwen-Image-2.1 (research licence), Rotate Your
Character (unavailable). DiffPortrait360's licence is stated only in its
README. Hosted APIs add their own terms, and the owner's or buyer's right to
use a picture is a separate question in every case.

**Can any produce our rig with no manual work?** Our own pipeline already
does, from one picture, on a CPU. None of the candidates produces better
moving artwork on its own; they produce layers (See-through) or images
(Qwen, THA3) that our pipeline must place, cut and rig. The smallest
adapters: See-through's PSD → our layer roles (its layer names map onto ours,
as Anime2.5DRig's import shows); a generated arm pose → segment it with our
part finder, register it at the shoulder, cut upper and lower arm, add it as
an alternate drawing switched by opacity under the arm parameters.

**What runs on a CPU or little memory?** Measured by us: our whole pipeline
on a CPU (82 s, 5.2 GB peak). Reported only: the riggers (CPU); everything
that generates artwork needs a GPU (8 GB and up) or a hosted service. None
of it runs on the device, and none needs to.

**Do our parameters, motions, physics and renderer still work?** Yes: all
new artwork enters as layers of the same rig with the standard parameter
names, so the stage, the converter and the motion work (`24-motion.md`)
are unchanged. Alternate drawings need opacity switching, which the
converter already carries into the Live2D format.

## Recommended method

1. **Hidden areas**: keep today's fills as the fallback; with a GPU of 8 GB
   or more (or a hosted run), use See-through's LayerDiff 3D for the layers
   behind the arms, hair and face, matched to our layer roles; with only the
   buyer's image-API key, inpaint each hidden area with the API using our
   masks.
2. **Arm poses**: ask an image-editing model (local Qwen 2511, or the
   buyer's image API) to redraw the whole character with one arm changed
   (waving, hand on hip, pointing, hands together), then segment, register
   and cut the new arm as above, and check its colours and outline against
   the original before accepting it. The buyer approves each drawing on a
   review page.
3. **Side views (for 90° turns)**: three-quarter and profile heads from Qwen
   2511 with the Multiple Angles LoRA, used as targets to fit the turn keys
   (the way Iki measures a turn reference) and as the source of the profile
   artwork (nose, lips, fill) that `20-head-turns.md` lists.
4. **References**: THA3 only if fitting needs exact angle-by-angle targets.

## Experiments next (item 3), with an original character only

The owner's own test pictures are commercial characters; image models will
be tried only on original artwork (a character made for the test, or the
commissioned default character), never asked to redraw an existing
character.

1. Make or obtain an original test character (front view, full body, flat
   colours).
2. With the owner's Gemini key: ask for an arm raised, a hand on the hip,
   both arms relaxed; a three-quarter and a profile head. **Blocked for
   now:** the key's project is on Google's free tier, which allows no image
   generation at all ("limit: 0" on every image model, checked 2026-11-17);
   billing must be enabled for the project in Google AI Studio (about
   US$0.04 per image with Gemini 2.5 Flash Image), or another image service's
   key supplied. Record cost, time,
   and how well style, colours and proportions hold (`reveal.py` and pose
   strips on the result).
3. Run See-through's demo (free Hugging Face account, 1-2 runs a day) on the
   same picture; compare its hidden areas with our fills.
4. Rig the same layers with PSD2Live, Anime2.5DRig and Iki; compare pose
   strips with ours and note what to borrow.

## Sources

Checked on 2026-11-17 (repositories cloned shallowly; Hugging Face records
read through its public API):

- https://github.com/Wzhang3912/image2live2d
- https://github.com/tsunehimatoi/psd2live (README licence table, `licenses/`)
- https://github.com/SparcAI-Inc/Bunraku; https://arxiv.org/abs/2607.27348; https://bunraku-live2d.github.io/
- https://github.com/852wa/Anime2.5DRig; https://github.com/lTwTlol/Auto-live2D-beta
- https://github.com/zeikar/iki
- https://github.com/shitagaki-lab/see-through; https://huggingface.co/layerdifforg/seethroughv0.0.2_layerdiff3d; https://huggingface.co/cagliostrolab/animagine-xl-4.0; https://huggingface.co/spaces/24yearsold/see-through-demo
- https://github.com/pkhungurn/talking-head-anime-3-demo; https://github.com/34j/tha3
- https://huggingface.co/Qwen/Qwen-Image-Edit-2511; https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA; https://huggingface.co/akhaliq/Qwen-Image-2.1-Multiple-Angles-LoRA; https://huggingface.co/Qwen/Qwen-Image-2.1; https://huggingface.co/spaces/r3lax/Qwen-Image-Edit-2511-Lora-Sheet
- https://github.com/FreedomGu/DiffPortrait360
- https://github.com/ShuhongChen/panic3d-anime-reconstruction
- https://github.com/zjp-shadow/CharacterGen
- https://rotateyourcharacter.github.io/
