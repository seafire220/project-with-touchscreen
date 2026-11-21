# Measurements

Numbers measured so far, where they were measured, and what is still to be
measured on the device. Measurements on this development machine (4 x86
cores, 16 GB) are not device numbers; a Raspberry Pi 4's cores are several
times slower.

## Measured here

| What | Result | Notes |
|---|---|---|
| Part-finding model, one picture | 32 s; 5.2 GB peak memory | CPU only. Why character making runs on a laptop (D-031) |
| Whole character maker, one picture | 82 s | Labels, background, cut, rig, refine, package; result 2.5 MB |
| On-device speech recognition (Moonshine tiny, 8-bit) | 6.6 s of speech in 0.24 s; 16.7 s in 0.53 s, 2 threads | Both test recordings recognised word for word, with punctuation |
| Speech model memory | 221 MB once loaded; 356 MB peak while recognising 16.7 s | Loaded once and kept (it was being reloaded for every utterance; fixed) |
| Core service memory, idle, without the speech model | about 50 MB | Python, aiohttp, numpy |
| Anthropic library | adds about 51 MB | Loaded only if Anthropic is chosen |
| Stage program size | 5.2 MB (PC), 4.7 MB (Pi build), with Ayagami | The Pi build needs only the C library; graphics libraries load at run time |
| Stage Pi build time | under 1 minute, cross-built on a PC | |
| On-device voice (Piper en_GB-vctk-medium, 109 speakers, through sherpa-onnx 2.x, phonemes from espeak-ng) | 13 times faster than real time with 2 threads on this PC (real-time factor 0.07-0.08; 0.11 with 1 thread); a sentence ready in 0.18-0.28 s; espeak-ng about 10 ms a sentence; about 150 MB once loaded, 220 MB at peak while speaking | A Pi's cores are several times slower, so expect roughly 0.3-0.6 with 2 threads: still ahead of speech, to be measured on the Pi. Survey: 72 of the 109 speakers read two hard test sentences with no word heard wrong by the device's own speech recognition (a second try allowed); the voice list offers those (`core/tools/voice_survey.py`) |
| Rejected voices | Kokoro (int8): only just real time on these PC cores, 428 MB. KittenTTS nano: fast, but sherpa-onnx 2.x drops words missing from its word list, and a third of words came back wrong. Piper LibriTTS-R medium (904 speakers, the first default: real-time factor 0.045, 108 MB): fine-tuned from Piper's lessac voice, whose recordings are licensed for research only (`34-licences.md`) | |
| Stage peak memory, 720x1280 window, software graphics | Synthetic test figure: 16 MB (Inochi2D), 22 MB (Live2D format). A test character from a picture: 22 MB (Inochi2D), 68 MB (Live2D format). Live2D's sample models: 13-57 MB | Before part pictures were packed into one texture page, the same test character took 158 MB in the Live2D format. The device's limit for the stage is 300 MB (`MemoryMax` in `companion-stage.service`) |
| Stage time per frame on the processor | Moving the character: 0.10-0.17 ms with Ayagami, 0.19-0.27 ms with Inox2D, for the same two characters. Handing the drawing to the graphics chip: about 0.4 ms for ours; 4-7 ms for sample models with many masks | Software graphics here, so the drawing figure is not the device's. Ayagami is not slower than Inox2D at moving a character. Models with many masks redraw each mask every frame; to watch on the Pi |
| Touchscreen edition overhead (`TouchEngine`, `FxRenderer`, `TouchUI`, `sounds.py`) | Idle core overhead: < 0.2 MB (10 cached synthesized PCM UI cues = 83 KB); idle pill GPU texture: ~0.04 MB; open dock/sheet GPU texture: ~1.9 MB; cached 1× dock base layer while dock is open: ~2.1 MB (released immediately on close, 2.6× faster slider drag renders); transient 2× Pillow render spike: ~8 MB | Zero new Python or Rust dependencies. Nightstand mode throttles stage redraws to ~12 fps and refreshes the clock overlay once every 30 s |

## Estimated memory budget on the 1 GB Pi

| Part | Estimate |
|---|---|
| Raspberry Pi OS Lite, cage, NetworkManager | 150–200 MB |
| Stage (character, textures in graphics memory, touchscreen FX + overlays) | 20–72 MB measured on a PC for our characters (above); to measure on the Pi |
| Core with on-device speech recognition (+ touchscreen UI & cached sound cues) | 220 MB idle, about 360 MB while recognising |
| On-device voice, in the core | about 110 MB loaded, up to about 230 MB while speaking |
| Anthropic library, if chosen | 50 MB |
| Total | about 630–1,045 MB with the on-device voice; tight on 1 GB, comfortable on 2 GB |

With the on-device voice it is tight on a 1 GB board. If it does not fit, the
first remedies are one thread for the voice, a cloud speech or voice service
(saving about 300 MB or 200 MB), or loading the speech model only while
listening; a 2 GB board has room for all of it. The touchscreen edition adds
under ~4 MB while a sheet is open and < 0.2 MB at rest.

## To measure on the device

Boot time; frame rate with a typical character; stage and core memory while
talking; on-device recognition time for a 3-second sentence; time from the
end of speech to the first sound, per provider; the sound output delay
that keeps the mouth in step (`OUTPUT_LATENCY`). Each is a test in
`15-hardware-test-plan.md`.
