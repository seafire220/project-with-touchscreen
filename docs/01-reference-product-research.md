# Reference product research — SyBran CODE27

Status: first pass, 2026-11-16. Living document.

The reference product is the **CODE27 Character Livehouse**, now sold as the
**CODE27 Companion Hub** (model **SyBran-01**) by SyBran Innovation Co., Ltd.
"CODE Sybran" in the project brief is taken to mean this device.

## How this was gathered — read before trusting any line

Direct page fetches of the vendor site, manual mirrors and review sites were
blocked by this session's network policy, so everything below comes from web
search result summaries rather than first-hand reading of the pages. Each claim
is tagged:

- **[Official]** — attributed to the vendor's product/support pages, the user
  manual, the Kickstarter page/FAQ, or the FCC filing.
- **[Reported]** — press, reviewers, backers. Many are sponsored or affiliate
  pieces; treat performance claims with caution.
- **[Inferred]** — my engineering reading, not stated by any source.
- **[Unknown]** — looked for, not found.

Anything that later drives a design decision should be re-verified against the
primary page.

## Product timeline and price

| Item | Detail | Tag |
|---|---|---|
| First shown | CES, January 2025 | Reported |
| Kickstarter | 10 Apr – 25 May 2025; US$1,901,187 from 3,570 backers against a US$5,000 goal | Official |
| Japan pre-sale | Makuake from 13 Feb 2026; ¥82,800 early price, ¥99,800 planned retail | Reported |
| Shipping to backers | Began mid-2026 (185 units 29 Jul, 819 units 10 Aug per the 11 Aug 2026 update) | Official |
| FCC grant | FCC ID 2BTG5-SYBRAN, granted 12 Aug 2026 | Official |
| Current price | US$599 list, US$509 promotional (Nov 2026); earlier store prices of US$549/569 seen | Official |
| Approx. AUD | Roughly A$780–920 before shipping and GST, at an assumed ~0.65 USD/AUD (rate not checked today) | Inferred |
| Subscription | A cloud subscription exists: Kickstarter backers got a "lifetime cloud subscription", and "backer lifetime license codes" are resold on eBay. Price for non-backers not found | Official / Unknown |

## Hardware

| Area | Detail | Tag |
|---|---|---|
| Size / weight | 200 × 190 × 370 mm, ~2.6 kg; cylindrical showcase; black or white | Official |
| Main display | 10.1"; visible area 135.36 × 216.58 mm, i.e. portrait 16:10. Early coverage quoted 1920 × 1200 | Official / Reported |
| Display effect | Marketed as a "depth-effect, holographic-like display"; vendor states it is not a true volumetric hologram. Manual wording: "volumetric display system, custom skin-feel display module, custom optical module". Reviewers describe a transparent/transmissive panel, and complain about reflections | Official / Reported |
| Display optics | Either a transparent LCD in front of a lit chamber, or a beam-splitter (Pepper's ghost) arrangement. No teardown confirms which | Inferred |
| Second screen | 2.8" touch control panel, 43.8 × 58.2 mm (the two figures agree: that is a 2.87" diagonal) | Official |
| Camera | 120° diagonal wide-angle | Official |
| Microphones | Dual microphone with echo cancellation | Official |
| Speakers | "Stereo speaker system"; wattage not stated | Official / Unknown |
| Lighting | RGB ambient lighting, 255 brightness levels | Official |
| Wireless | Wi-Fi 2.4/5 GHz (not simultaneous, per FCC), Bluetooth 5.3 | Official |
| Ports | USB-C (power + data), microSD, 3.5 mm audio jack | Official |
| Power | USB-C PD 20 V / 2.25 A (45 W max); operating 10–45 W; no internal battery | Official |
| SoC / RAM / storage | Only "built-in AI chip, real-time rendering & edge AI processing". FCC internal photos and parts list are under short-term confidentiality | Unknown |
| Operating system | Not stated | Unknown |
| Accessory: Smart Rotating Base | Motorised base that turns the hub toward the user using face tracking; two manual buttons; 3000 mAh (22.2 Wh) battery giving ~2 h light use | Official |
| Accessory: Smart Light Panel | Voice-controlled, music-synced light panel (stretch-goal add-on) | Official |

The 10–45 W operating range and 2.6 kg mass suggest a mid-range ARM SoC plus a
power-hungry display/lighting stack rather than a tiny microcontroller-class
device. That is inference, not evidence.

## Software and behaviour

