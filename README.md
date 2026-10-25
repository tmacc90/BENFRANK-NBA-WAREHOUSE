# BENFRANK NBA v3.7 — acquisition deployment repair

The saved v3.7 framework and its original modules are preserved. The original release notes are in [docs/ORIGINAL_V37.md](docs/ORIGINAL_V37.md). This repair adds reproducible historical acquisition and record-level reconciliation; it does not complete the proposed possession simulator, independent AI, injury feeds, or model calibration.

## Execute

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python acquire_history.py --seasons 2024-25 2025-26
python verify_direct_nba.py --seasons 2024-25 2025-26
```

The manifest pins the NBA Stats archive to a Git commit and pins all five input files by SHA-256. NBA Stats box scores and the final-game schedule are obtained through the SportsDataverse mirror; ESPN box scores are obtained through its separately produced ESPN archive. This does not establish direct access to NBA endpoints. Credits and license links are in [DATA_SOURCES.md](DATA_SOURCES.md).

Only final regular-season appearances are eligible. Exact official game/player IDs, season, date, team, opponent, seven counting stats, explicit home/away, starting status, and both team scores are checked. NBA box-score starting positions must form exactly five starters per team/game and agree with ESPN's explicit starter flags. ESPN minutes are rounded; a maximum one-minute difference is allowed. Names receive accent and punctuation normalization only; ambiguous or unmatched players are quarantined. DNP, playoff, play-in, and Cup-final records are excluded from the regular-season engine table.

Each source row and source hash is retained in SQLite. The legacy games table contains only reconciled rows from this importer, with a separate game_verifications identity and receipt table. Generic CSV/Parquet ingestion remains staging-only. The legacy NBA PlayerGameLog adapter no longer invents starting status and also stages its output.

acquisition/import_receipt.json records totals; failures_2025.json and failures_2026.json retain every rejection, discrepancy, and unmatched source row. Failure events can refer to the same player-game in both sources. database_audit.json independently checks the saved warehouse. No data fixture from unit tests is counted as imported history.

**Exit 2 means historical coverage is incomplete.** The database can contain real, reconciled records while the full acquisition gate fails. Do not change a failing acquisition into success merely because tests pass. For a changed source manifest, use a fresh database and retain the previous snapshot.

## GitHub Actions

- test.yml: software tests on push, PR, or manual run.
- acquire-nba.yml: historical import on relevant pushes to main or a manual run. Partial coverage fails the job. SQLite, raw sources, failure ledgers, and receipts upload even when the job fails. Artifacts expire after 30 days; download or persist them for long-term use.
- import-public-parquet.yml: manually stage a permitted HTTPS CSV, JSON, or Parquet file with an explicit column map. This workflow never claims official verification.

No recurring schedule is added by this deployment repair. Workflows are source files until a GitHub commit and actual run are observed. Local tests are not evidence of GitHub execution.

## Prediction limits

All predictions retain NO_TICKET. The original engine implements 12 markets, 24 statistical windows, a game bootstrap, a statistical line-blind formula, a minute-level proxy, and a sensitivity grid. These are not the complete 68-market framework, an independent AI system, or possession-level Digital Twon. No production simulation, probability calibration, walk-forward certification, current-season acquisition, live injury/lineup integration, or betting edge is claimed by this import.

## Execution status

A local baseline executed 33 tests and imported 52,737 cross-checked regular-season player-games across 2,460 games. Direct NBA Stats verification passed for all imported rows, while 220 official player-game records remained absent. The historical coverage gate therefore failed with exit 2. These are local baseline results, not evidence that GitHub Actions has passed. Inspect this repository’s Actions runs and downloaded artifacts for remote execution evidence.
