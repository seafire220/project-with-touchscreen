# Requirements interview

Status: issued 2026-11-16, awaiting answers.

How to answer: reply with only the numbers you want to change. Anything skipped
takes the **default** shown and is recorded in the requirements specification
as an assumption that can be overturned later.

## A. Budget, priorities, your situation

1. **Budget (AUD), all-in** — board, display, audio, storage, power supply,
   cables, enclosure materials. Target and hard cap?
   Default: target ≤ $300, hard cap $400.
   (Reference: CODE27 is roughly A$780–920 before shipping and GST.)
2. **Tier**: cheapest workable / **best value (default)** / premium-but-inexpensive.
3. **Running costs**: acceptable monthly API spend — $0 (local only) /
   **up to ~$10–15 (default)** / don't care.
   Trade-off: cloud LLM/STT/TTS is what lets a ~$100 board feel fast. Fully
   offline conversation needs a much dearer device, or a PC on your network
   doing the heavy lifting.
4. **An always-on PC, server or GPU on your LAN** that could host local
   LLM/TTS/STT? Give CPU/GPU/RAM if so.
   Default: none; cloud-first, with LAN endpoints supported.
5. **You**: can you solder? Own a 3D printer? Happy to use Linux for initial
   setup only? AliExpress (2–4 weeks) acceptable, or Australian stock only?
   One unit for yourself, or several / might publish or sell the design?
   Default: basic soldering yes, no printer, AliExpress OK, one personal unit.

## B. Feature triage

| CODE27 feature | Provisional call |
|---|---|
| Custom VRM character with expressions, lip-sync, hair/cloth physics | Essential |
| Hands-free talk, tap-to-talk, interrupting the character mid-sentence | Essential |
| Persona / backstory / world-setting editor | Essential |
| Bring-your-own LLM and voice providers | Essential |
| Long-term memory with summarisation; diary | Desirable |
| Custom or cloned voice per character | Desirable |
| Idle animations, gestures, dancing to music | Desirable |
| Character "room" / backgrounds; RGB ambient lighting | Desirable |
| Proactive speech after silence | Desirable, off by default |
| Touch: pet the character; small second control screen | Desirable / Omit |
| Assistant skills: web search, weather, timers, smart home | Desirable |
| Camera: eye contact, face tracking, gesture and smile recognition | Omit, optional later |
| Motorised rotating base; battery; Bluetooth-speaker mode | Omit |

6. Corrections to the table? Anything CODE27 does that you want and isn't listed?

## C. Form factor and display

7. **Look**: (a) echo CODE27's cylinder/showcase silhouette;
   (b) **own design, functionally equivalent, e.g. a portrait monolith/frame (default)**;
   (c) don't care. Any maximum footprint or height? Where will it sit, and how
   far from you (arm's length on a desk, or across a room)?
8. **Depth effect** — the biggest look-versus-cost trade-off:
   (a) **plain bright portrait IPS panel plus software depth cues such as a
   parallax room and lighting (default)**;
   (b) Pepper's-ghost box: the panel is reflected in angled glass so the
   character floats in a dark chamber. Cheap in parts, but roughly doubles the
   bulk and wants a dimmer room;
   (c) transparent LCD showcase: closest to CODE27, but panels are costly,
   low-contrast and hard to source.
9. **Screen**: size 7–8" / **10.1" (default)** / 13"+; resolution
   **≥ 1200 × 1920 portrait (default)** or 800 × 1280 to save about $20–30;
   touch **yes (default)** / no; wide viewing angle (IPS) assumed; used in a
   bright room? 60 Hz acceptable?
10. **Render target**: **smooth 30 fps minimum, 60 preferred (default)**, or
    60 fps mandatory; toon outlines and hair/skirt physics on.
    This sets the GPU class, which is the main driver of board choice.
11. **Avatar modes**: **VRM 3D first with the renderer kept pluggable (default)**.
    Also want Live2D, 2D sprite, or video-loop characters in version 1?

## D. Characters

12. **Your VRM models** — for Alice Synthesis Thirty and any others: file size;
    VRM 0.x or 1.0; made in VRoid or Blender/Unity; triangle count and texture
    sizes if known; standard expressions only, or ARKit "perfect sync"
    blendshapes? Any `.vrma`, Mixamo or BVH animations you want to use?
    An armoured, long-haired model with 4K textures can be several times
    heavier than a stock VRoid export, so this drives GPU and RAM sizing.
13. **Other formats**: **VRM 0.x and 1.0 native, plain glTF/GLB best-effort,
    FBX/MMD via a documented convert-to-VRM path (default)** — or is native
    MMD/FBX needed?
14. **Character package**: one portable file (zip containing manifest, model,
    persona prompt, voice config, animation and expression maps, backgrounds).
    **API keys never inside; memories exported separately and only on request
    (default)**. Acceptable? May a package *recommend* an LLM/voice provider
    without carrying credentials?
15. **Transfer methods**, any of: **browser drag-and-drop over Wi-Fi (default)**,
    **USB stick auto-import (default)**, microSD, network share, device appears
    as a USB drive when plugged into a PC, cloud folder sync.
16. How many characters on the device, and how to switch: web UI / touch /
    voice? Default: 10 or more; all three.

## E. AI and voice

17. **LLM**: which providers do you use or want?
    Default: any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq, Ollama,
    LM Studio and so on) plus a native Anthropic adapter.
