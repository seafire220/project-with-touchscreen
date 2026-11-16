# Hardware options and bill of materials

Status: draft 1, 2026-11-16. Nothing has been bought or tested. Prices are a
snapshot; those marked *est.* are my estimates and were not found in a shop
listing. USD is converted at an assumed 0.65 USD per AUD.

## The market fact that shapes everything: memory

Board prices in 2026 are driven by a memory shortage. Raspberry Pi says its
memory cost rose sevenfold in a year, and the price gap between memory sizes
is now far larger than the gap between processors:

| Board | Price found | Source |
|---|---|---|
| Raspberry Pi 4 Model B, 1 GB | A$64.88 | Core Electronics |
| Raspberry Pi 4 Model B, 2 GB | A$109.33 | Core Electronics |
| Raspberry Pi 4 Model B, 4 GB | A$162.20 | Core Electronics |
| Raspberry Pi 5, 1 GB | A$83.42 | Core Electronics |
| Raspberry Pi 5, 2 GB | US$77.50 list (about A$130 *est.*) | Raspberry Pi announcement, Oct 2026 |
| Raspberry Pi Zero 2 W, 512 MB | US$15 list, reported scarce | Press |
| Radxa Zero 3W, 2 GB + 16 GB storage | US$43.95; A$96.29 on Amazon AU | Ameridroid, Amazon AU |

One extra gigabyte costs A$44 on a Pi 4. The cheapest way to save money is
therefore to write software that fits in 1 GB, which is now a design
requirement (assumption A5).

## Two kinds of platform

| | Linux single-board computer | Microcontroller display board (ESP32-P4) |
|---|---|---|
| Example | Raspberry Pi 4 + separate screen + audio board | Guition JC1060P470: processor, 7" touch screen, Wi-Fi 6 on one board |
| Cost for processor + screen | About A$145 | About A$55–70 (US$34–44) |
| Boot time | Roughly 15–25 s *est.* | About 2 s |
| Idle power | About 4–5 W with screen *est.* | Under 2 W *est.* |
| Lite character kinds (sprite, clips) | Yes | Yes, with clips stored as Motion-JPEG |
| Standard puppet | Yes, has a graphics processor | No graphics processor; not suitable |
| Speech recognition on the device | Yes | No; needs a cloud service |
| Software | Python and web code; I can run and test almost all of it here | C++ firmware; cannot be run or tested without the board |
| Shared code between tiers | One codebase | Separate firmware |

The microcontroller route roughly halves the cost of Lite and is the better
fit for the owner's priorities of boot speed and idle power. Its cost is a
second, harder-to-test codebase.

**Proposed strategy:** build both tiers on one Linux platform first, so the
product, character format and creation process are proven with one codebase.
Design the character package and the device's web API so they do not assume
Linux. Then port Lite to an ESP32-P4 board as a cost-reduction step, using
the open-source xiaozhi-esp32 firmware as a reference for audio, echo
cancellation and Wi-Fi setup. An ESP32-P4 board can be bought alongside the
prototype for about A$65–80 to judge the screen and audio quality early; this
is optional.

## Boards considered for the Linux prototype

| Board | Verdict | Reason |
|---|---|---|
| **Raspberry Pi 4 Model B, 1 GB** | **Chosen for the prototype** | Cheapest board with a display connector, hardware video decoding, dependable Wi-Fi hotspot mode, a first-party touch screen, long production life and published compliance documents. |
| Raspberry Pi 5, 1 GB | Alternative | Two to three times the processor speed for A$18.50 more, but needs a larger power supply and cooling, and has no hardware H.264 decoding. Take it if speech recognition proves slow on the Pi 4. |
| Raspberry Pi 4/5, 2 GB | Rejected for now | A$44–50 for memory the software is designed not to need. |
| Raspberry Pi Zero 2 W | Deferred | Very cheap, but 512 MB, no display connector and hard to buy. A cost-reduction target once real memory use is measured. |
| Radxa Zero 3W (RK3566) | Cost-reduction candidate | Similar capability and cheaper overseas, but HDMI only, and its Wi-Fi driver, hotspot mode and browser graphics would all need proving. More risk than a first prototype should carry. |
| Orange Pi Zero 2W class (Allwinner H618) | Not pursued | Current prices not found; weaker Wi-Fi driver support (from memory). |
| Second-hand tablet | Rejected | Cheapest of all, but not repairable, supply changes monthly, and boot behaviour cannot be controlled. Conflicts with the top priority and with selling. |

## Expected load on the Pi 4 (1 GB)

Estimates, to be replaced by measurements on the real board.

