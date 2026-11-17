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
| 17 | Memory | Tell it a fact; after six exchanges check Memory | The fact appears in the notes; edits there are used |
| 18 | Failure | Remove the language model key, then talk | A short tone and a clear message in the console; no hang |
| 19 | Restart recovery | `sudo systemctl kill companion-stage`, then the core | Both come back within 5 s |
| 20 | Echo | Turn listening on and let it speak loudly | It does not answer itself (the microphone is ignored while it speaks) |

## Things to measure and feed back

- The sound card's ALSA name, and whether the ReSpeaker Lite's echo
  cancellation works over USB (this decides whether speaking can interrupt
  the character as well as the button).
- The display overlay line that actually works for your Touch Display 2.
- The output latency (`OUTPUT_LATENCY` in `core/companion/audio.py`):
  film the screen and speaker together and compare mouth and sound.

## Troubleshooting

| Problem | Look at | Likely cause |
|---|---|---|
| Black screen after boot | `journalctl -u companion-stage -b` | Wrong display overlay line; or the stage program is missing from `/opt/companion/bin` |
| Screen shows a console login | `systemctl is-enabled companion-stage` | The installer did not finish; run it again |
| No sound | `aplay -l`; `/etc/default/companion` | The sound card name in `/etc/default/companion` is wrong |
| It never hears you | Console "What is happening" | Listening is off (press the button); wrong capture device; the on-device speech model failed to download (choose a cloud service) |
| "refused the key" | AI services → Test | The key is wrong, expired, or has no credit |
| Character shows as a still picture | Console; stage log | The puppet uses a feature the renderer lacks; the log names it |
| Settings page will not load | Phone on the same Wi-Fi? | The page only answers on the home network; check the address on screen |
| Forgot the settings page password | — | Delete `/var/lib/companion/config/console-password` over SSH and restart `companion-core`; the next visit asks for a new one |
