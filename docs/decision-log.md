# Decision log

One entry per significant decision: what was chosen, why, and what was
rejected. Settled entries are not reopened without new evidence.

## D-001 — Reference product

- Date: 2026-11-16
- Decision: the benchmark is the SyBran CODE27 Character Livehouse / Companion
  Hub (model SyBran-01).
- Why: it is the only SyBran product matching the brief.
- Open: confirm with the project owner that this is what "CODE Sybran" means.

## D-002 — Clean-room boundary

- Date: 2026-11-16
- Decision: reproduce function and user experience from publicly observable
  information only. No vendor firmware, source, character or voice assets,
  trademarks or trade dress. All software in this repository is original or
  from correctly licensed open-source projects.
- Rejected: firmware extraction, asset reuse, visual copies of the vendor's
  characters or interface.

## D-003 — No hardware commitment before requirements sign-off

- Date: 2026-11-16
- Decision: no SBC, display or audio part is selected until the requirements
  interview is answered and written up as a specification.
- Why: budget, depth-effect choice, model complexity and local-versus-cloud
  processing each change the board class. Choosing first would bake in guesses.
