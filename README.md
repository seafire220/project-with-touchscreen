# Low-cost AI character device

An independently designed, lower-cost alternative to the SyBran CODE27
Companion Hub: a desk device that shows a 2D anime-style character you can
talk to. Built from commodity hardware and original software, using the
owner's own AI service keys, with no lock-in to one AI or voice provider.

Two tiers: **Lite** plays pre-rendered 2D animation; **Standard** drives a
rigged 2D puppet.

## Status

| Phase | State |
|---|---|
| 1. Reference product research | First pass done |
| 2. Requirements interview | Answered |
| 3. Requirements specification | Draft 2 |
| 4. Hardware selection and BOM | Prototype board chosen: Raspberry Pi 4, 1 GB |
| 5. Architecture | Revision 2, after review and testing |
| 6. Software implementation | Started. Stage (character drawing) and a flat-image layer splitter implemented and tested on software graphics; core service, console and installer not started |
| 7. Install, boot and appliance behaviour | Designed; not implemented |
| 8. Build guide, test plan | Not started |

Estimated prototype cost: about A$239 (Raspberry Pi 4 option) or A$294
(Radxa Zero 3W option), against roughly A$850 for the reference product.

## Code

- [`stage/`](stage/README.md) — draws and animates the character on the
  device screen.
- [`studio/flatsplit.py`](studio/flatsplit.py) — cuts a flat character
  picture into named layers for the rigger, without repainting it.

## Documents

1. [Reference product research](docs/01-reference-product-research.md)
2. [Requirements interview and answers](docs/02-requirements-interview.md)
3. [Requirements specification](docs/03-requirements-spec.md)
4. [Technology research](docs/04-technology-research.md)
5. [Hardware options and bill of materials](docs/05-hardware-and-bom.md)
6. [System architecture](docs/06-architecture.md)
7. [Test: Inochi2D on Linux](docs/07-spike-inochi2d.md)
8. [Review of the owner's earlier work](docs/08-prior-work-review.md)
9. [Experiment: flat image to puppet without repainting](docs/09-flat-image-experiment.md)
- [Decision log](docs/decision-log.md)

## Awaiting the owner

- The owner's verdict on the first generated puppet (animation and stills
  supplied outside the repository).
- A handful of other character images the method has never seen, to test
  whether it generalises.

## Known gaps

- No part has been bought or tested; every hardware compatibility statement
  is from documentation or search results. Inochi2D rendering has been
  tested, on software graphics only.
- Memory use, boot time and on-device speech recognition speed are estimates.
- Several prices are estimates, marked in the hardware document.
- Compliance cost for selling in Australia has not been researched.
