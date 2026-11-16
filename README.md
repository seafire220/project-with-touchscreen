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
| 4. Hardware selection and BOM | Two prototype options costed; owner to choose |
| 5. Architecture | Revision 2, after review and testing |
| 6. Software implementation | Not started; Inochi2D rendering proven in a test |
| 7. Install, boot and appliance behaviour | Designed; not implemented |
| 8. Build guide, test plan | Not started |

Estimated prototype cost: about A$239 (Raspberry Pi 4 option) or A$294
(Radxa Zero 3W option), against roughly A$850 for the reference product.

## Documents

1. [Reference product research](docs/01-reference-product-research.md)
2. [Requirements interview and answers](docs/02-requirements-interview.md)
3. [Requirements specification](docs/03-requirements-spec.md)
4. [Technology research](docs/04-technology-research.md)
5. [Hardware options and bill of materials](docs/05-hardware-and-bom.md)
6. [System architecture](docs/06-architecture.md)
7. [Test: Inochi2D on Linux](docs/07-spike-inochi2d.md)
- [Decision log](docs/decision-log.md)

## Awaiting the owner

- Choice of prototype board (decision D-016).
- A layered file from See-through for one of the owner's characters, to
  develop the rigger against.
- The summary of the owner's earlier work on this idea.

## Known gaps

- No part has been bought or tested; every hardware compatibility statement
  is from documentation or search results. Inochi2D rendering has been
  tested, on software graphics only.
- Memory use, boot time and on-device speech recognition speed are estimates.
- Several prices are estimates, marked in the hardware document.
- Compliance cost for selling in Australia has not been researched.
