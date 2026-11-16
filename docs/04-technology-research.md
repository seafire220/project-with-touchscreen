# Technology research

Status: revision 2, 2026-11-16. Living document. Section 1 was corrected
after building and running the Inochi2D code; see `07-spike-inochi2d.md`.

How each fact was checked is stated, because some hosts could not be read
directly from this session:

- **[Read]** — I read the project's README, licence file or package index
  entry directly.
- **[Search]** — taken from web search summaries; not read first-hand.
- **[Memory]** — from prior knowledge, not re-checked this session.
- **[Tested]** — built and run here.

## 1. Rigged 2D puppet engines (Standard tier)

| Option | Licence | Findings | Verdict |
|---|---|---|---|
| Live2D Cubism SDK | Proprietary | A device that loads arbitrary user models is an "Expandable Application". That class needs review and a paid agreement even for individuals and small businesses, with annual fees and a revenue share. [Search] | Rejected, as the owner already decided |
| Inochi2D official library | BSD-2-Clause [Read] | Being rewritten for 0.9 as a renderer-independent library with a C interface, WebAssembly build and TypeScript bindings. An August 2026 snapshot builds and loads a real model; the current source has not compiled since 3 October 2026. Latest release is still 0.8.7. [Tested] | Track; adopt when 0.9 is released |
| **Inox2D (Rust implementation of Inochi2D)** | BSD-2-Clause [Read] | Rendered a full rigged sample character correctly as a native program and, compiled to WebAssembly, in a browser. Two small defects found. Lacks mesh groups and animation playback; its README still calls it a prototype. [Tested] | **Chosen runtime**, pinned and patched |
| nijilive / nicxlive | BSD-2-Clause [Read] | A fork of Inochi2D 0.8. nicxlive is a C++ implementation "developing", said to work with OpenGL, Vulkan and WebGL. No stable builds of its editor. [Read] | Watch; not ready |
| Spine | Proprietary | Runtimes need a paid editor licence and rigs are authored in its editor. [Memory] | Rejected |
| Rive | Runtime open, editor proprietary | Files come from the Rive editor; no route for machine-generated rigs. [Memory] | Rejected |
| Talking Head Anime 4 | MIT code [Read] | Animates a single anime image, but needs a per-character model trained for "several ten hours" on a high-end GPU, and a powerful Nvidia GPU to run. [Read] | Rejected: impractical per character |
| Ayatsuri2D | Editor GPL-3.0; runtime MIT; C interface Apache-2.0 [Read] | A young open alternative to Live2D with its own format and the ability to read Live2D model files without the Live2D SDK. Beta. [Read] | Watch. Loading Live2D files in a sold product is a legal question to settle first |
| Own puppet format and runtime | Ours | Proposed in the first draft. | Withdrawn: Inochi2D works and already has an editor and models |

**Correction.** The first draft rejected Inochi2D because its README says
the reference renderer needs desktop OpenGL 3.1 and because the Rust port
calls itself a prototype. Both statements are true and neither is a reason
to reject it. The open graphics drivers for the Mali chips on Orange Pi and
Radxa boards provide desktop OpenGL 3.1 as well as OpenGL ES 3.1 [Search],
and the Rust port draws a real rigged character correctly when actually run
[Tested]. Inochi2D also brings what a home-made format never would: a free
rigging editor (Inochi Creator) and existing models, which gives users a
manual route when automatic rigging falls short.

## 2. Turning one image into a character

