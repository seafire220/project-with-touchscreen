# Requirements specification

Status: draft 2, 2026-11-16, derived from the owner's interview answers and
their review of the first design proposal.
Supersedes the 3D/VRM scope of the original brief.

## What is being built

A small mains-powered desk device that shows a 2D anime-style character on a
flat screen and holds a spoken conversation with the user. The user supplies
their own AI service keys. The device is built first as a prototype and is
intended to be published and sold.

Two tiers share one character system:

| Tier | Character animation | Cost goal |
|---|---|---|
| **Lite** | Pre-rendered 2D: short video loops or frame sets per state and emotion (idle, speaking-neutral, speaking-angry, and so on) | Cheapest workable |
| **Standard** | A rigged 2D puppet that moves continuously, in the style of Live2D but without Live2D Cubism. Uses the open Inochi2D format. Built first. | Still cheap, but able to run the puppet smoothly |

## Hard requirements

These came directly from the owner. A design that misses one is wrong.

| ID | Requirement |
|---|---|
| H1 | Two tiers as defined above. No VRM or other 3D. |
| H2 | Significantly cheaper than the CODE27 (about A$780–920 before shipping and GST). Lite prioritises lowest cost; Standard prioritises low cost while running the puppet well. |
| H3 | The design is intended for sale. Every software dependency, model and asset must permit commercial distribution. No Live2D Cubism. |
| H4 | The user supplies API keys. Keys are stored only on the device and never appear in character packages, exports, logs or the web UI after entry. |
| H5 | Several LLM back-ends selectable by the user. Several voice back-ends, including ones that offer custom or cloned voices. |
| H6 | A character can be created from user-supplied 2D art, ideally a single image, through an AI-assisted process provided with the device. For Standard this is a chain of tools (split into layers, mesh, rig, export) that may run on the user's laptop, with its requirements stated. A user without a suitable laptop uploads a hand-rigged model, but that alone does not meet this requirement: an ordinary, unfamiliar, full-body anime image must become an attractive, recognisable animated character. It must cope with most anime characters, not only simple designs, and is judged on independent artwork with failures kept. The customer tool is a local laptop program, including on an Apple Silicon Mac. |
| H7 | Characters can be added, switched and deleted without editing code. No fixed limit other than storage. |
| H8 | Conversation memory is stored on the device and the user can read and edit it. |
| H9 | Appliance behaviour: power on and the character appears. No login, desktop or manual program launch. The underlying computer is not exposed in normal use. Automatic recovery from crashes. |
| H10 | A physical button turns listening on and off. A fallback mode uses press-to-start and press-to-stop when automatic end-of-speech detection is unreliable. |
| H11 | Wi-Fi setup and routine management without a terminal, through a local web UI. Character upload over Wi-Fi. |
| H12 | Manual software updates, over Wi-Fi where possible or by connecting to a computer. |
| H13 | English at launch. Adding a language must be configuration, not a rewrite. |
| H14 | Voice-first audio. The character's custom voice must be clearly distinguishable. Mains powered. |
| H15 | No camera, RGB lighting or presence sensor. USB only for power and for debugging or file transfer. |
| H16 | Prototype sourcing and production sourcing are tracked separately. |

## Preferences

Ranked guidance. These can be traded against cost.

| ID | Preference |
|---|---|
| P1 | Low latency. Lower is better; streaming everywhere it is supported. |
| P2 | Priority order when qualities conflict: repairability, then boot speed, then low idle power, then looks, then heat. |
| P3 | Speech recognition on the device by default because it is free; cloud recognition where a free or cheap service is better. |
| P4 | Withdrawn. Ready-made speech-to-speech services cannot use a cloned voice. The streamed chain of recognition, LLM and cloned-voice service is the project's own equivalent. |
| P5 | Simple skills only: alarms, timers, web search, and whatever the user's LLM provider offers. |
| P6 | USB stick or microSD as secondary ways to load characters. |
| P7 | Battery power is a possible later option for Standard, only if cheap. |
| P8 | A flat enclosure that suits a 2D screen. 3D printed by the owner; not the current focus. |
| P9 | Other screen sizes later, as a scaling exercise. |

## Assumptions

Provisional choices made where the answers were open. Each can be overturned.

| ID | Assumption | Why |
|---|---|---|
| A1 | Portrait screen, 720 × 1280, 5" for the prototype. | The 5" and 7" versions of the same display share a resolution, so size can change later with no software change. |
| A2 | 30 frames per second is the floor; 60 where the hardware allows. | Anime-style animation reads well at 24–30. |
| A3 | ~~No wake word in version 1.~~ Superseded 2026-11-20: a wake word is an option (D-057); the button stays. | The owner asked for button activation first, then for the wake word (`33-finishing.md`). It was added without redesign, as expected. |
| A4 | The character can be interrupted by voice only when echo cancellation is present. Otherwise the button interrupts. | Without echo cancellation the device hears itself. |
| A5 | The software must fit in 1 GB of RAM. | Memory is the dominant cost in 2026 board prices. See the hardware document. |
| A6 | The seller runs no cloud service. Lite characters are generated from the device's web UI on the buyer's own AI keys. Standard characters are made with a tool chain on the buyer's laptop. | Avoids hosting cost, liability and an ongoing dependency on the seller. |
| A7 | The web UI is reachable only on the home network and is password protected. | Security default. |
| A8 | Long-term memory is on by default, per character. | Owner asked for it to be included. |
| A9 | Touch is optional. Nothing depends on it. | Keeps the cheapest screen options open. |
| A10 | One prototype is built first and runs the software for both tiers. | Halves the first parts order. |
| A11 | Compliance for sale is dealt with after prototyping. The first sales route is a Kickstarter. Until then, parts that already carry certification are preferred. | Owner's direction. |
| A12 | A microcontroller Lite is attempted after the Linux Standard works, with the owner providing access to the board through a laptop. | Owner's direction. |

## Out of scope

- 3D avatars, VRM, MMD.
- Camera features, gesture recognition, motorised base, ambient lighting.
- Music playback as a design driver.
- A vendor account system, character store or subscription.
- Enclosure design, until electronics and software work.

## Features carried over from the reference product

| Feature | Status |
|---|---|
| Custom character with expressions and lip movement | Required (2D instead of 3D) |
| Spoken conversation, interruptible | Required |
| Persona and backstory editing | Required |
| Bring-your-own LLM and voice | Required |
| Long-term memory, editable | Required |
| Custom or cloned voice | Required |
| Idle animation | Required |
| Backgrounds | Wanted |
| Timers, alarms, web search | Wanted, simple |
| Proactive speech after silence | Later, off by default |
| Touch interaction | Later, optional |
| Camera, rotating base, lighting, battery | Omitted |

## Matters the owner did not raise that affect the design

1. **Selling changes the rules.** A product sold in Australia needs the
   Regulatory Compliance Mark, an Australian supplier registration, and an
   approved mains adapter. This favours parts that already carry radio and
   EMC test reports. Detail is in the hardware document. This is not legal
   advice.
2. **Users will upload art they do not own.** The device should ship with only
   original characters, and the product terms should place responsibility for
   uploaded art and cloned voices on the user.
3. **Realtime speech-to-speech and custom voices pull in opposite
   directions.** Those services speak in their own built-in voices. Resolved:
   cloned voices win, and speech-to-speech services are not used.
4. **Single-image puppet rigging is the highest-risk part of the project.** It
   is at the edge of what current tools do. The plan stages it so the device is
   useful before that part is finished.