| Area | Detail | Tag |
|---|---|---|
| Characters ("Codies") | Upload a standard humanoid VRM from local files. FBX, PMX, PMD and glTF were "announced / in progress" as of software 1.5.0 (Aug 2026), so VRM is the only format that reliably works | Official |
| Avatar features | Full standard VRM expression set, automatic lip-sync on the five vowel shapes, spring-bone physics. ARKit 52 blendshapes still in progress. Lip-sync was rebuilt in a 2026 update | Official |
| Scene | Character has a "room", animations and emotional expressions; dances to music | Official / Reported |
| Persona | Personality, world setting and backstory are editable | Reported |
| Memory | About 10,000 turns per character, older content condensed to a summary; "stored memories" and "diary entries" exist as features | Reported / Official |
| Voice | Licensed voicebank library; voice cloning from a recording or audio file; English and Japanese only | Official / Reported |
| Talking to it | Tap-to-talk and a hands-free "ready-to-listen" mode; "full duplex" is claimed | Reported |
| Proactive behaviour | Can start a conversation after long silence | Official |
| Camera features | Recognises thumbs up, thumbs down, V-sign and smiles; face tracking drives the rotating base | Official |
| Touch | Character can be "petted"; second screen for controls | Reported |
| AI back-end | Marketed as configurable for ChatGPT, Gemini, (Claude in one article) and local models through a "model configuration tool". Several reviews say custom API and fully local operation were still "planned for a future update". Sources conflict | Official / Reported |
| Cloud dependence | Core real-time interaction needs internet and vendor cloud; a "preferred server" option was added to reduce response delay by region | Reported / Official |
| Setup | Pairing mode, activation codes, companion app. No PC needed for daily use | Official |
| Updates | OTA system reworked during 2026 | Official |
| Data | Memory and data for online and local models are stored on the device | Official |

## Reported weaknesses

These are the openings for a better device, not just a cheaper one.

- Response speed "not very fast"; struggles with long conversations.
- User and character lines sometimes get mixed up (role confusion in the dialogue).
- Bring-your-own LLM / fully local use promised but not clearly delivered.
- Activation codes, vendor cloud and a subscription sit between the owner and the device.
- Reflections on the transparent panel; large and heavy; mains only.
- Early firmware: restarts, freezes, Wi-Fi anomalies, camera recognition faults (fixes listed in vendor updates).
- Only English and Japanese; Japanese voice quality criticised.
- Only VRM import actually works; eyelid closure issue reported by one user converting a model.
- Price.

## Provisional feature matrix

Provisional until the requirements interview is answered; then it moves into
the requirements specification.

### Replicate

- Portrait ~10" display showing a full-body 3D character with a sense of presence.
- VRM avatar with expressions, vowel lip-sync, spring-bone physics, idle and gesture animation.
- Editable persona: personality, backstory, world setting.
- Hands-free conversation plus tap/push-to-talk.
- Per-character voice.
- Long-term memory with summarisation.
- Dual-mic capture with echo cancellation; stereo speakers.
- Touch interaction; ambient lighting; character "room"/background.
- Local character import with no PC required for daily use.

### Improve

- Any LLM, STT or TTS provider through provider-independent interfaces, using the owner's own keys. No vendor cloud, activation code or subscription.
- Latency: fully streamed STT → LLM → TTS with sentence-level speech start and real barge-in.
- Correct turn handling so the character never confuses who said what.
- Portable, documented character package format; add/remove characters without touching code.
- Web management UI on the local network instead of a companion app.
- Local/offline fallbacks where the hardware allows.
- Commodity, replaceable parts; open, reproducible software.
- Substantially lower cost.

### Omit (provisional)

- Motorised rotating base.
- Camera-based gesture and smile recognition (possibly an optional later add-on).
- Internal battery.
- Vendor character store, voicebank and other proprietary content.
- Smart Light Panel accessory.

### Unknown

- SoC, RAM, storage, operating system, rendering engine.
- Exact optical stack of the display.
- Microphone array geometry and where echo cancellation runs.
- Speaker drivers and amplifier power.
- Which STT/TTS/LLM services the vendor cloud uses by default, and its real latency.
- Subscription price and what stops working without it.

## Sources

Search-result summaries of:

- CODE27 product page — https://code27.com/products/code27 (also https://code27.co/products/code27)
- Companion Hub product support — https://code27.com/pages/companion-hub-product-support
- Smart Rotating Base — https://code27.com/products/smart-rotating-base and https://code27.com/pages/smart-rotating-base-product-support
- "Inside CODE27: The Technology to Bring Your VRM Character to Life" — https://code27.com/blogs/inside-code27/vrm-character-article
- CODE27 updates — https://code27.com/blogs/updates
- Kickstarter campaign, FAQ and updates — https://www.kickstarter.com/projects/1731190486/code-27-character-livehouse-bring-your-characters-to-life
- FCC filing 2BTG5-SYBRAN — https://fccid.co/fcc/2BTG5-SYBRAN
- User manual mirrors — https://device.report/manual/19782614 and https://manuals.plus/m/e2cd239cb56c0fe518c26f4387074381ba4e1681fe404cac372f3fe67e5f851a
- PC Gamer CES coverage — https://www.pcgamer.com/hardware/tiny-anime-girl-cyberprison-shown-at-ces/
- note.com owner review — https://note.com/uzumax_1976/n/n003525204582?hl=en
- mia-cat.com review round-up — https://mia-cat.com/en/pet-robot/code27-review/
- 4Gamer Makuake announcement — https://www.4gamer.net/games/999/G999902/20260212065/
- PHILE WEB — https://www.phileweb.com/sp/news/gadget/202603/06/5958.html
- Koikatsu-to-VRM conversion notes for CODE27 — https://note.com/firm_peony2134/n/n78c7bca88ec4?hl=en
- YouTube: final-version unboxing — https://www.youtube.com/watch?v=utIMbNrz0AY ; add-a-character and voice-clone tutorial — https://www.youtube.com/watch?v=Gi_b-WczC3o
- Third-party guide — https://poxgateselect.com/news/code27-companion-hub-a-desk-device-where-a-3d-character-lives-2026-guide