| Tool | What it does | Licence | Practical limits |
|---|---|---|---|
| See-through (SIGGRAPH 2026) | Splits one anime illustration into up to 23 inpainted, named layers (front hair, back hair, face, irises, eye whites, eyelashes, eyebrows, mouth, ears, neck, clothing items, tail, wings) with draw order, exported as a PSD | Apache-2.0 code [Read]; licences of its model weights not checked | Needs an 8–16 GB GPU, about 2–3 minutes per image. Does not rig: "rigging, deformation meshes, and physics" stay manual. Trained on commercial Live2D models, which is a provenance question for a commercial product. [Read] |
| Qwen-Image-Layered | Splits any image into a chosen number of transparent layers | Apache-2.0 [Read] | General purpose, not anime-part aware; needs a large GPU. [Read] |
| anime-segmentation (SkyTNT) | Cuts the character out from the background | Apache-2.0 [Read] | Light enough to run in a browser or on the device as a one-off job. |
| Image-to-video services | Turn a still into a short animated clip; most accept a first frame and an optional last frame | Commercial APIs | Roughly US$0.03–0.30 per second of video depending on model; quotes vary 2–5× between sources. [Search] |
| Image-editing models | Produce variants of the same picture (mouth open, eyes closed, angry) | Commercial APIs | Cents per image. [Memory] |
| Stretchy Studio | Browser tool that takes a See-through layered file, builds meshes, finds a skeleton by pose detection or simple rules, and animates on a timeline | MIT [Read] | Exports Spine and Live2D project files, not Inochi2D. Works by keyframed animation, not live parameters. Last commit April 2026. Useful as a source of mesh-generation and pose-detection code, and for rendering clips. [Read] |
| psd2live | Layered file to Live2D model with automatic rigging | GPL-3.0 [Search] | Live2D output only; reference for technique. |
| image2live2d | Named layers (a folder or layered file) to a full-body rig with blink, mouth, head turn, body sway, breathing and hair/cloth physics; writes an Inochi2D-family `.inp` | Apache-2.0 [Read] | Needs layers as input; calls See-through for flat images. Writes only plain nodes, parts and simple physics, which the stage supports [Read]. Not run here. Used in the owner's earlier attempt. |

Three character kinds follow from this, in rising cost and difficulty:

1. **Sprite** — a handful of still frames (mouth closed/half/open, blink,
   each emotion) swapped according to the speech volume. Made with an
   image-editing model for well under a dollar. Lip movement is properly in
   time with the voice. Runs on anything.
2. **Clips** — short video loops per state and emotion, as the owner
   described. Made with an image-to-video service, with the same picture
   given as first and last frame so every clip starts and ends on the same
   pose and clips can be cut together cleanly. A dozen four-second clips is
   roughly US$2–15 per character at the prices above.
3. **Puppet** — a rigged Inochi2D character, made one of two ways:
   - Automatically: the image is split into named layers, then an existing
     open-source rigger (image2live2d) builds meshes and the rig and writes
     an Inochi2D-family file. Splitting is the unsolved part.
   - By hand: rigged in Inochi Creator and uploaded.

Lite ships kinds 1 and 2. Standard adds kind 3.

## 3. Conversation pipeline

| Option | Licence | Findings | Verdict |
|---|---|---|---|
| Pipecat | BSD-2-Clause [Read] | Mature voice-agent framework with many providers. Requires Python 3.11+. Core install pulls in numpy, pydantic, the OpenAI SDK, onnxruntime, Pillow, protobuf and more. [Read] | Not adopted: too heavy for a 1 GB device and slow to start. Its design is a good model. |
| xiaozhi-esp32 | MIT [Read] | Voice chatbot firmware for ESP32 chips including ESP32-P4. Wake word, echo cancellation on capable boards, hotspot Wi-Fi setup, streaming and realtime modes. Depends on a companion server for the AI calls. [Read] | Reference and possible base for a later microcontroller Lite |
| Open-LLM-VTuber | — | Built around Live2D Cubism models. [Memory] | Not usable |
| **Own asyncio pipeline** | Ours | Small Python service with one adapter per protocol family rather than per vendor. | **Proposed** |

### Speech recognition

| Option | Cost | Findings |
|---|---|---|
| sherpa-onnx streaming models, on device | Free | Apache-2.0. Version 2.0.1 has ARM64 wheels for Python 3.13, which is what Debian 13 ships. [Read] Its documentation says all its models run in real time on a Raspberry Pi 4. [Search] No measured figures for our exact board yet. |
| Groq-hosted Whisper | Free tier | Reported limits: 2,000 requests and 28,800 audio seconds per day, each request counted as at least 10 seconds. No card needed. [Search] |
| Deepgram | US$200 starting credit, then paid | True streaming. [Search] |
| Any OpenAI-compatible transcription endpoint | Varies | One adapter covers OpenAI, Groq and self-hosted servers. |

Default: on-device, with cloud selectable per the owner's preference.

### Voices with cloning

| Provider | Notes |
|---|---|
| ElevenLabs | Widely rated best for cloning. Low-latency "Flash" models quoted at about 75 ms model latency. HTTP and WebSocket streaming. [Search] |
| Cartesia | Fastest reported time-to-first-audio (about 40–170 ms). WebSocket streaming. [Search] |
| Fish Audio | Cheapest of the group in the sources found (about US$15 per million bytes). Scored well on clone similarity in one review. [Search] |
| MiniMax | Cloning supported; pricing roughly US$50 per million characters in one source. [Search] |
| OpenAI-compatible speech endpoint | Covers OpenAI and many self-hosted voice servers. No user cloning on OpenAI itself. [Memory] |

