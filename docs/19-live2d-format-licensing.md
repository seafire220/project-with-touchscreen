# Licensing check: Live2D-format models without Live2D's software

Status: 2026-11-17. A check of public sources, written by an engineer, not a
lawyer. It says what we do, what Live2D's published terms say, where the
risks are, and which questions a lawyer must answer before units that make
or play Live2D-format files are sold. Items marked **For a lawyer** are
open.

**Owner's decision (2026-11-17, D-044):** the device plays characters
with Ayagami, Live2D-format copy first, with Inochi2D kept as the fallback
(screen cards, older packages, and any character without a Live2D-format
copy). This was decided after a second reading of the terms (ChatGPT's, by
the owner; also not a lawyer's): Ayagami's licence allows commercial use;
Live2D's per-unit SDK fee is a condition of using Live2D's own SDK, which a
build with only Ayagami does not include; the point still open is the Cubism
Editor licence (reportedly section 5.1.9), which restricts what Editor
customers may do with exported files and so concerns buyers' own models and
any models we bundle, not the player. The lawyer questions below still need
answers before selling; switching units back to Inochi2D is one default
(`character_format` in `core/companion/store.py`).

Two of the sources could not be read from the development session: Live2D's
own pages (live2d.com) and one blog post (undeleted.ronsor.com) are blocked
by its network settings. What is said about them here comes from search
results. The owner can open them in a browser, or allow those two sites in
the session's network settings so they can be read and quoted directly.

## What we do, and what we do not do

- **Making models.** `studio/live2d_export.py` (the `--live2d` option of
  `make_character.py`, off by default) writes `.moc3` files with the writer
  in image2live2d (Apache-2.0). That writer follows the byte layout
  published by the OpenL2D project (`moc3.hexpat`, from its `moc3ingbird`
  repository, whose README says no file in it was derived from the output of
  any Live2D software). We reverse-engineered nothing ourselves.
- **Playing models.** The device's Live2D-format path uses Ayagami's core
  (MIT or Apache-2.0), vendored in `stage/vendor/ayagami` with its licence
  files; the drawing code around it is ours (`stage/src/live2d.rs`). Its README says it was developed "strictly
  using black-box reverse engineering only": reading model files and
  watching how test models render in VTube Studio, never disassembling or
  decompiling proprietary software. It says it may be used for any purpose
  without royalties or permission, "including ... expandable applications
  that load user-provided models", and that it is not affiliated with or
  endorsed by Live2D Inc.
- **Not used anywhere in the product or the studio:** Live2D's Cubism SDK
  or Cubism Core library, the Cubism Editor, Live2D's sample models, and
  Live2D's names or logos as branding.
- **Live2D's sample models** were used only on the development computer, to
  check that our files are drawn the right way up and in the right colours,
  and that the device's drawing matches Ayagami's own renderer and imports
  model folders correctly. They are not in the repository or the product and
  must not be (D-024).
- **Buyers' own models.** The settings page accepts a zip of a Live2D-format
  model's folder (as shared for VTube Studio) and turns it into a character;
  it asks people to add only models they have the right to use, and notes
  that some model licences name the programs allowed to show them.

## Live2D's published terms

- **The official reader is closed.** Cubism Core, the library that reads
  `.moc3` files, is under the Live2D Proprietary Software License; the
  Cubism Framework around it is under the Live2D Open Software License.
  Live2D's documentation says Cubism Core is not published on GitHub for
  that reason. Their licences forbid reverse engineering and modification.
  Those terms bind people who accept them, for example by downloading the
  SDK; we have not used anything obtained under them.
- **The official route would cost a lot for this product.** A device that
  loads users' own models is what Live2D calls an "Expandable Application".
  Every one needs review, approval and a Publication License Agreement
  before release, even for individuals and small businesses, and approval
  "may not be granted ... in all cases". The published fees are an initial
  fee (¥50,000 or ¥300,000 by business size), annual fees, and a revenue
  share of ¥300 per sale or 20% of sales, whichever is higher, for small
  businesses (5% for larger ones). On a device at our price that is a large
  share, and approval is uncertain. That is why Ayagami is the candidate,
  not the official SDK.
- **Enforcement on record.** GitHub's DMCA records hold notices from Live2D
  citing the licence's ban on reverse engineering and modification: against
  repositories that redistributed or modified Cubism Core itself, shared
  licence keys, or cracked Cubism. In at least one case GitHub found the
  anti-circumvention claim insufficient but other copyright claims valid. No
  public record was found of action against an independent reader or writer
  such as Ayagami, image2live2d or OpenL2D's layout description. An earlier
  search suggested an independent reader's developer had been threatened
  (undeleted.ronsor.com); that page could not be read, so this is
  unverified.
- **Trademarks.** "Live2D" and "Cubism" are Live2D Inc.'s trademarks. Its
  help pages say the logo and name may be used when its brand guidelines are
  followed; those guidelines mainly cover SDK users, who must show the logo.

## The questions, and where they stand

| Question | Current view | For a lawyer? |
|---|---|---|
| Does our code copy Live2D's? | No. Our code, image2live2d (Apache-2.0) and Ayagami (MIT/Apache-2.0) are independent; no Live2D code, library or data is included. | Confirm the provenance claims of the two open-source projects are enough for us to rely on. |
| Can Live2D stop others from reading or writing the file format? | A file format as such is generally not protected by copyright; the usual risk is in how the knowledge was obtained, which concerns the people who reverse-engineered it, not us. In Australia, s 47D of the Copyright Act 1968 allows reproducing a program to make interoperable products, and s 47H makes contract terms that exclude it void. | **Yes.** Our position as a downstream user, in Australia and in the countries backers live in (US, Japan, EU). |
| Patents | Not searched. Live2D Inc. may hold patents on its deformation methods or file handling. | **Yes.** A freedom-to-operate search (JP, US, EU, AU) before selling units that play these files. |
| Can we say the device plays Live2D models? | Do not use "Live2D" or "Cubism" in the product name, logo or as a badge. A plain factual statement such as "plays .moc3 model files" may be acceptable descriptive use; Ayagami uses the names "only nominatively, to describe file-format compatibility". | **Yes.** What wording, if any, is safe on the Kickstarter page and the box. |
| Buyers' own models | Models bought from artists, or made with Cubism Editor, come with their own licences; some allow only personal or streaming use, or use in named apps. The device plays what the buyer loads; the upload page says so. | Wording for the user guide and terms of sale: buyers must have the right to use a model on the device. |
| Cubism Editor licence (reportedly section 5.1.9) | Reported to restrict Editor customers from using files exported by the Editor with software other than Live2D's. If so, a buyer who made a model in the Editor could be in breach by loading it on the device; the obligation is the buyer's, but advertising the import could be read as encouraging it. It also rules out bundling Editor-made models unless their makers grant the right. Our own characters are not made with the Editor. | **Yes.** Confirm the clause and its current text; whether advertising the import is safe and how to word it; and that models we write ourselves (studio) are outside it. |
| The studio writing `.moc3` files | image2live2d's authors made writing `.moc3` opt-in, saying the remaining gate is legal (Live2D's SDK licence), not technical. Ours is opt-in as well. | Covered by the format question above. |

