# What else would make it complete and polished

Status: 2026-11-20. The owner asked for a review of anything else that would make the product more complete
and polished. This is that review, in order of importance, with what was built in the same round marked.
Everything below is about the product as a buyer meets it; `21-roadmap.md` keeps the overall order of work.

## Built in this round

| | What | Where |
|---|---|---|
| ✓ | **Software updates for sold devices**: signed with your key, installed at night, undone if they fail, and finished or undone after a power cut | `32-updates.md` |
| ✓ | **Speaking first**, as an option: greets you when you come back, asks how your plans went | `31-memory.md` |
| ✓ | **Memory that matches by meaning**: "my pup" finds the dog | `31-memory.md` |
| ✓ | **Your own rigged models**: Inochi2D files added directly; Live2D models' pose files respected (a sample showed two sets of arms at once before) | `28-user-guide.md` |
| ✓ | **Backup and restore**: every character with its memory, choices and animations, and the settings, in one file. Keys, the password and Wi-Fi are never in it. For keeping, or for moving to a new device or a bigger card | Device tab |
| ✓ | **A support report**: versions, board, storage, settings, which keys are set, recent problems and logs. No keys, no passwords, nothing anyone said. A buyer can email it to you | Device tab |

## Before selling (needed)

1. **Run it on the real hardware.** Nothing has run on a Raspberry Pi yet; everything is tested in software and under emulation. Follow `29-hardware-setup.md` and `15-hardware-test-plan.md`: frame rates, memory, boot time, the hotspot, the buttons, the sound card, a whole day of use.
2. **Make your update key and choose the update address** before building the images you sell (`32-updates.md`). A device made without them can only be updated by re-flashing its card.
3. **Protect the card from power cuts.** The architecture doc said the system was read-only; it was not (corrected).
   - Writes are safe now: they are atomic and journaled, the logs are small, and the power button shuts down cleanly.
   - Proper protection means a read-only system partition plus a separate data partition for characters, memories, settings and the software's versions, so updates can still be written.
   - Medium work, mostly in the image build; to be tested on the real board.
4. **A character in the box.** Commission original art (no existing character may ship, D-024), so a new device greets its buyer with someone rather than text.
5. **The paperwork:**
   - the six questions for a lawyer (`19-live2d-format-licensing.md`);
   - in Australia, an electrical safety and EMC declaration (RCM) for the finished product. A pre-certified Pi and power supply help, but don't cover the whole device;
   - a privacy statement, saying what goes to the AI services the buyer chooses;
   - warranty and returns terms.
6. **A quick-start card in the box:** a QR code for the setup steps, and one for the user guide.

## Strongly recommended

7. **A wake word**: say the character's name instead of pressing the button.
   - sherpa-onnx, already on the device for speech recognition, also does keyword spotting with small models.
   - The echo-cancelling microphone in the parts list (ReSpeaker Lite) makes it dependable.
   - Medium work; the single biggest everyday improvement.
8. **Captions**: what the character says, on the screen, as an option. Helps in noisy rooms, and anyone hard of hearing. Medium work, in the stage.
9. **Screen sleep at night.** The character already dozes; dimming or switching off the display on a schedule saves the screen and the bedroom. Small to medium, depending on the display's backlight control.
10. **A family-safe mode**: an option that adds content rules to every reply's instructions, for homes with children. Small.
11. **A microphone mute you can see**: a hardware switch (or a long press) with the state shown on screen. Some buyers will want it, whatever the software promises.

## Later

12. **Other languages**: the settings page, the voice and speech recognition are English today. Large: models and voices per language.
13. **Live2D models' own motions**: playing a model's idle animations as well as its expressions and the device's own movement. Medium.
14. **More than one person**: telling voices apart, so memory belongs to the right person and speaking first knows who came in. Large.
15. **Add the settings page to the home screen**, so it opens like an app on a phone. Small.
16. **Calendar, weather, smart home**, as tools the character can use. Medium each.
17. **Hearing about failed updates**: an opt-in report to you when a device goes back to an earlier version. Small, with a privacy statement.

## Not recommended

- **Encrypting the data on the card.** The device has nowhere safe to keep the key. A key on the card protects nothing, and asking the buyer for a password at every start-up is not appliance behaviour. The risk is someone who takes the card out and reads it. Mitigations instead:
  - keys can be revoked at their services in a minute;
  - **Device → Reset everything** before passing a device on;
  - the case can make the card hard to reach.
