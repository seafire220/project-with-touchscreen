# Third-party components and their licences

What the device and the character maker include or download, where it
comes from, and under which terms. Keep this list current when a component
is added; the device's settings page shows the short version ("About this
device").

## On the device

| Component | What it does | Licence | Where |
|---|---|---|---|
| Inox2D (Inochi2D runtime), vendored with changes | Plays Inochi2D puppets | BSD-2-Clause | `stage/vendor/inox2d*`, changes in `stage/vendor/PATCHES.md` |
| Ayagami core, vendored | Plays Live2D-format models (independent implementation; no Live2D software) | MIT or Apache-2.0 | `stage/vendor/ayagami`, commit in `stage/vendor/PATCHES.md` |
| sherpa-onnx | Runs the on-device speech recognition and voice | Apache-2.0 | Python package |
| Moonshine tiny, English, 8-bit (Useful Sensors), packaged for sherpa-onnx | On-device speech recognition | MIT | Downloaded at install (`device/install.sh`) |
| Piper voice "LibriTTS-R medium", packaged for sherpa-onnx | The free on-device voice (904 speakers) | CC BY 4.0: trained on LibriTTS-R (Y. Koizumi, H. Zen, S. Karita, Y. Ding, K. Yatabe, N. Morioka, M. Bacchiani, Y. Zhang, W. Han, A. Bapna, 2023), voice by the Piper project | Downloaded at install |
| espeak-ng | Turns text into phonemes for the voice | GPL-3.0; installed from the operating system's packages and run as a separate program | Operating system |
| Raspberry Pi OS and its packages (Linux, Mesa, cage, NetworkManager, ALSA...) | The operating system | Their own licences (mostly GPL, LGPL, MIT) | Operating system |
| aiohttp, numpy, Pillow, qrcode | The core service | Apache-2.0, BSD, HPND/MIT-CMU, BSD | Python packages |
| Anthropic Python library (only if Claude is chosen) | Talking to Claude | MIT | Python package |

## In the character maker (laptop)

| Component | What it does | Licence |
|---|---|---|
| See-through body-part model (`24yearsold/l2d_sam_iter2`) | Finds a character's parts | Apache-2.0 |
| image2live2d (pinned commit) | Rigs the parts; writes `.moc3` | Apache-2.0 |
| PyTorch, NumPy, SciPy, Pillow, rembg and their models | Image work | Their own licences (BSD, MIT, Apache-2.0) |

## Not included

Live2D's Cubism SDK, Cubism Core, Cubism Editor output and sample models are
not in the product or the repository (`docs/19-live2d-format-licensing.md`).
Test pictures of commercial characters are kept out as well (D-024).
