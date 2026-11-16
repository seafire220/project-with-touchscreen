# Technology research

Status: 2026-11-16. Living document.

How each fact was checked is stated, because some hosts could not be read
directly from this session:

- **[Read]** — I read the project's README, licence file or package index
  entry directly.
- **[Search]** — taken from web search summaries; not read first-hand.
- **[Memory]** — from prior knowledge, not re-checked this session.

## 1. Rigged 2D puppet engines (Standard tier)

| Option | Licence | Findings | Verdict |
|---|---|---|---|
| Live2D Cubism SDK | Proprietary | A device that loads arbitrary user models is an "Expandable Application". That class needs review and a paid agreement even for individuals and small businesses, with annual fees and a revenue share. [Search] | Rejected, as the owner already decided |
| Inochi2D (reference SDK) | BSD-2-Clause [Read] | Written in D. The reference renderer needs a desktop OpenGL 3.1 context, not the OpenGL ES found on low-cost boards. States "at least 1 GB of RAM for bigger models". Has a WebAssembly build configuration. [Read] | Not usable as the runtime without porting work |
| Inox2D (Rust port of Inochi2D) | BSD-2-Clause [Read] | Renders through OpenGL and WebGL. Its own README says it is "in a prototype state" and "not recommended … in production". Animations and mesh groups are not implemented. [Read] | Too immature to build a product on |
| nijilive / nicxlive | BSD-2-Clause [Read] | A fork of Inochi2D 0.8. nicxlive is a C++ implementation "developing", said to work with OpenGL, Vulkan and WebGL. No stable builds of its editor. [Read] | Watch; not ready |
| Spine | Proprietary | Runtimes need a paid editor licence and rigs are authored in its editor. [Memory] | Rejected |
| Rive | Runtime open, editor proprietary | Files come from the Rive editor; no route for machine-generated rigs. [Memory] | Rejected |
| Talking Head Anime 4 | MIT code [Read] | Animates a single anime image, but needs a per-character model trained for "several ten hours" on a high-end GPU, and a powerful Nvidia GPU to run. [Read] | Rejected: impractical per character |
| **Own puppet format and WebGL runtime** | Ours | A small runtime that draws textured meshes and bends them with named parameters (head turn, blink, mouth, breathing, hair sway). Only needs the features our own rig generator emits. | **Proposed** |

Why the proposal is our own runtime and not Inochi2D: nobody publishes an
automatic rigger that targets Inochi2D, so the rig generator has to be written
here in any case, and the generator decides which runtime features are needed.
The only Inochi2D runtime that runs in WebGL calls itself a prototype.
Inochi2D's file format is open, so an importer for hand-made Inochi2D models
can be added later without depending on its runtime.

## 2. Turning one image into a character

| Tool | What it does | Licence | Practical limits |
|---|---|---|---|
| See-through (SIGGRAPH 2026) | Splits one anime illustration into up to 23 inpainted layers with draw order, exported as a PSD | Apache-2.0 code [Read]; licences of its model weights not checked | Needs an 8–16 GB GPU, about 2–3 minutes per image. Does not rig: "rigging, deformation meshes, and physics" stay manual. Trained on commercial Live2D models, which is a provenance question for a commercial product. [Read] |
| Qwen-Image-Layered | Splits any image into a chosen number of transparent layers | Apache-2.0 [Read] | General purpose, not anime-part aware; needs a large GPU. [Read] |
| anime-segmentation (SkyTNT) | Cuts the character out from the background | Apache-2.0 [Read] | Light enough to run in a browser or on the device as a one-off job. |
| Image-to-video services | Turn a still into a short animated clip; most accept a first frame and an optional last frame | Commercial APIs | Roughly US$0.03–0.30 per second of video depending on model; quotes vary 2–5× between sources. [Search] |
| Image-editing models | Produce variants of the same picture (mouth open, eyes closed, angry) | Commercial APIs | Cents per image. [Memory] |

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
3. **Puppet** — a rigged character.
   - Version 0: the single image is bent as one sheet. Face position, eyes
     and mouth are located automatically (with a vision model on the user's
     key) and can be corrected by dragging markers in the web UI. Gives
     breathing, sway, blinking, mouth movement and a few degrees of head turn.
     No layer splitting is needed, so it is robust.
   - Version 1: import a layered PSD, such as See-through output or an
     artist's file, and rig it from a template. Gives hair that swings
     separately and larger head turns.

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
Neither was confirmed to accept a user's cloned voice, so this mode uses the
provider's built-in voices.

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
- Inochi2D: https://github.com/Inochi2D/inochi2d ; Inox2D: https://github.com/Inochi2D/inox2d
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