| Part | Memory | Processor |
|---|---|---|
| Operating system and services | about 180 MB | negligible |
| Display server and embedded browser showing the character | about 200–280 MB | one core partly used, plus the graphics processor |
| Device service with speech-recognition model loaded | about 150–220 MB | up to one core while listening |
| **Total** | **about 550–700 MB** | two of four cores at peak |

The likely bottleneck is memory, not processing. The standard Chromium
browser alone would use 400–500 MB, which is why the lighter WPE browser is
the default. Compressed swap (zram) is enabled as a safety margin.

## Configurations

### A. Minimum-cost Linux prototype — about A$208

| Part | Purpose | Qty | Cost | Source | Notes |
|---|---|---|---|---|---|
| Raspberry Pi 4 Model B 1 GB | Computer | 1 | A$64.88 | Core Electronics | |
| Raspberry Pi Touch Display 2, 5" | 720 × 1280 portrait touch screen | 1 | A$78.79 | Core Electronics | Powered from the Pi; cables included (to confirm on arrival) |
| Waveshare USB sound card, SKU 18833 | Microphone and speaker output | 1 | A$18 *est.* (US$7.99 + post) | Waveshare, AliExpress | No echo cancellation in hardware |
| Small speaker, 8 Ω 2–3 W | Voice | 1 | A$6 *est.* | AliExpress, Jaycar | May be bundled with the sound card |
| microSD card, 32 GB, A1 rated | Storage | 1 | A$12 *est.* | Any | Name-brand only |
| USB-C power supply, 5 V 3 A, RCM marked | Power | 1 | A$17 *est.* | Core Electronics | |
| Momentary push buttons with leads | Listen, power | 2 | A$6 *est.* | Jaycar, AliExpress | |
| Stick-on heatsinks | Cooling | 1 set | A$5 *est.* | Any | Fanless |

### B. Best value — recommended — about A$239

Configuration A with the sound card and speaker replaced by:

| Part | Purpose | Qty | Cost | Source | Notes |
|---|---|---|---|---|---|
| Seeed ReSpeaker Lite | Two microphones with echo cancellation, noise suppression and gain control done on the board; 5 W speaker amplifier; USB | 1 | A$46 *est.* (US$24.90 + post) | Seeed, Core Electronics, Pakronics | Lets the user talk over the character |
| Speaker, 4 Ω 5 W, about 50 mm | Voice | 1 | A$9 *est.* | AliExpress, Jaycar | Connector to match the board |

The extra A$31 buys echo cancellation that is known to work. Echo is the most
common reason home-built voice devices feel bad to use, so this is where a
small premium is justified. Buying the A$18 sound card as well allows a test
of software echo cancellation, which decides whether a production Lite can
use the cheaper part.

### C. Premium but still inexpensive — about A$342

| Part | Cost |
|---|---|
| Raspberry Pi 5, 2 GB | A$130 *est.* |
| Raspberry Pi Touch Display 2, 7" (same 720 × 1280) | A$105.69 (Core Electronics) |
| ReSpeaker Lite and 5 W speaker | A$55 *est.* |
| 27 W USB-C power supply | A$24 *est.* |
| Active cooler | A$9 *est.* |
| microSD and buttons | A$18 *est.* |

Larger screen, much faster processor and more memory headroom. No software
change from A or B, because both screen sizes have the same resolution.

### D. Microcontroller Lite candidate, for evaluation — about A$95–105

| Part | Cost |
|---|---|
| Guition JC1060P470 (7", 1024 × 600) or JC8012P4A1 (10.1") ESP32-P4 board | A$65–78 *est.* (US$34–44 + post) |
| Speaker, power supply, microSD | A$28 *est.* |

Whether these boards carry a microphone and speaker amplifier on board was
not confirmed.

### Cost against the reference

| | Cost | Share of CODE27 (about A$850) |
|---|---|---|
| A | A$208 | about 24% |
| B | A$239 | about 28% |
| C | A$342 | about 40% |
| D | about A$100 | about 12% |

The biggest cost drivers in A and B are the screen (33–38%) and the computer
(27–31%). The cheapest lever after the software's memory use is the screen:
unbranded 5" display-connector panels are roughly A$35–45, at lower
resolution and with unverified driver support.

## Connection plan for configuration B

No soldering is needed if the buttons come with push-on leads.