18. **TTS**: which providers or voices? Is a specific or cloned voice for a
    character a must?
    Default: plugin interface shipping with an OpenAI-compatible
    `/audio/speech` adapter, ElevenLabs streaming, a generic custom
    REST/WebSocket adapter, and a free on-device fallback voice.
19. **STT**: **cloud streaming with on-device fallback (default)** / on-device
    only / LAN server.
    Cloud is faster and more accurate but sends your speech out; on-device
    costs CPU and roughly 0.5–1.5 s.
20. **Activation**, any of: **wake word = the character's name**, **follow-up
    window (no wake word for a few seconds after a reply)**, **barge-in**,
    **physical push-to-talk / mute button**, touch-to-talk, fully open mic.
    Bold items are the default set.
21. **Languages**: English only (default)? Japanese or others? Mixed?
22. **Latency target**: default is that the character starts speaking within
    about 1.2 s of you finishing, on a good connection. Tighter?
23. **Speech-to-speech "realtime" models** (OpenAI Realtime, Gemini Live) as an
    optional mode? Lowest latency, but ties the voice to that provider's voices
    and costs more. Default: keep an interface for it; not in version 1.
24. **Memory and privacy**: long-term memory on (default)? Comfortable with an
    always-listening microphone if wake-word detection is entirely on-device?
    Hardware mic-mute switch (default yes)?
25. **Skills**: time/timers/alarms (default on), web search, weather,
    Home Assistant, camera "look at this"?

## F. Audio, peripherals, power

26. **Audio**: (a) **clear voice and passable music from a small stereo pair
    (default)**; (b) voice-only mono, cheapest; (c) properly good music
    speakers. Noisy room (TV or music nearby)? Headphone jack or Bluetooth
    output needed?
    Barge-in only works if echo cancellation is good. A mic module with
    hardware echo cancellation costs about $15–35 more than bare microphones
    and is the classic false-economy spot.
27. **Peripherals**, Essential / Desirable / Omit for each: camera; buttons
    (power, mute, volume); RGB LEDs; presence sensor (wake the screen when you
    approach); Ethernet; spare USB ports; Bluetooth.
    Default: buttons essential; LEDs and presence sensor desirable; camera and
    Ethernet omitted; at least one USB host port essential.
28. **Power**: **mains only (default)**, or battery — how many hours?
29. **Rank**: silence (fanless), boot speed, low idle power and heat,
    repairability, looks. Running 24/7, or switched on when used?
    Default: silent > looks > repairability > idle power > boot time; 24/7 with
    screen dimming.
30. **Enclosure**: prove electronics and software on the bench first, enclosure
    as stage 2 (default)? Preference: 3D-printed, laser-cut, or a modified
    off-the-shelf frame or case?

## G. Management and security

31. **Admin UI**: LAN-only web UI with a password, paired by QR code on the
    device screen; first-time Wi-Fi setup through a temporary hotspot
    (default). Need access from outside your home?
32. **Updates**: **manual update button in the web UI with automatic rollback
    on failure (default)**, or automatic.
33. Anything else: pet hates, must-haves, whether you have used a CODE27
    yourself, any deadline?

## Answers

Not yet received.
