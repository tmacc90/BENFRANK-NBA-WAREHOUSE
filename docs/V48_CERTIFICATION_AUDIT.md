# BENFRANK NBA v4.8 certification audit — execution contract

## Purpose and boundaries

This additive release does **not** assert an unearned model certificate, win rate, or production betting recommendation. It closes the missing *certification decision-infrastructure* gap: a stage can only advance with attributable, independently verified evidence. Every model output remains `NO_TICKET` while this evidence is incomplete. The existing v4.7 simulator, history, original archive, legacy rules and calibrations remain untouched.

- `benfrank_v48_certification_gate.py` verifies nine categories of required evidence. Its only positive return is `ELIGIBLE_FOR_INDEPENDENT_CERTIFICATION_REVIEW`; it does not grant FULL or ticket release. Synthetic fixtures, unit tests, missing/poorly-typed receipts and unsupported current sources are rejected.
- `benfrank_v48_readiness.py` reads immutable existing v4.7 experiment, calibration and protocol files and creates a fresh reproducible **research readiness** report with source SHA256 hashes. Source evidence can be independently checked, but immutable historical research does not qualify as a prospective platform prediction.
- `.github/workflows/v48-certification-readiness.yml` runs these checks on PRs or manual dispatch; archives the small JSON readiness receipt and puts stage blockers in the Actions summary. It does not upload private datasets.
- Tests verify that 32 evaluated games and 2,575,000 historical-model simulation trials are *reported accurately and remain uncertified*.

## What the latest source-backed experimental data shows

The frozen v4.7 model studied PrizePicks **points** in only the 25-to-under-30 line band. It executed 1,775,000 retrospective development simulations and 800,000 temporally later test simulations, 25K for each evaluated line. Its 70 development games were split into 42 parameter-fit games and 28 disjoint conformal-calibration games. The later test contains **32 distinct October 20–28 games**.

| Frozen test measurement | Observed |
| --- | --- |
| Calibrated Brier score | **0.239499** |
| Historical baseline Brier | **0.261079** |
| Difference, calibrated minus baseline | **-0.021580** |
| Clustered 95% bootstrap interval for Brier difference | **-0.0794567 to +0.0299871** |
| Adjusted 90% interval coverage | **30/32** |
| Unknown material availability cases | **32/32** |
| Individual game settlement assurance | **ESPN secondary with official schedule identity**, not official independent player stats |

Because the Brier confidence interval overlaps zero, the test is not statistically strong enough to establish reliable improvement, notwithstanding a descriptively lower average Brier. It is retrospective reconstruction, not 32 live issued decisions. New outcomes cannot be retroactively used to tune or regrade this validation.

The complete saved 2024–25 and 2025–26 archived NBA LeagueGameLog source contains **52,957** crosschecked rows and was independently audited outside GitHub; the current GitHub mirror import contains **52,911**. The full archived file has not been securely installed into GitHub Actions, and the current NBA Stats API still times out there. Do not conflate saved official-source verification with live API access.

## Nine specific release dependencies

1. **History:** reproducibly install authorized complete original archive in the execution environment; preserve its SHA256 and original official-source response receipts, without public upload.
2. **Current season:** secure independent player-game box score and shooting/rotation reconciliation. ESPN staging is not the same as independently verified official season coverage.
3. **Availability and lineups:** use dated official injury reports and a final pregame confirmed starting five, starter status, minute restriction and substitution/rotation forecast for the specific scheduled game.
4. **Exact lines:** capture genuine, timestamp-attested pre-tipoff platform/market/line snapshots. A pinned secondary collector is useful research but not authenticated native sportsbook evidence.
5. **Possession model:** execute at least 25,000 fully sequential real-game trials **per line** with complete current verified player opportunity/efficiency inputs and record each game/seed/source hash, then pass real-game calibration.
6. **Blind challenger:** execute an independent feature-isolated model against the same future test; preserve its training freeze, input source, model digest and original prediction.
7. **Calibration:** predeclare market-specific, platform-specific, scoring-specific and line-band acceptance criteria, then evaluate new, untouched, independently settled outcomes. The current v4.8 automated gate uses a **conservative provisional review threshold of 500 out-of-sample outcomes per evaluated stratum** and upper confidence bound below zero for Brier improvement. That threshold is an *engineering review policy*, not a statistical guarantee or retroactive claim of proven profitability. Revise only prospectively in a new auditable version.
8. **Market adapters:** do not claim validated fantasy score, rebounds, assists, threes, PRA etc. merely from a points-only fit. Test each adapter, settlement and scoring contract independently.
9. **Governing stages:** attach actual per-prop execution evidence, independent stress tests and ticket authority for all applicable v4.4+ stages. A static 66-stage enumeration is not proof that 66 analytical stages executed.

Even if all nine software gates turn green, an independent promotion decision is necessary. FULL is per prop and market, never a global guarantee that bets will win.

## Current verified outcome

Running `python benfrank_v48_readiness.py --output receipts/v48-certification-readiness.json` produces `NOT_CERTIFIED`, `NO_TICKET` and precise blockers. The expected outcome is correctly **not** a green claim merely from code deployment. Existing archived sources and models are read-only.

The release is intended to let later verified data satisfy stages incrementally without retroactively changing these observed failures. There is no API credential, sports data source or probability threshold in this repository that can *guarantee* predictive accuracy.

## Run manually

```bash
python -m unittest discover -s tests -p 'test_v48_*.py' -v
python benfrank_v48_readiness.py --output receipts/v48-certification-readiness.json
# --require-certifiable will exit nonzero until independent source-backed gates pass
python benfrank_v48_readiness.py --output receipts/v48-required.json --require-certifiable
```