| From | To | Cable |
|---|---|---|
| Touch Display 2 | Pi display connector | Flat cable supplied with the display |
| Touch Display 2 power lead | Pi header 5 V (pin 2 or 4) and ground (pin 6) | Supplied lead |
| ReSpeaker Lite USB-C | Pi USB 2.0 port | USB-C to USB-A cable |
| Speaker | ReSpeaker Lite speaker connector | Speaker lead |
| Listen button | Pi header GPIO17 (pin 11) and ground (pin 9) | Two leads |
| Power button | Pi header GPIO3 (pin 5) and ground (pin 14) | Two leads; this pin both shuts down and wakes the Pi |
| Power supply | Pi USB-C | — |

## Compatibility not yet confirmed

| Item | Confidence | How it gets confirmed |
|---|---|---|
| Pi 4 with Touch Display 2 | High; a first-party pairing | First power-on |
| WPE browser drawing WebGL and video smoothly on the Pi 4 | Medium | Hardware test; Chromium is the fallback |
| ReSpeaker Lite as a plug-in USB audio device with its echo cancellation active | Medium; may need a firmware update | Hardware test |
| Pi 4 USB port powering the ReSpeaker Lite at full volume | Medium | Loud-playback test, watching for under-voltage warnings |
| On-device speech recognition speed on the Pi 4 | Medium | Timed test; fall back to the Pi 5 or a cloud service |
| Boot time to character | Unknown | Measure, then trim services |
| Microphone and amplifier on the ESP32-P4 boards | Unknown | Seller documentation |

## Production sourcing

Kept separate from the prototype list, as requested. None of this is quoted
pricing.

| Volume | Approach |
|---|---|
| 1–10 | Retail parts as listed. |
| 10–100 | Same parts at volume pricing (Core Electronics lists a 50+ price for the Pi 4; Waveshare and Seeed publish quantity breaks). Screens and speakers direct from manufacturers. |
| 100+ | Lite on an ESP32-P4 display board bought in volume. Standard on a compute module or Rockchip module with a small custom board carrying the audio parts and buttons, which cuts assembly labour and cabling. A custom board needs its own EMC testing. |

## Selling in Australia

Not legal advice; a starting map from search summaries.

- Products with radio or mains connection need the Regulatory Compliance
  Mark. Radio and EMC fall under ACMA; electrical safety under the state-based
  EESS scheme.
- The supplier must be an Australian entity registered on the national
  database. Registration for the ACMA side is reported as free.
- The likely EMC standard is AS/NZS CISPR 32.
- Shipping an external mains adapter that already carries the mark keeps the
  device itself at 5 V and narrows the electrical-safety question.
- A board whose radio already has test reports helps, but sources say the
  finished product must still be assessed in its own right.
- Compliance records are kept for at least five years.
- Test-lab cost has not been researched. Speak to an accredited lab before
  the first sale.

## Sources

- Raspberry Pi price changes: https://www.raspberrypi.com/news/a-new-3gb-raspberry-pi-4-for-83-75-and-more-memory-driven-price-increases/ and https://www.theregister.com/2026/02/02/raspberry_pi_ram_shortage_price_hike/
- SBC prices 2024 vs 2026: https://www.cnx-software.com/2026/04/28/what-a-difference-two-years-make-comparing-sbc-prices-in-2024-and-2026/
- Core Electronics: https://core-electronics.com.au/raspberry-pi-4-model-b-1gb.html , https://core-electronics.com.au/raspberry-pi-4-model-b-2gb.html , https://core-electronics.com.au/raspberry-pi-5-model-b-1gb.html , https://core-electronics.com.au/raspberry-pi-touch-2-display-5-inch.html , https://core-electronics.com.au/raspberry-pi-touch-display-2.html
- Radxa Zero 3W: https://ameridroid.com/products/radxa-zero-3w and https://www.amazon.com.au/Radxa-3W-2GB-16GB-GPIO/dp/B0CZD2NXQF
- ESP32-P4 boards: https://www.atomic14.com/esp32/boards/displays/ , https://www.waveshare.com/product/esp32-related/boards-kits/esp32-p4.htm , https://shop.m5stack.com/products/m5stack-tab5-iot-development-kit-esp32-p4
- ReSpeaker Lite: https://www.seeedstudio.com/ReSpeaker-Lite-p-5928.html
- Waveshare USB sound card: https://www.waveshare.com/usb-to-audio.htm
- Waveshare 7" screens: https://www.waveshare.com/7inch-hdmi-lcd-h.htm and https://www.waveshare.com/7-dsi-touch-c.htm
- Compliance: https://www.accesscomms.com.au/product-compliance/ , https://www.compeng.com.au/c-tick-rcm-testing/australian-emc-labelling-requirements/ , https://www.spilma.com/en/guides/acma-rcm-australia-certification
