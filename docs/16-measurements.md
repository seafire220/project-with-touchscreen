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
| Stage peak memory, 720x1280 window, software graphics | Synthetic test figure: 16 MB (Inochi2D), 22 MB (Live2D format). A test character from a picture: 22 MB (Inochi2D), 68 MB (Live2D format). Live2D's sample models: 13-57 MB | Before part pictures were packed into one texture page, the same test character took 158 MB in the Live2D format. The device's limit for the stage is 300 MB (`MemoryMax` in `companion-stage.service`) |
| Stage time per frame on the processor | Moving the character: 0.10-0.17 ms with Ayagami, 0.19-0.27 ms with Inox2D, for the same two characters. Handing the drawing to the graphics chip: about 0.4 ms for ours; 4-7 ms for sample models with many masks | Software graphics here, so the drawing figure is not the device's. Ayagami is not slower than Inox2D at moving a character. Models with many masks redraw each mask every frame; to watch on the Pi |

## Estimated memory budget on the 1 GB Pi

| Part | Estimate |
|---|---|
| Raspberry Pi OS Lite, cage, NetworkManager | 150–200 MB |
| Stage (character, textures in graphics memory) | 20–70 MB measured on a PC for our characters (above); to measure on the Pi |
| Core with on-device speech recognition | 220 MB idle, about 360 MB while recognising |
| Anthropic library, if chosen | 50 MB |
| Total | about 520–810 MB |

It should fit, with little to spare. If it does not, the first remedies are
a cloud speech service (saves about 300 MB) or freeing the speech model
when listening is off.

## To measure on the device

Boot time; frame rate with a typical character; stage and core memory while
talking; on-device recognition time for a 3-second sentence; time from the
end of speech to the first sound, per provider; the sound output delay
that keeps the mouth in step (`OUTPUT_LATENCY`). Each is a test in
`15-hardware-test-plan.md`.
