# BENFRANK free iPhone workflow: verified execution — 2026-11-07

## Links

- [Full independent-verification GitHub Actions run](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/42409096534)
- [Audit bundle (GitHub Actions artifact; expires November 10, 2026)](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/42409096534/artifacts/13588761445)
- [One-tap free launcher on default branch](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/workflows/benfrank-free-launcher.yml)

## Actual result, not a placeholder

The source-backed no-subscription **manual** pathway executed successfully in
GitHub Actions on November 7, 2026. The runner returned
`FORWARD_RESEARCH_EXECUTED` and froze **one pregame research prediction**.
The separate verification tool `scripts/verify_auto_run.py` passed with
`ACTUAL_ARTIFACTS_VERIFIED`.

Observed verification counts:
- 120 retained raw source documents passed SHA-256 integrity checks.
- 25,000 main complete-game simulations plus two 2,000-trial stress scenarios:
  **29,000 complete simulated games**.
- Main and both stress trial trace chains were verified.
- Five predetermined trials per scenario were independently replayed (15 in total).
- The frozen pregame prediction was independently checked against the immutable ledger.
- Original protected warehouse and governing files passed the preservation check.
- The existing player-history, exact-line window, Blind-model process, adversarial,
  sensitivity, DNA and 60-question stages all emitted execution receipts.

The deliberately labeled test was **Aaron Gordon — points 13.5, DEN @ IND,
November 7, 2026**, modeled **OVER** at research confidence only.
The exact line came from a prior research example; **it was not
independently confirmed as an available PrizePicks or sportsbook offer**.
The prediction's pregame freeze preceded the game's listed 22:00 UTC tipoff.

## Known limitations and unresolved questions

- The free PrizePicks public projections API returned **HTTP 403 Forbidden** in
  the earlier automated-discovery GitHub Actions run
  [42408679478](https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/42408679478).
- The corrected `manual_forward_prop` route never requests the blocked endpoint.
  Player/game are validated against future ESPN schedule/depth; the **line is
  user-supplied** and not independently marketplace-verified.
- `ACTUAL_ARTIFACTS_VERIFIED` verifies provenance/execution, **not model
  probability calibration or outcome predictive accuracy**. Raw OVER percentages
  are uncalibrated. Blind-model process separation is audited, predictive
  independence/performance still needs separate held-out assessment.
- Postgame grading remains prepared/pending after the game is final; no win is
  claimed from a pregame prediction.
- Standard GitHub-hosted runners can execute this project in a public repo
  without paid Render hosting. Provider availability and GitHub usage policies
  remain external constraints.
- Trace/source artifacts retained with the run expire automatically after three
  days, so save the ZIP before that time for permanent personal audit.

## How to use

On iPhone/iPad open the free launcher above on **main**, choose **Run workflow**,
leave NBA date as `today` if appropriate, paste the **player**, supported
**market** (for example `points`), and **exact line** from your prop.
Confirm the player's game is still in the future, run it, and inspect the
completed run's evidence ZIP and `verification.json`.

All user-facing forecasts remain research-only without an established
forward, independently calibrated hit rate. Preserve existing warehouse
data, rules and historical prediction receipts.
