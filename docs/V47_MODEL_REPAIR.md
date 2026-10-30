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
python benfrank_v47_run.py --context /private/source-backed-context.json --player 'Full Player Name' --market points --line 26.5 --platform PrizePicks --calibration /private/frozen-calibration-model.json --output /private/new-prop-receipt.json
```

Contexts must come from the source-backed builder and original dated reports, not a hand-authored claim that a player is healthy. The receipt records current execution time, source/context hashes, actual trial counts, conditional probabilities, void risk and separate release blockers. Historical reconstruction is never labeled a live pregame pick.

The `v47-model-repair.yml` workflow runs regression contracts and 25K actual sequential games on an explicitly synthetic software fixture. Real NBA development and October validation have separate receipts. A successful fixture job never awards FULL. Scope remains the markets with executable adapters and the separately validated calibration strata; no missing adapter or 66-stage source requirement disappears.
