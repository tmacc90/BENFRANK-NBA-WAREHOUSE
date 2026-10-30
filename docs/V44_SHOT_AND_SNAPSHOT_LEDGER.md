# BENFRANK NBA v4.4 — immutable prop snapshots and real shooting-opportunity staging

This follow-up closes two practical infrastructure gaps without changing the production warehouse.

## Exact-line capture

`benfrank_v44_snapshot_ledger.py` stores original sportsbook lines in a **separate SQLite ledger**. Each unique `snapshot_id` is immutable: exact-line changes require a new ID; a repeated identical capture is idempotent. Pregame captured/tipoff timestamps are mandatory. A screenshot hash may be attached to establish a source-file fingerprint.

Example board JSON (illustrative; **not** an actual historical market snapshot):

```json
[
  {"player":"Example Player","market":"points","line":25.5,"opponent":"BOS",
   "game_date":"2026-10-29","platform":"Example Platform","snapshot_id":"example-001",
   "captured_at":"2026-10-29T12:00:00Z","tipoff_utc":"2026-10-29T23:00:00Z",
   "source_type":"MANUAL_ENTRY"}
]
```

Usage:

```bash
python benfrank_v44_snapshot_ledger.py --ledger /private/storage/benfrank-snapshots.sqlite --board captured_board.json
python benfrank_v44_snapshot_ledger.py --ledger /private/storage/benfrank-snapshots.sqlite --export captured_lines.json
python benfrank_v44_calibration.py --db /path/verified_nba.sqlite --snapshots captured_lines.json --out calibration.json
```

**Do not commit a private snapshot ledger, screenshot, or personal betting history into this publicly visible GitHub repository.** Use approved private storage or an encrypted private volume. Calendar dates and a synthetic board file alone do not create valid sportsbook history. No actual snapshots were found in the previously archived warehouse.

## FGA / 3PA / FTA ingestion

`benfrank_v44_shots.py` validates made/attempt pairs from completed ESPN player box scores and checks that 2PT/3PT/FT components add up exactly to points. The existing `espn_live_stage.py` current-season collector now writes these to an additional `player_shot_attempts` table in its isolated per-run `espn_staging.sqlite`.

Each staged shooting row records game, team, player, made/attempted totals, observed timestamp, source SHA-256, and `verified_official=0`. Missing or inconsistent shooting detail is not imputed. The production `games` table is not modified.

This starts accumulating the genuine shooting-opportunity inputs needed for the new 5-on-5 simulator, but is **not** yet a certified multi-season shooting-profile warehouse. ESPN is a secondary source; corresponding NBA authority or independent reconciliation remains required before production use.

## Still required for predictive certification

- Snapshot backfill from real pregame board captures (without retroactively inventing odds).
- Real rosters, starters, rotations and 240-minute availability forecasts sourced before tipoff.
- Enough verified historical attempts and context to parameterize player-specific 25,000-trial simulations.
- Independent official settlement, per-market leakage-free probability backtesting, and model validation.
- Durable private data storage beyond GitHub Actions 30-day artifact retention.

All betting selections remain `NO_TICKET` until required evidence gates pass.