Prices and latencies in this table come from comparison sites that disagree
with each other. They are good enough to choose which adapters to write first,
not to quote to customers.

### Speech-to-speech

OpenAI Realtime and Gemini Live both run over a WebSocket. Reported cost is
roughly US$0.02–0.10 per minute of two-way talk depending on model. [Search]
Neither was confirmed to accept a user's cloned voice. Decision: not used.
The streamed recognition → LLM → cloned-voice chain is the project's own
form of speech-to-speech.

## 4. Display software on the device

Checked directly against the Debian 13 (trixie) ARM64 package index [Read]:

| Package | Version | Role |
|---|---|---|
| cage | 0.2.0 | Minimal full-screen display server for kiosks |
| cog + WPE WebKit | 0.18.4 / 2.48.3 | Lightweight embedded browser, about 120 MB installed |
| chromium | 150 | Fallback browser, about 280 MB installed |
| plymouth | 24.004 | Boot splash |
| pipewire / wireplumber | 1.4.2 / 0.5.8 | Audio routing, includes an echo-cancel module |
| network-manager | 1.52.1 | Wi-Fi, including hotspot mode for setup |
| python3 / python3-aiohttp | 3.13.5 / 3.11.16 | Service runtime |
| ffmpeg | 7.1.5 | Clip conversion on import |

## 5. Licence summary for a product that will be sold

| Component | Licence | Obligation |
|---|---|---|
| sherpa-onnx, anime-segmentation, See-through code, Qwen-Image-Layered | Apache-2.0 | Keep notices |
| Inochi2D family, Pipecat | BSD-2-Clause | Keep notices |
| xiaozhi-esp32, Talking Head Anime 4 code | MIT | Keep notices |
| Linux, WebKit, PipeWire and other OS packages | GPL / LGPL / MIT mix | Offer source for GPL parts of the shipped image; a written offer in the manual is the usual route |
| AI model weights and speech models | Varies per model | Check each model before it is shipped on the device |

## Sources

- Live2D licence: https://www.live2d.com/en/sdk/license/ and https://www.live2d.com/en/sdk/license/expandable/
- Inochi2D: https://github.com/Inochi2D/inochi2d ; Inox2D: https://github.com/Inochi2D/inox2d ; example models: https://github.com/Inochi2D/example-models
- Stretchy Studio: https://github.com/MangoLion/stretchystudio and https://stretchy.studio/
- Ayatsuri2D: https://github.com/Yoru-KenomoVT/ayatsuri_2d
- psd2live: https://github.com/tsunehimatoi/psd2live
- image2live2d: https://github.com/Wzhang3912/image2live2d
- Mali driver capabilities: https://www.collabora.com/news-and-blog/blog/2021/01/13/desktop-opengl-3-1-on-mali-gpus-with-panfrost and https://sources.debian.org/src/mesa/26.0.1-2/docs/drivers/panfrost.rst
- nijilive: https://github.com/nijigenerate/nijilive ; nicxlive: https://github.com/nijigenerate/nicxlive
- See-through: https://github.com/shitagaki-lab/see-through and https://arxiv.org/abs/2602.03749
- Qwen-Image-Layered: https://github.com/QwenLM/Qwen-Image-Layered
- anime-segmentation: https://github.com/SkyTNT/anime-segmentation
- Talking Head Anime 4: https://github.com/pkhungurn/talking-head-anime-4-demo
- Pipecat: https://github.com/pipecat-ai/pipecat
- xiaozhi-esp32: https://github.com/78/xiaozhi-esp32
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx and https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html
- Image-to-video pricing: https://fal.ai/learn/tools/best-image-to-video-apis-2026 and https://www.teamday.ai/blog/best-ai-video-models-2026
- Voice comparison: https://www.speechmatics.com/company/articles-and-news/best-tts-apis-in-2025-top-12-text-to-speech-services-for-developers and https://diyai.io/ai-tools/audio-generation/best-voice-cloning-apis/
- Free speech recognition tiers: https://dev.to/unicodefawn/free-speech-to-text-and-text-to-speech-api-quotas-oct-2026-with-the-catches-17hg and https://www.eesel.ai/blog/groq-pricing
- Speech-to-speech: https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/speech-to-speech-realtime-api-gemini-live-seamless
