# BENFRANK NBA v4.5 — source evidence and simulator calibration repair

This is additive to v4.4 and its 66 governing stages. OVER/UNDER, one-prop isolation, immutable evidence, Winner Preservation and separate ticket authority remain in force. No source warehouse, baseline game record, or historical decision is overwritten. All results remain NOT_CERTIFIED / NO_TICKET.

## Actual executed evidence, 2026-10-30

The audit uses GitHub historical acquisition run **41018584742**, artifact **12959744855**, produced from commit `0171525a0cf84b132775a5e49f19bc62bda34605`. Its ZIP SHA-256 is `2da1810fab1197a343a53cd24f44feaa8f9f039b416a32bf4fb31dce004f0a81`. The archive's database SHA-256 before and after audit is `a65f8a4b66ae7b1e084500c860ac05aa637e4a15c8a655da76bfe2cbd992e96d`.

| Check | Observed result |
| --- | --- |
| Existing warehouse | 52,737 player-games; SQLite integrity OK; no duplicate official identities, missing receipts or canonical receipt disagreements |
| New, separate shooting database | 52,736 NBA/ESPN-crosschecked player-games with FGM/FGA, 2PT, 3PT, FT, minutes and explicit starter flags |
| Starting fives | 4,920 independently crosschecked team-games across 2,460 games |
| Shooting discrepancies | One profile quarantined because NBA and ESPN attempts disagree |
| Original coverage gaps | 213 positive-minute appearances remain absent from the input warehouse; seven zero-minute cases require explicit played-status evidence |
| Current-season collection | 66 completed ESPN player rows and shooting profiles collected for 2026-10-29; secondary staging only, zero promoted rows |
| Genuine historical pregame captures supplied to this run | None; no placeholder ledger or fake market history created |
| Exact-line production simulator trials in this run | Zero: required genuine snapshots and pregame context inputs are absent |

