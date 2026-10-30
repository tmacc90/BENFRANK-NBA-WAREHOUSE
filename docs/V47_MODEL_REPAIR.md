# NBA v4.7 availability, rotation and uncertainty repair

This version implements the three model repairs identified by v4.6: original-report availability, variable legal rotations, and a separately calibrated uncertainty model tested on a later period. It preserves all original warehouse bytes, the failed v4.6 validation, and every stricter inherited release gate.

## Executable repairs

1. `benfrank_v47_availability.py` reads the physical PDF column coordinates, carries game/team context across page breaks, excludes page footers and retains explicit statuses. Its parser successfully processes the 64 original development reports with zero unresolved table rows. A player absent from a report remains unknown. A team marked `NOT YET SUBMITTED` is never cleared.
2. `benfrank_v47_history.py` constructs features only from games at least two calendar days before the target. Rates shrink to the observed previous season, rather than fabricated rookie logs. The pregame published board and original official report supply roster observations; target-game stats do not establish the forecast roster. Thin histories and secondary sources remain explicit.
3. `benfrank_v47_model.py` draws availability and conditional-minute scenarios, excludes confirmed-out players from the entire scenario roster, and allocates exactly 240 regulation minutes per team. An out player cannot re-enter via a foul-out substitution. A sparse board can be supplemented by actual team appearances from the preceding 45 days, with uncertain membership and attendance probability retained. Inactive-target outcomes are VOID, separate from OVER/UNDER/push counts. Every reported trial executes a complete sequential game. Overtime and offensive-rebound continuations are expanded; hitting a safety ceiling fails execution rather than silently treating a truncated game as complete. [NBA Rule 3-I](https://official.nba.com/rule-no-3-players-substitutes-and-coaches/) governs the last-five-player foul exception: the player stays eligible and a team technical free throw is assessed, rather than crashing the game or inventing a replacement.
4. `benfrank_v47_uncertainty.py` fits the location bias and globally shrunk isotonic probabilities on the earlier part of development data. A disjoint later development sample supplies the finite-sample split-conformal interval correction. Calibration cannot pool platforms, markets, scoring contracts or line bands, or fit any October test outcome.
5. `benfrank_v47_experiment.py` freezes the 32-game October 20–28 cohort, completes development, freezes the calibration artifact, then runs the separate later test. The inspected February–April v4.6 games become development evidence. They are not regraded as a new held-out success.
6. `benfrank_v47_run.py` is the repaired per-prop inference entry point. It executes at least 25K games and applies only an artifact whose platform, market, scoring contract, line band and time scope match. Calibration mismatch preserves a provisional direction and NO TICKET, with the exact blocker.

The core simulator's preparation cache was checked against five frozen legacy seeds; scores, player statistics, minute accounting and event outcomes remain identical under legacy settings. The new availability and expanded-tail behavior is explicitly versioned as v4.7.

## Source and validation scope

`configs/v47_validation_protocol.json` and `configs/v47_frozen_test_sources.json` fix the period, cohort rule, source commit hashes and fitting policy before the new predictions. The current NBA schedule comes from a commit-pinned NBA Stats mirror. Current individual game labels are ESPN secondary records. NBA season-total crosschecks are recorded separately and never represented as verification of the allocation across individual games. Direct current NBA endpoints remained unavailable during source collection; that limitation is retained.

The uncertainty method follows split-conformal quantile calibration's finite-sample order statistic, `ceil((n+1)*coverage)`. Its interpretation requires exchangeability; a later season and changing player roles can violate that assumption, so actual temporal coverage and its binomial interval are reported. The method is described in [Conformalized Quantile Regression](https://arxiv.org/abs/1905.03222). No numerical acceptance threshold is retroactively tuned to the October results.

## Run a prop with the repaired model

```bash
python benfrank_v47_run.py --context /private/source-backed-context.json --player 'Full Player Name' --market points --line 26.5 --platform PrizePicks --calibration models/v47_prizepicks_points_25_30_calibration.json --output /private/new-prop-receipt.json
```

Contexts must come from the source-backed builder and original dated reports, not a hand-authored claim that a player is healthy. The receipt records current execution time, source/context hashes, actual trial counts, conditional probabilities, void risk and separate release blockers. It is hashed and written exclusively to a new file; an earlier decision cannot be overwritten. Historical reconstruction is never labeled a live pregame pick. The checked-in calibration is byte-identical to the artifact frozen before October test execution: its 42 parameter-fit games and 28 conformal-calibration games are disjoint. It is a challenger artifact with explicit scope, not an automatic production certificate.

The `v47-model-repair.yml` workflow runs regression contracts and 25K actual sequential games on an explicitly synthetic software fixture. Real NBA development and October validation have separate receipts. A successful fixture job never awards FULL. Scope remains the markets with executable adapters and the separately validated calibration strata; no missing adapter or 66-stage source requirement disappears.

## Completed execution and measured results

The frozen execution source is commit `b4af77ca7a200ab2aac0d30cf9046d6521f6fc5d`. All 71 development contexts and all 32 later test contexts executed without exclusion. Each completed 25,000 actual games: 1,775,000 development trials and 800,000 test trials, 2,575,000 total. One settled development push is excluded from binary calibration, leaving 42 parameter-fit games and 28 disjoint conformal games. The frozen calibration SHA256 is `58969ceee18480765f71039ae093130ad2095a220262106ed3cdebe8485b2630`; its coefficients were not revised using October outcomes.

| October 20–28 test metric | Result |
| --- | --- |
| Independently dated test games | 32 |
| Raw nominal 90% interval coverage | 29/32 (90.63%) |
| Adjusted nominal 90% interval coverage | 30/32 (93.75%) |
| Adjusted coverage Wilson 95% interval | 79.85%–98.27% |
| Raw / adjusted mean absolute point error | 7.284 / 7.157 |
| Separate-process blind model mean absolute error | 7.790 (32 paired cases) |
| Raw / adjusted / baseline Brier score | 0.251114 / 0.239499 / 0.261079 |
| Adjusted / baseline log loss | 0.672018 / 0.724294 |
| Adjusted-minus-baseline Brier difference, game-cluster bootstrap 95% interval | -0.07946 to +0.02999 |

The Brier difference interval includes zero: this sample does not establish a statistical edge. The study is limited to PrizePicks points lines from 25 through less than 30. All 32 test labels retain `ESPN_SECONDARY_WITH_OFFICIAL_SCHEDULE_IDENTITY` assurance; season totals do not independently verify individual box scores. All 32 also retain some material unknown availability at their original early report cutoff. The test was reconstructed after the games, not issued live. These results are separate from the older v4.6 28-game test and are not a paired before/after comparison with it. Earlier failed development stress execution is preserved separately and never pooled into the completed sample.

The data-only evidence package preserves the source snapshots, original reports, frozen contexts, complete simulation counts, calibration, separate-process blind receipts and feature database. `diagnostics/v47-model-repair-validation-20261030.json` is the repository summary. The original complete warehouse SHA256 remains `76bd45d13047e7e4b0bf7b26a1546c631e82ae81bdd221bb5781e3b76e33d64b`.

## Batch integration and remaining release evidence

`benfrank_v44_batch.py` dispatches a prop containing a matching `v47_context` to the repaired runner and the checked-in frozen calibration. It validates exact snapshot, game/date, platform, capture/tipoff, source cutoff and opponent identity. The repaired probability direction and calibrated forecast become the primary output; the legacy baseline remains separately labeled. A real 25K batch proof analyzed its prop without error, retained NO TICKET, and substantiated governing stage G53 from the matching execution receipt. Context-less boards preserve their earlier provisional path. Batch and standalone CLI outputs are immutable hashed new files.

FULL remains a per-prop decision. Required next evidence includes independently reconciled player-game outcomes and shooting/lineup sources; authoritative final pregame availability and starting/rotation confirmations; sufficient genuine pregame line history and later walk-forward evaluation for every proposed platform/market/line band; and complete applicable opponent, stress, blind-model, freshness and settlement requirements from the governing 66-stage contract. The current free mirror/ESPN route supplies usable secondary evidence during official endpoint failures, but cannot silently inherit official assurance. A signed, source-backed final receipt must substantiate the applicable requirements before any FULL/ticket promotion.
