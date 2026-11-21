# Hardware test plan and troubleshooting

For the first build of the prototype (Raspberry Pi 4, 1 GB, Touch Display
2, ReSpeaker Lite). Each test has a pass mark. Record results, including
failures, in a copy of this table, and add them to the decision log when
they change a decision.

## Bring-up

| # | Test | How | Pass |
|---|---|---|---|
| 1 | Power and display | Power on with the installed card | Screen shows the setup card within 40 s; no under-voltage warning in `journalctl -k` |
| 2 | Boot time | Stopwatch from power to the setup card or character | Record it; target under 30 s |
| 3 | Wi-Fi setup | Follow the setup card from a phone | Joins home Wi-Fi; address shown on screen |
| 4 | Console | Open the address on a phone and a laptop | Password set; all tabs load |
| 5 | Listen button | Press it with no character speaking | Console shows "listen on"; second press "listen off" |
| 6 | Power button | Press while running; press again | Clean shutdown (no SD errors next boot); starts again |
| 6a | Setup reset | Hold the listen button for 12 s | Setup screens return; characters kept |
| 7 | Sound out | AI services → Voice → Test | Clear voice, no crackle at 80% volume |
| 8 | Sound in | Talk with listening on; watch "What is happening" | Your words appear correctly in a quiet room |

## The character

| # | Test | How | Pass |
|---|---|---|---|
| 9 | Frame rate | `journalctl -u companion-stage -f` shows heartbeats with `fps` | 30 or more with a typical character |
| 10 | Memory | `free -m` and `systemctl status companion-core companion-stage` while talking | No swapping; core under 300 MB, stage under 200 MB |
| 11 | Look | Watch idle, blink, speech and head movement for 2 minutes | No smears, gaps or flicker; mouth moves with the voice |
| 12 | Switching characters | Add a second character and switch | New character on screen within 5 s |

## Conversation

| # | Test | How | Pass |
|---|---|---|---|
| 13 | Latency | Time from the end of your sentence to the first sound | Record per provider; target under 2 s |
| 14 | Interrupt | Press the button while it speaks | Sound stops within 0.3 s |
| 15 | Long reply | Ask for a story | Speech continues without gaps between sentences |
| 16 | Timer | "Set a timer for one minute" | It confirms, and announces the timer after a minute |
| 17 | Memory | Tell it a fact and a plan with a date ("my sister Kim visits on Saturday"), say goodbye, wait four minutes, check Memory; talk again the day after the date | The conversation is summed up and both are kept (the plan with its date); edits there are used; the day after, it asks how the plan went (`31-memory.md`) |
| 17b | A model on your own computer | Run Ollama on a laptop on the same Wi-Fi (`OLLAMA_HOST=0.0.0.0`), then **AI services → My own computer → Find on my network**, choose a model, **Save and test**; talk | Found without typing an address; replies within its usual time (the first after a pause is slower); the Memory tab fills as with a cloud model |
| 18 | Failure | Remove the language model key, then talk | A short tone and a clear message in the console; no hang |
| 19 | Restart recovery | `sudo systemctl kill companion-stage`, then the core | Both come back within 5 s |
| 20 | Echo | Turn listening on and let it speak loudly | It does not answer itself (the microphone is ignored while it speaks) |

## Added on 2026-11-20

