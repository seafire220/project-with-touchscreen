# Hardware options and bill of materials

Status: revision 2, 2026-11-16, adding the boards the owner suggested.
Nothing has been bought or tested. Prices are a
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
| Radxa Zero 3W, 2 GB + 16 GB storage | US$43.95 (about A$68 before post); A$96.29 on Amazon AU | Ameridroid, Amazon AU |
| Radxa Zero 3W, 2 GB, no storage | US$63–75, mostly out of stock | ALLNET China, Amazon price tracker |
| Orange Pi Zero 3, 1 GB | US$58.59 (about A$90) | Newegg |
| Orange Pi Zero 3, 2 GB | US$66.48 (about A$102) | Newegg |
| Orange Pi Zero 3, 4 GB | US$73.13 (about A$113) | AliExpress |

One extra gigabyte costs A$44 on a Pi 4. The cheapest way to save money is
therefore to write software that fits in 1 GB, which is now a design
requirement (assumption A5).

On the owner's suggestions:

- **Orange Pi Zero 3.** It launched in 2023 at US$15–29, but the same memory
  shortage has pushed current listings to roughly US$40–90. The 4 GB model
  (about A$113) is now level with the Raspberry Pi 4 2 GB (A$109), not below
  it, and every Orange Pi Zero 3 variant found costs more than the Pi 4 1 GB.
- **Radxa Zero 3W, 2 GB.** Confirmed cheaper than a 2 GB Raspberry Pi
  (about A$68–96 against A$109), and the best of the non-Pi options: a
  faster processor and graphics chip than the Orange Pi Zero 3, with storage
  on the board.
- **Unbranded boards.** Cheaper still exist (generic Rockchip and Allwinner
  boards, TV-box mainboards), but they change revision without notice and
  rarely publish availability or test reports. They suit a production run
  with a supplier relationship, not a prototype or a first Kickstarter batch
  that has to be re-ordered identically.

Prices in this market are moving month to month; check the listing on the
day of purchase.

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
| Software | Python, Rust and web code; almost all of it can be run and tested without hardware | C++ firmware; cannot be run without the board |
| Shared code between tiers | One codebase | Separate firmware |

The microcontroller route roughly halves the cost of Lite and is the better
fit for the owner's priorities of boot speed and idle power. Its cost is a
second, harder-to-test codebase.

**Agreed strategy (owner, 2026-11-16):** Standard first, on Linux. Build both tiers on one Linux platform first, so the
product, character format and creation process are proven with one codebase.
Design the character package and the device's web API so they do not assume
Linux. Then port Lite to an ESP32-P4 board as a cost-reduction step, using
the open-source xiaozhi-esp32 firmware as a reference for audio, echo
cancellation and Wi-Fi setup. An ESP32-P4 board can be bought alongside the
prototype for about A$65–80 to judge the screen and audio quality early; this
is optional.

### What testing a microcontroller Lite needs

- **Compiling firmware** can probably be done in this cloud session;
  Espressif's toolchain and component servers are reachable from it. To be
  confirmed by doing it.
- **Running it** needs the physical board. No emulator covers the ESP32-P4's
  screen and audio (from memory).
- Ways to close the loop, in order of convenience:
  1. A Claude Code session running on the owner's laptop, with this
     repository open and the board plugged in by USB. It can build, flash
     and read the board's log directly.
  2. Firmware built here; the owner flashes it with one command or a
     browser-based flasher and sends back the log and a photo or short video.
     Slower, but needs only a USB cable.
  3. Attaching a laptop folder to this cloud session. No folders are
     currently offered to this session, and that feature is not available on
     every account.
- A graphics card is not needed for the microcontroller work. It is needed
  for See-through layer splitting in the Standard character pipeline.

## Boards considered for the Linux prototype

| Board | Verdict | Reason |
|---|---|---|
| **Raspberry Pi 4 Model B, 1 GB** | **Option 1: cheapest and lowest risk** | A$64.88 in Australian stock, the cheapest board found. Ribbon-cable screen, hardware video decoding, dependable hotspot mode, long production life, published compliance documents. Enough memory now that the character is drawn by a small native program. |
| **Radxa Zero 3W, 2 GB with 16 GB storage** | **Option 2: best non-Pi board** | About A$68–96. Twice the memory, on-board storage instead of a memory card, Wi-Fi 6. HDMI only, one USB host port (a small hub is needed), runs warm. Its Wi-Fi driver, hotspot mode and graphics under the chosen operating system all need proving on the board. |
| Orange Pi Zero 3 | Not recommended today | Dearer than the Radxa for a slower processor and graphics chip. Its Wi-Fi chip is reported to work as a hotspot but with driver errors, and HDMI needs patches carried by Armbian. Revisit if its price falls. |
| Raspberry Pi 5, 1 GB | Alternative | A$83.42. Much faster processor; needs a larger power supply and cooling. |
| Raspberry Pi 4/5, 2 GB | Rejected | A$44–50 for memory the software is designed not to need. |
| Raspberry Pi Zero 2 W | Deferred | Very cheap, but 512 MB, no display connector and hard to buy. A cost-reduction target once real memory use is measured. |
| Radxa ROCK 3C with Radxa's 8" ribbon-cable screen | Unpriced | Would give a non-Pi board a portrait touch screen on one ribbon and three USB ports. Current prices could not be confirmed (the screen was found at US$46.99–81.95). |
| Second-hand tablet | Rejected | Not repairable, supply changes monthly, boot behaviour cannot be controlled. |

