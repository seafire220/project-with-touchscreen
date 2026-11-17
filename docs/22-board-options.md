# Board options (single-board computers) for the Standard device

Status: 2026-11-17. Desk research; prices are web listings to re-check at
purchase. No board here has been tested yet (`15-hardware-test-plan.md`).

## What a board must have

| Need | Why | Minimum |
|---|---|---|
| A graphics chip with an open driver in Mesa giving OpenGL ES 3.0 or newer | The stage draws characters with OpenGL ES 3 (Inox2D, and the planned Ayagami path) | Raspberry Pi V3D, or Mali Bifrost/Valhall with Panfrost |
| Memory | Budget in `16-measurements.md`: about 520–810 MB in use with on-device speech recognition | 1 GB works; 2 GB gives room for Live2D-format characters and later work |
| Wi-Fi | Setup by phone, cloud AI services | Built in |
| Display and audio connections | Screen, speaker, microphone | DSI or HDMI; I2S or USB audio |
| Sold in Australia, or easy to import | Kickstarter production | — |

## Candidates

| Board | Chip and graphics | Memory | Graphics driver | Price seen | Fit |
|---|---|---|---|---|---|
| **Raspberry Pi 5 1GB** | BCM2712, VideoCore VII | 1 GB | V3D, OpenGL ES 3.1 | A$77.72–83.42 inc GST (Core Electronics) | **Recommended reference.** Faster than the Pi 4 for less than a Pi 4 2GB; same OS and our image tools. Needs a 5 V 5 A supply for full USB power; less for our load |
| Raspberry Pi 5 2GB | as above | 2 GB | as above | A$104.62 inc GST (one listing marked retired) | Headroom option |
| Raspberry Pi 4 2GB | BCM2711, VideoCore VI | 2 GB | V3D, OpenGL ES 3.1 | A$109.33 inc GST | Today's development target; now poorer value than the Pi 5 1GB |
| **Radxa Zero 3W** | RK3566, Mali-G52 | 1–8 GB | Panfrost, OpenGL ES 3.1, officially conformant on G52 | about US$15–26 for 1 GB (import; no Australian stock found) | **Cheapest board with a properly supported graphics chip.** Needs a Debian/Armbian image instead of Raspberry Pi OS: `device/build-image.sh` would need a variant |
| Orange Pi Zero 3 | Allwinner H618, Mali-G31 | 1–4 GB | Panfrost, OpenGL ES 3.1 (works; not formally conformant) | A$88 for 2 GB (Newegg AU, ships from Hong Kong) | Possible, but dearer here than a Pi 5 1GB |
| Orange Pi Zero 3W | Allwinner A733 | 1–16 GB | Not confirmed; check before buying | 25–60 by memory (currency not stated) | Too new to rely on |
| Raspberry Pi Zero 2 W | RP3A0, VideoCore IV | 512 MB | OpenGL ES 2.0 only | A$32.75 inc GST (with headers) | **Unsuitable**: no OpenGL ES 3, and too little memory |
| Pine64 Oz64 | Sophgo SG2000 (RISC-V/Arm) | 512 MB | No graphics chip | US$12.99 | **Unsuitable**: drawing on the processor alone would be far too slow, and 512 MB is too little |

## Recommendation

1. Buy a **Raspberry Pi 5 1GB** now as the reference board: everything we
   have built runs on Raspberry Pi OS, and it costs less than the Pi 4
   2GB we planned around.
2. Buy one **Radxa Zero 3W (2 GB)** to measure the cheapest credible
   option. If it holds 30 frames per second with a character and the
   speech model, it could take a lot off the unit cost, at the price of
   maintaining a second OS image.
3. Keep the Lite tier on the ESP32-P4 (pre-drawn frames), as planned.

## Sources

- Core Electronics, Raspberry Pi boards: https://core-electronics.com.au/raspberry-pi/boards.html,
  Pi 5 1GB: https://core-electronics.com.au/raspberry-pi-5-model-b-1gb.html,
  Pi 5 2GB: https://core-electronics.com.au/raspberry-pi-5-model-b-2gb.html
- Radxa Zero 3W: https://ameridroid.com/products/radxa-zero-3w,
  https://www.cnx-software.com/2023/12/08/radxa-zero-3w-sbc-rockchip-rk3566-8gb-ram-wifi6-raspberry-pi-zero-2-w-form-factor/
- Orange Pi Zero 3 (Newegg AU): https://www.newegg.com/global/au-en/p/3D0-0052-00059
- Orange Pi Zero 3W: https://www.cnx-software.com/2026/04/15/orange-pi-zero-3w-an-allwinner-a733-sbc-in-raspberry-pi-zero-form-factor/
- Panfrost conformance on Mali-G52: https://www.collabora.com/news-and-blog/news-and-events/panfrost-achieves-opengl-es-3.1-conformance-on-mali-g52.html
- Panfrost GPU support list: https://sources.debian.org/src/mesa/26.0.1-2/docs/drivers/panfrost.rst
- Pine64 Oz64: https://pine64.org/devices/oz64/