Yang Hansen's archived NBA name order prevented one team's full starting-five ID crosscheck. An explicit identity-only crosswalk uses his [official NBA profile](https://www.nba.com/player/1642905) and the unique exact canonical name/ID in the hash-pinned ESPN archive. It restores the affected team lineup and ten otherwise agreeing shooting rows. It never changes original names or game rows, and it does not implement fuzzy matching or automatic name reordering. The complete mapping and provenance are in `identity_crosswalks.json`.

This is an audit of the specified GitHub artifact. Separately saved v4.1 databases and their reconciliation receipts remain preserved and outside this artifact's scope. A source workflow failure is not evidence that every stored row is wrong; integrity, source agreement and coverage are reported separately.

## Real PBP alternative, with a retained conflict

The PBP Stats API was physically queried for NBA game `0022400001` (2024-11-12, Boston Celtics vs Atlanta Hawks). Saved responses contain 198 possessions and 38 quarter-level lineup combinations. Lineup totals conserve 240 regulation player-minutes per team, and possession durations conserve 2,880 regulation clock seconds. Eighteen of 19 played-player shooting profiles agree with the independently crosschecked box-score data.

PBP Stats reports Jalen Johnson with 17 FGA while the NBA/ESPN box-score sources agree on 16. Atlanta's possession FGA total consequently differs by one. Both disagreements are retained; the PBP game remains PARTIAL_PBP_SOURCE_CONFLICTS. PBP Stats is NBA-derived, so it is not another independent statistical authority. Quarter lineup aggregates also do not establish ordered substitution stints or pregame rotation forecasts.

## Repairs

1. `benfrank_v45_evidence.py` opens the input SQLite in read-only/query-only mode, validates each pinned source hash, rechecks original canonical records, game identities, schedule, scores, all seven counting stats, shot conservation and starters, and builds a **new** evidence database. Partial coverage returns exit 2 with explicit ledgers; source/integrity failure returns exit 1. Original database hashes are compared before and after.
2. `benfrank_v45_readiness.py` reads the separate `exact_line_snapshots` ledger, validates payload/column consistency, immutable hashes, original capture files and pre-tipoff ordering. It requires a stable game ID. Repeated or moved lines count as one selected player/market/platform/game outcome under a frozen first-capture policy. Fifty is only an exploratory execution minimum.
3. `benfrank_v45_odds.py` imports untouched historical The Odds API event documents, or collects with the user's `BENFRANK_ODDS_API_KEY`. It preserves the provider snapshot timestamp, platform and exact line. Live collector timestamps are not reused as historical timestamps. The raw response is hash-linked to every normalized line; a modified line cannot pass by reusing a different source response's hash. No provider request occurs without a key. Fantasy-score lines and scoring weights are not invented.
4. Player-team mapping is explicit. The Odds API outcome does not encode the player's team; unresolved rows retain both event teams and remain blocked. Once historical identity is resolved, a new derived snapshot ID links to the original capture instead of editing it.
5. `benfrank_v45_backtest.py` executes the **actual** 5-on-5 simulator for each eligible exact-line snapshot, with at least 25,000 trials, model/context hashes, actual counts and quantiles. It rejects actual rotations passed off as forecasts, same-day outcomes in feature history, wrong teams, mismatched game IDs, after-capture features, missing original context evidence, and unsupported fantasy scoring.
6. Backtesting uses simulator probabilities, alongside the historical hit-rate baseline and separately executed ML challenger. A global chronological holdout keeps each game on one side across all strata. Calibration is separate by platform, market, scoring contract and fixed line band. Reports include Brier/log loss, reliability, predictive interval coverage, MAE and a game-cluster bootstrap. Repeated captures do not become independent trials. No fitted calibration or sample count automatically promotes FULL.
7. The shared isotonic helper now pools tied probabilities before fitting and preserves monotonicity across differently sized bins. Snapshot export supports read-only connections without creating a table.
8. `benfrank_v45_pbp.py` retains real provider responses, validates game scope, identities, five-player combinations, minutes and possession shot totals, and preserves every detected conflict. Saved responses can be replayed without refetching.

## Execution

```bash
# New directory required; never use the input archive as output.
python benfrank_v45_evidence.py --archive-dir /private/history-artifact --out-dir /private/new-evidence

# Diagnose readiness against the separate ledger and original capture files.
python benfrank_v45_readiness.py --ledger /private/lines.sqlite --evidence-root /private/line-captures --out /private/readiness.json

# Import an original provider event response; resolve historical identity.
python benfrank_v45_odds.py --source-json /private/original-provider-event.json --evidence-dir /private/line-captures --ledger /private/lines.sqlite --warehouse /private/history-artifact/nba_warehouse.sqlite

# Actual simulator replay, only when genuine line/context inputs exist.
python benfrank_v45_backtest.py --warehouse /private/history-artifact/nba_warehouse.sqlite --ledger /private/lines.sqlite --evidence-root /private/line-captures --contexts /private/contexts/manifest.json --out-dir /private/new-backtest --trials 25000
```

The context manifest maps each **selected snapshot ID** to a relative JSON file. Each context must supply the existing Twon fields plus `game_id` (NBA ID), `input_mode: ASOF_PREGAME_FORECAST`, `feature_cutoff_utc`, `history_through_date`, and `evidence_files`. Each evidence item includes a relative `file`, `sha256`, `available_at`, and `kind` of `lineup_forecast`, `shooting_history`, or `pace_and_matchup`. Paths must remain inside the manifest directory. Original forecast data must be genuinely available before capture. Metadata/hashes alone do not independently attest a vendor's authenticity.

## GitHub execution and limits

The new `v45-certification-evidence.yml` workflow runs tests, selects the newest retained main-branch historical acquisition artifact (or an explicit run ID), audits it, reads the correct separate-ledger contract, checks one actual PBP sample, and saves exact readiness/backtest blockers. It performs no direct NBA endpoint retry and never treats a successful audit job as successful prediction certification. Private capture ledgers, account information, paid provider payloads and raw warehouse databases are not committed to the public repository.

GitHub artifacts retain 30 days. Preserve the private evidence package separately for durable reuse. Historical odds backfill requires actual existing captures or the user's approved provider access and applicable coverage. FULL still requires source-complete inputs for the target prop, genuinely timestamped pregame line/rotation evidence, source-conflict resolution where material, sufficiently broad market-specific held-out performance, independent challenger validation, and all stricter governing gates.