## Recommendation

The engineering recommendation was to keep Inochi2D as the default until a
lawyer had answered (D-040). The owner decided to play Live2D-format copies
first (D-044); what follows keeps that decision safe to reverse.

1. Keep Inochi2D able to play every character the studio makes (it does:
   every package has an `.inp`), so units can be switched back with one
   default if a lawyer advises it.
2. Keep Live2D-format output opt-in in the studio (`--live2d`) until the
   owner turns it on for the one-click app.
3. Keep the safeguards: no Live2D code, SDK, editor output or sample model
   in the product or the repository; no Live2D trademarks in branding; and a
   record of where every third-party component comes from and under which
   licence (`stage/vendor/PATCHES.md`).
4. Before the Kickstarter page goes live, ask a lawyer the six questions in
   the table, with this document and the Ayagami and image2live2d READMEs
   attached, and do not advertise importing Live2D models until the Cubism
   Editor question is answered.

## Sources

- Live2D, SDK licence overview: https://www.live2d.com/en/sdk/license/
- Live2D, Expandable Applications fee table: https://www.live2d.com/en/?p=607
- Live2D Proprietary Software License Agreement (English translation):
  https://live2d.com/eula/live2d-proprietary-software-license-agreement_en.html
- Live2D Open Software License Agreement (English translation):
  https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html
- Live2D, Cubism Core documentation: https://docs.live2d.com/en/cubism-sdk-manual/cubism-core/
- Live2D help, logo and trademark use: https://help.live2d.com/en/?p=2523
- Live2D, Terms of Use for Cubism Sample Data: https://www.live2d.com/eula/live2d-sample-model-terms_en.html
- OpenL2D, moc3ingbird (format pattern and README): https://github.com/OpenL2D/moc3ingbird
- Mirror of GitHub's DMCA records (Live2D notices):
  https://git.randommeaninglesscharacters.com/github/dmca/commit/82675e1c742eb3562e6aa3af2b10b066b26566c0 and
  https://git.randommeaninglesscharacters.com/github/dmca/commit/e3937644aebac8e96e15f64021caaa63fb8d654f
- Ayagami README (provenance, licence, trademark notice), and Lina's
  reverse-engineering FAQ it links: https://lina.yt/moc3faq
- image2live2d README, "Notes on the Live2D targets":
  https://github.com/Wzhang3912/image2live2d
- Copyright Act 1968 (Cth) s 47D:
  https://www6.austlii.edu.au/au/legis/cth/consol_act/ca1968133/s47d.html
- Copyright Act 1968 (Cth) s 47H:
  https://20.austlii.edu.au/au/legis/cth/consol_act/ca1968133/s47h.html
- Australian Law Reform Commission, contracting out of copyright exceptions:
  https://www.alrc.gov.au/publication/copyright-and-the-digital-economy-ip-42/contracting-out/
