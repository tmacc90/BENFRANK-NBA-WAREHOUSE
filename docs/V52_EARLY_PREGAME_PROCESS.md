# BENFRANK v5.2: predict early, measure forward

The October 31, 2026 user instruction replaces waiting for final starters with depth charts and projected lineups. EARLY_PREGAME is the new forecasting/test mode. It can issue a direction hours before a game. A final starting five, late official clearance and a near-tipoff recheck are not prerequisites for this mode. This is a concrete process repair, not a claim that an unmeasured model is the greatest or that accuracy has been certified.

The original warehouses, 66-stage governing text, strict legacy certification mode, earlier failed runs and original predictions are retained. `configs/v52_early_testing_policy.json` records the narrow G08/G09/G60 early-mode amendment. Never backdate a source or describe a projected lineup as confirmed.

## Execution contract

1. Freeze every supplied player, market, exact line, opponent, game and analysis clock. Screenshots supply names/lines. Preserve native capture time as unknown when it is unknown; analysis time is a separate field.
2. Read historical player and full-team profiles from source-backed warehouse contexts. Exclude target-day/later game outcomes. Calculate L5/L10/L15/L20/L25/L32/L52, current/previous season and the explicitly incomplete available archive span. Date-specific identity, missing adapters and genuine missing target history can still produce exact blockers.
3. Capture all five ESPN depth positions. Optional public RotoWire expected-five projections are an explicit additional source for this early workflow; the existing ESPN/NBA-only scheduled collector is unchanged. Record source/retrieval clocks, byte hashes and disagreements. An expected-five disagreement becomes a scenario alternative. Resolve only exact names or a unique documented generational-suffix difference, never fuzzy names.
4. Prefer an original timestamp-checked NBA injury PDF. On an actual source outage, retain the failure and use literal ESPN secondary observations. Unlisted is UNKNOWN; day-to-day is not silently promoted to healthy. No source is promoted to official authority.
5. Infer minutes from actual recent played minutes, depth position and projected role, then conserve 240 regulation minutes per team. Confirmed-out players cannot appear in any substitution path. Unknown/questionable participation is a model scenario, not medical clearance.
6. A non-target reserve with no observed NBA profile receives an explicitly labeled observed-reserve peer prior. Its target game count stays zero and its historical-minute list stays empty. Its source peers and estimated minutes are recorded. This does not manufacture college/G League translation or validated rookie skill. Such priors remain a separate validation/risk cohort.
7. Execute at least 25,000 actual complete sequential 5-on-5 games per prop. Retain OVER/UNDER/push/model-void counts, the full target histogram, quantiles, seeds, context/engine hashes, checkpoint chains and 240-minute checks. A tail guard fails execution. A model void is not an UNDER win or a verified platform DNP settlement.
8. Before primary inference, run a separate line-blind pooled ridge worker on real chronological lagged outcomes. It receives only numeric features and training labels, not player names, lines, opponent or primary output. A five-game rookie can use real peer training without inventing 40 additional rookie games. The model remains unvalidated. Fewer than three real target appearances remains an exact blocker.
9. Measure material questionable-player IN/OUT branches, published-versus-depth roles, and separate low-minute/low-conversion and high-minute/hot-conversion stresses. By default each dedicated stress executes 2,000 additional complete games. These are explicitly proxies where observed rebound chances/potential assists are absent, not falsely completed P25 opportunity-times-conversion certification.
10. Issue mandatory OVER/UNDER from the primary played/nonpush side distribution. Report independent-model disagreement and scenario sign flips without averaging them away. `STABLE_IN_TESTED_CASES_ONLY` describes the tested scenarios, not verified probability or broad robustness.
11. Insert the actual issued prediction before tipoff into a new append-only SQLite ledger. `FORWARD_TEST_READY` means the process ran with source-clock checks before the game. It does not mean certified accuracy or betting approval. All outputs use `UNVALIDATED_EARLY_CHALLENGER / RESEARCH_ONLY`; missing calibration does not stop collecting test forecasts.
12. After completed games, append source-hashed ESPN final outcomes without altering predictions. DNP/platform early-exit cases remain unresolved until the applicable native settlement rule is substantiated. Score hit rate and raw Brier separately by platform/market/line band and unique games. Never pool markets to inherit unrelated calibration, refit on the test cohort, or count synthetic software tests as prediction certification.

## One-command entry point

Keep the owner's board, historical contexts, databases and ledger outside the public repository. A private config provides:

```json
{
  "board": "/private/board.json",
  "contexts": "/private/source-backed-contexts",
  "history_db": "/private/research-features.sqlite",
  "ledger": "/private/early-forward-ledger.sqlite",
  "published_projected_lineups": true,
  "trials": 25000,
  "stress_trials": 2000
}
```

Each board record supplies the existing player/market/line/team/opponent/date/game ID/tipoff/platform fields, an isolated `snapshot_id`, `espn_event_id`, and optionally `context_id` naming a source-backed per-game profile context. The upstream acquisition/context builder supplies real rate and team history; v5.2 does not fabricate that dependency. The context must match the same game/date/teams/tipoff, and all used features precede the game. An absent context is an explicit source-ingestion blocker, not a final-lineup wait.

```bash
python benfrank_v52_pipeline.py --config /private/early-config.json --output /private/new-immutable-run
```

This captures depth charts/projected roles and current availability, executes the board, and freezes successful predictions in the ledger. Source failures or genuine execution errors are isolated per prop in `comparison.json`; reruns use a new output directory and new snapshot ID. Revisions preserve prior forecasts and should be evaluated as revisions, not independent games.

To settle and review measured forward results:

```bash
python benfrank_v52_ledger.py --db /private/early-forward-ledger.sqlite --settle --output /private/new-settlement-receipt.json
```

No new recurring job is scheduled by this change. Existing collector schedules remain unchanged. The usual repository test workflow runs the new contracts on push/PR. Actual user-board execution has separate receipts and is not replaced by that workflow's synthetic tests.

## What testing still has to establish

Predictive accuracy, calibrated winning probabilities, source-tier effects, thin-history performance, prior-sensitive reserve cases, game-cluster uncertainty and any betting edge must be measured on the new forward cohort. Defender assignments, shot quality, contested chances and college/G League translation stay missing where not observed; they are neither invented nor prerequisites for issuing an explicitly limited early test forecast. New measurements can justify later repairs; there is no honest guarantee that this is the last model change ever needed.