**Decision (owner, 2026-11-16): Raspberry Pi 4 Model B, 1 GB.** If 1 GB
proves too tight, switch to a Radxa Zero 3W or an Orange Pi.

### Second search for cheaper boards

| Board | Memory | Price found | Comment |
|---|---|---|---|
| Raspberry Pi Zero 2 W | 512 MB | "just over €20" (Aug 2026); unaffected by the memory shortage | No ribbon display connector; only viable if the software fits in 512 MB |
| Orange Pi Zero 2W | 1–4 GB | US$18.90–41.99 across memory sizes at one reseller (Oct 2026); €53 for 1 GB on Amazon.de | Same chip as the Orange Pi Zero 3. The sources disagree by a factor of three |
| LCKFB TaishanPi (RK3566) | 2 GB + 16 GB | US$67.78–68.76 at LCSC | Not cheaper |
| Luckfox Core3566 module | 2 GB | US$55.99 | A module that needs a carrier board |
| Other RK3566 boards | 1 GB | Cheapest found US$139 | Not cheaper |

Nothing was found that is reliably cheaper than the Pi 4 1 GB (about US$42)
while having at least 1 GB and a graphics chip that supports OpenGL ES 3.
Two leads are worth following once the software's real memory use has been
measured on the Pi 4:

- The **Orange Pi Zero 2W 1 GB**, if the US$18.90 listing is genuine. Check
  the manufacturer's own AliExpress store on the day.
- The **Raspberry Pi Zero 2 W**, at about half the price of a Pi 4. The
  stage is now a 4.5 MB native program rather than a web browser, which
  makes fitting in 512 MB plausible, though unmeasured.

The software does not depend on the choice. It needs a Debian-based system,
any screen the display server can drive, and USB audio. Moving between these
boards is a matter of screen and Wi-Fi bring-up, not a rewrite.

## Expected load on a 1 GB board

Estimates, to be replaced by measurements on the real board.

| Part | Memory | Processor |
|---|---|---|
| Operating system and services | about 180 MB | negligible |
| Display server and native stage drawing a puppet, including its textures | about 100–200 MB | one core partly used, plus the graphics chip |
| Device service with speech-recognition model loaded | about 150–220 MB | up to one core while listening |
| **Total** | **about 430–600 MB** | two of four cores at peak |

Drawing the character with a native program instead of a web browser is
what brings this comfortably under 1 GB; a browser alone would add 200–500
MB. The sample puppet tested has 76 textures and about 5,400 triangles,
which is a light load for any of the candidate graphics chips. Actual frame
rate is unmeasured.

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

Optional, added 2026-11-20 (`33-finishing.md`):

| Part | Purpose | Qty | Cost | Source | Notes |
|---|---|---|---|---|---|
| Slide switch, SPDT, panel mount | A microphone mute switch you can see and feel | 1 | A$2 *est.* | Jaycar, AliExpress | GPIO27 to ground when "off" (`29-hardware-setup.md`); the screen shows the state either way |
| USB-C power and data splitter (for Pi 4 OTG) | Lets a computer connect by USB while the device keeps its own power | 1 | A$15 *est.* | The Pi Hut, AliExpress | Without it, the computer powers the device while connected (`28-user-guide.md`) |
| Industrial or high-endurance microSD card with power-loss protection, 16–32 GB | Instead of the A1 card, for production | 1 | A$15–35 *est.* | SanDisk Industrial, Kingston Industrial, Swissbit | The software protects the card already (read-only system); this adds a card that survives power cuts mid-write |

The extra A$31 buys echo cancellation that is known to work. Echo is the most
common reason home-built voice devices feel bad to use, so this is where a
small premium is justified. Buying the A$18 sound card as well allows a test
of software echo cancellation, which decides whether a production Lite can
use the cheaper part.

### R. Radxa alternative — about A$294