| # | Test | How | Pass |
|---|---|---|---|
| 21 | Power cuts | With an image built with power-cut protection: pull the plug 50 times, at random moments, ten of them while it saves (just after a reply, or while adding a character) | It always starts; the character, memories and settings are there (the last few seconds' change may be lost); `journalctl -b -u companion-data-check` shows repairs if any; `mount` shows `/` read-only |
| 22 | First start of a new card | Flash a fresh image to a 32 GB card and start it | `df -h /data` shows the data partition grown to fill the card; second start is no slower |
| 23 | Updates on a read-only system | Install an update file (Device → Software) | It installs and restarts; `mount` shows `/` read-only again after |
| 24 | Wake word | Turn it on; say "hello" and the name 20 times from 1 m and 3 m, with the TV off and on; then talk normally near it for an hour | Heard at least 17 of 20 from 1 m; it starts by mistake at most once in the hour. Try *less* and *more*; record the name |
| 25 | Wake word, one breath | "Hey NAME, what time is it?" | It answers the question without a second step |
| 26 | Captions | Turn captions on; read them from 2 m and 3 m, in both sizes | Readable from where people sit |
| 27 | Microphone off | Hold the button 2 s; check `pgrep -a arecord` | The sign shows, `arecord` is not running, a press says the microphone is off; 2 s again turns it on |
| 28 | Mute switch | Fit the switch (`29-hardware-setup.md`); slide it both ways, also while the device starts | The sign follows the switch, from the start too |
| 29 | Screen at night | Set the hours to include now; wait two minutes; press the button | The screen goes dark (backlight off: `cat /sys/class/backlight/*/bl_power` shows 4); the button lights it. Record whether the Touch Display 2 has a backlight Linux can set |
| 30 | USB connection | Connect a Windows 11 laptop, a Mac and a Linux PC in turn to the USB-C port, without the power supply; open http://10.12.194.1 | The page opens with no driver to install; the computer's internet still works; the device stays up on the computer's power while it talks |
| 31 | Family-safe mode | Turn it on; ask for a rude joke, and something frightening | Polite refusals that change the subject; turning it off asks for the password |
| 32 | A Live2D model's own idle motions | Add a model that has idle motions (most bought ones do); watch it five minutes, then talk to it; switch *Its own idle motions* between as made, gentler and off | Its artist's motions play and change smoothly; looking at you, nods and gestures still show on top; the frame rate in the heartbeat stays as with them off |
| 33 | 3D head turns | With a VRM avatar, ask it to look back over its shoulder; leave it alone ten minutes | The head reaches a profile with the shoulders following, and comes back smoothly; now and then it looks over its shoulder by itself |

## Touchscreen edition bring-up (Touch Display 2)

Run these checks on units fitted with the Raspberry Pi Touch Display 2 (5" or 7", 720×1280 portrait):

| # | Test | How | Pass |
|---|---|---|---|
| 34 | Touch alignment & rotation | Open **Moods & Care → Setup Wizard → Step 2**; tap all 4 corners and the calibration target box; if coordinates are rotated relative to the display, pick `90°`/`180°`/`270°` and re-tap | Sparkles and cyan target dot land directly under the fingertip at all corners and center; setting survives a reboot |
| 35 | Tactile character interaction | Stroke back and forth across head (headpat), rub cheek, double-tap body, and glide finger around screen | Immediate 60 fps headpat/cheek-rub/poke motion, floating hearts/sparkles, smooth eye tracking; heartbeat `fps` stays ≥ 30 |
| 36 | Multi-touch gestures | On a 3D VRM avatar, pinch in and out with two fingers; with 2+ characters installed, swipe horizontally with two fingers | Pinch switches `bust ↔ upper ↔ full` live with no stage restart; two-finger swipe switches to the next/previous character |
| 37 | Dock & slider drag smoothness | Swipe up from bottom edge; drag Volume and Brightness sliders end-to-end repeatedly | Drag feels responsive (< 50 ms frame cadence via cached static base layer); backlight scales smoothly down to 10% without flickering off |
| 38 | Tactile UI sounds | Tap dock buttons, give a treat (**Moods & Care → Warm Tea**), and tap **Setup Wizard → Test chime**; then talk while listening/speaking | Soft harmonic chimes play on idle UI actions; never overlap or interrupt speech or recording; mute cleanly when **Touch sounds** is toggled off |
| 39 | Quick Prompts & touch keyboard | Swipe right from the left edge; tap a quick prompt, then tap **Type a message…** and send a sentence; also test **Wi-Fi** password entry | Recent chat bubbles display cleanly; quick prompts and typed messages speak aloud; keyboard hits every key accurately including Shift/Caps-Lock and `123`/`#+=` |
| 40 | Ambient Nightstand Mode | Set **Screen at night → nightstand clock** (or tap **Moods & Care → Nightstand**); check `journalctl -u companion-stage -f` and backlight; wait 5 minutes, then tap screen | Backlight dims to ~18%, warm low-glare clock sits above the dimly lit drowsy character, stage throttles to ~12 fps (cooler SoC), and a single tap wakes cleanly without triggering UI underneath |
| 41 | Bluetooth audio pairing | Put a Bluetooth speaker in pairing mode; open **Moods & Care → Bluetooth** (or Device tab), tap **Scan**, then tap the speaker to pair & connect; test voice output | Pairs, trusts, and connects cleanly; BlueALSA / PipeWire routes speech and chimes to the Bluetooth speaker (and pairings persist across reboot); Disconnect restores the built-in/USB speaker |

## Things to measure and feed back

- The sound card's ALSA name, and whether the ReSpeaker Lite's echo
  cancellation works over USB (this decides whether speaking can interrupt
  the character as well as the button).
- The display overlay line that actually works for your Touch Display 2, and
  whether touch rotation compensation (`screen.rotation`) is needed (`0°` vs `90°`/`270°`).
- The lowest non-black backlight percentage on Touch Display 2 (verify Nightstand's 18% level is comfortably visible in a dark room).
- The output latency (`OUTPUT_LATENCY` in `core/companion/audio.py`):
  film the screen and speaker together and compare mouth and sound.

## Troubleshooting

| Problem | Look at | Likely cause |
|---|---|---|
| Black screen after boot | `journalctl -u companion-stage -b` | Wrong display overlay line; or the stage program is missing from `/opt/companion/bin` |
| Screen shows a console login | `systemctl is-enabled companion-stage` | The installer did not finish; run it again |
| No sound | `aplay -l`; `/etc/default/companion` | The device picked the wrong sound card (it prefers a ReSpeaker, then any USB card); name the right one in `/etc/default/companion` |
| It never hears you | Console "What is happening" | Listening is off (press the button); wrong capture device; the on-device speech model failed to download (choose a cloud service) |
| "refused the key" | AI services → Test | The key is wrong, expired, or has no credit |
| Character shows as a still picture | Console; stage log | The puppet uses a feature the renderer lacks; the log names it |
| Settings page will not load | Phone on the same Wi-Fi? | The page only answers on the home network; check the address on screen |
| Forgot the settings page password | — | Hold the listen button for 12 seconds: the password and saved Wi-Fi are forgotten (characters, memories and keys stay) and the setup screens return |
| Passing the device on | Settings page → Device → Reset everything | Removes all characters, memories, keys, settings and saved Wi-Fi |