| Part | Purpose | Qty | Cost | Source | Notes |
|---|---|---|---|---|---|
| Radxa Zero 3W, 2 GB, 16 GB storage, header fitted | Computer | 1 | A$96.29 | Amazon AU | US$43.95 at Ameridroid before international post |
| 7" HDMI screen, 1024 × 600, capacitive touch (Waveshare 7inch HDMI LCD (H)) | Screen, mounted on its side for portrait | 1 | A$85 *est.* (US$47.99 + post) | Waveshare, AliExpress | Unbranded equivalents are cheaper |
| Micro-HDMI to HDMI cable | Video | 1 | A$8 *est.* | Any | |
| USB-C data hub | Extra USB ports | 1 | A$10 *est.* | Any | The board has one USB host port; audio and touch both need one |
| ReSpeaker Lite and 5 W speaker | Audio | 1 | A$55 *est.* | As in B | |
| microSD card, 32 GB | Development boots | 1 | A$12 *est.* | Any | Not needed once the on-board storage is flashed |
| USB-C power supply, 5 V 3 A, RCM marked | Power | 1 | A$17 *est.* | Any | The screen also needs 5 V |
| Buttons, heatsink | | | A$11 *est.* | Any | |

About A$55 more than B today. The board itself is cheap; the extra goes on
the HDMI screen, cable and hub that a board without a ribbon display
connector requires. It buys double the memory and on-board storage.

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
| R | A$294 | about 35% |
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
| ReSpeaker Lite as a plug-in USB audio device with its echo cancellation active | Medium; may need a firmware update | Hardware test |
| Pi 4 USB port powering the ReSpeaker Lite at full volume | Medium | Loud-playback test, watching for under-voltage warnings |
| On-device speech recognition speed on the Pi 4 | Medium | Timed test; fall back to the Pi 5 or a cloud service |
| Puppet frame rate on the chosen board | Unknown; expected good | Measure with the sample puppet |
| Radxa Zero 3W: Wi-Fi hotspot mode, graphics acceleration and screen rotation under Armbian or Radxa's own system | Unknown | Hardware test; setup over the USB cable is the fallback for Wi-Fi |
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

Not legal advice; a starting map from search summaries. The owner plans a
Kickstarter first and will deal with compliance after prototyping. The one
thing to keep doing meanwhile is to prefer parts that already carry radio
and EMC test reports, and an external mains adapter that is already marked.

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
- Radxa Zero 3W: https://ameridroid.com/products/radxa-zero-3w , https://www.amazon.com.au/Radxa-3W-2GB-16GB-GPIO/dp/B0CZD2NXQF , https://shop.allnetchina.cn/products/copy-of-radxa-zero-3w
- Orange Pi Zero 3: https://www.newegg.com/p/3D0-004Z-000C2 , https://www.aliexpress.com/item/1005005785846814.html , https://www.makeuseof.com/board-everyone-recommends-costs-60-what-buy-instead/ , https://www.cnx-software.com/2023/07/03/orange-pi-zero-3-allwinner-h618-sbc-ships-with-up-to-4gb-ram/
- Orange Pi Zero 3 software status: https://forum.armbian.com/topic/29202-orange-pi-zero-3/page/26/ and https://github.com/giltal/Retro-OrangePI-Zero-3
- Radxa Display 8 HD: https://shop.allnetchina.cn/products/radxa-display-8-hd
- Pi Zero 2 W and Orange Pi Zero 2W pricing: https://raspberry.tips/en/raspberrypi-tutorials/raspberry-pi-alternatives-sbc , https://raspberry.tips/en/raspberrypi-infos/raspberry-pi-zero-2-w-alternative-sold-out , https://spotpear.com/index/forum/detail/id/14816.html
- LCKFB TaishanPi: https://www.lcsc.com/product-detail/C19273641.html ; Luckfox Core3566: https://www.luckfox.com/EN-Core3566
- ESP32-P4 boards: https://www.atomic14.com/esp32/boards/displays/ , https://www.waveshare.com/product/esp32-related/boards-kits/esp32-p4.htm , https://shop.m5stack.com/products/m5stack-tab5-iot-development-kit-esp32-p4
- ReSpeaker Lite: https://www.seeedstudio.com/ReSpeaker-Lite-p-5928.html
- Waveshare USB sound card: https://www.waveshare.com/usb-to-audio.htm
- Waveshare 7" screens: https://www.waveshare.com/7inch-hdmi-lcd-h.htm and https://www.waveshare.com/7-dsi-touch-c.htm
- Compliance: https://www.accesscomms.com.au/product-compliance/ , https://www.compeng.com.au/c-tick-rcm-testing/australian-emc-labelling-requirements/ , https://www.spilma.com/en/guides/acma-rcm-australia-certification
