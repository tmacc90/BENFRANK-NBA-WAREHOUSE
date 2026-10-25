# BENFRANK NBA v3.0 — Local starter engine

**Status:** executable proof-of-concept, not a production-certified predictive model. No official NBA data is bundled. No automatic screenshot parser or NBA data downloader is implemented yet. Not betting advice.

## Setup
Python 3.10+; **no pip dependencies**.

```bash
python engine.py --db nba.sqlite import your_game_logs.csv
python engine.py --db nba.sqlite predict --player 'Giannis Antetokounmpo' --market fantasy_score --line 53 --opponent CHA --asof 2026-10-24 > report.json
python -m unittest discover -s tests -v
```

CSV schema: `player,date,season,team,opponent,home,starter,minutes,pts,reb,ast,stl,blk,tov,fg3m`. Dates `YYYY-MM-DD`, season `2025-26`; home/starter 0 or 1. Include only verified game records. Team/opponent should use consistent abbreviations. All games in the database should be NBA regular season unless separately filtered upstream. Do not mix preseason/playoffs without extending the schema. No data is downloaded automatically.

## Markets
points, rebounds, assists, steals, blocks, turnovers, threes, pra, pr, pa, ra, fantasy_score. Fantasy scoring assumes `PTS + 1.2 REB + 1.5 AST + 3 STL + 3 BLK - TOV`; verify the platform's current contract before using.

## 24 windows
L3/L5/L7/L10/L12/L15/L20/L25/L30/L40/L50/L60; current season, previous season, two seasons ago, last three seasons; career, current team, starter, reserve; vs opponent L3, L5, current season and career. All windows are subsets of verified game logs; missing windows are labeled, not fabricated. Some windows overlap, so they are not independent samples.

Each window reports mean, median, standard deviation, raw exact-line MORE/LESS/PUSH counts, rates, average minutes and sample completeness. The preliminary baseline blends five correlated windows. This is a heuristic, not a validated independent predictive model. Baseline is computed from games without using the uploaded line. `--asof` excludes games on and after that date to avoid future leakage.

`--trials` defaults to 25,000 and runs an **empirical game-level bootstrap**, not the proposed sequential Digital Twon possession simulator. No injury, defense, matchup or game-script adjustments are currently available. All output is NO_TICKET until calibrated and independently validated. Never treat uncalibrated bootstrap rates as proven winning probabilities.

## Next implementation milestones
1. NBA official data source adapter, resilient retries and provenance with date/season validation.
2. Game type, minutes/availability, lineup and matchup warehouse tables.
3. Market-specific opportunity/efficiency models and uncertainty.
4. Sequential possession simulation and independent Blind AI/Hell tests.
5. Walk-forward backtesting, calibration, settlement audit and GitHub Actions.
6. Screenshot prop extraction with explicit line and game verification.

## v3.1 repair upgrade (upgrade.py)
The original `engine.py` remains available. `upgrade.py` adds schema migrations, an optional NBA Stats `nba_api` player-game-log importer, acquisition provenance, per-minute diagnostics, a second line-blind projection, a 16-scenario HELL sensitivity grid, multi-prop CSV controller, and walk-forward directional/MAE audit. No NBA historical games are bundled or invented. The NBA Stats API may throttle/block automated requests.

Install optional data adapter: `python -m pip install nba_api`

Examples (from this folder):
```
python upgrade.py --db nba.sqlite acquire --player 'Giannis Antetokounmpo' --player-id 203507 --season 2025-26
python upgrade.py --db nba.sqlite predict --player 'Giannis Antetokounmpo' --market fantasy_score --line 53 --opponent CHA --asof 2026-10-24 > report.json
python upgrade.py --db nba.sqlite batch props.csv --asof 2026-10-24 > batch_report.json
python upgrade.py --db nba.sqlite backtest --player 'Giannis Antetokounmpo' --market fantasy_score --line 53 > backtest.json
python -m unittest discover -s tests -v
```
Batch CSV header: `player,market,line,opponent,asof`.

The workflow `.github/workflows/test.yml` runs tests on push, manual dispatch and daily schedule **only after uploaded to GitHub**. It does not auto-fetch NBA data. Backtest uses a fixed historical threshold; it is not a calibrated trading or wagering edge. Matchup context is schema-ready but does not yet ingest verified defensive, injury or lineup records. `alternative_line_blind_model` is an independent formula, **not** an independent AI system. The 25,000 bootstrap trials are not possession-sequential Digital Twon. `NO_TICKET` remains mandatory until source-backed validation.

### Next required work
- Verify live NBA acquisition against real games in a network-enabled environment; validate season/player IDs, duplicate game IDs, starting status and game types.
- Add official injury and lineup feed and defensive matchup data with pregame timestamps.
- Build actual possessions and substitutions simulator, separate blind model, calibration and settlement audit.
- Add screenshot OCR/vision parser with human-readable confirmation of exact market, line and date.
- Add real-data integration tests and reproducible out-of-sample accuracy reporting.

## v3.2 controller (production.py)
Adds isolated robust per-minute blind *statistical* model, sequential minute-level box-score proxy, pregame evidence records with strict UTC timestamps, batch controller, and chronological blind-model point forecast audit. These are tested implementations, NOT a validated possession-level game engine or certified betting predictions.

```
python production.py --db nba.sqlite import-games verified_games.csv
python production.py --db nba.sqlite import-evidence pregame_evidence.csv
python production.py --db nba.sqlite predict --player 'Giannis Antetokounmpo' --market fantasy_score --line 53 --opponent CHA --asof 2026-10-24 --trials 25000 > result.json
python production.py --db nba.sqlite batch props_example.csv --asof 2026-10-24 > batch.json
python production.py --db nba.sqlite backtest --player 'Giannis Antetokounmpo' --market fantasy_score
python -m unittest discover -s tests -v
```

Evidence CSV columns: `player,game_date,kind,metric,value,source,observed_at`; observed_at must have timezone offset or Z, e.g. `2026-10-24T12:00:00-04:00`. By default, only evidence observed before 00:00 UTC of the game date is eligible; pass `--cutoff` with a timezone-aware pregame timestamp for later information. Never use post-tipoff evidence. These rows are reported, not yet used as automatically learned numeric matchup adjustments. Exact injuries, lineup and defensive schemes must be supplied from verified sources. Missing sources remain missing. All predictions are NO_TICKET until external walk-forward accuracy, probability calibration, and source validation pass.

The free `nba_api` acquisition adapter is still optional and has not been verified live in this runtime. For deployment install `nba_api` in a network-enabled environment and run `production.py acquire` for each player/season; confirm fetched records against official box scores. The GitHub workflow is not deployed.

## v3.3 NBA connection diagnostic
Run `python -m pip install -r requirements.txt` in an internet-enabled environment.
Run `python connect_nba.py --db nba_warehouse.sqlite --fetch --player 'Giannis Antetokounmpo' --player-id 203507 --season 2025-26` to backfill official NBA Stats player-game logs and record provenance. If NBA Stats blocks the connection, the importer reports a failure rather than inventing data. Run `python connect_nba.py --install --fetch` to attempt package installation first. An offline environment cannot install `nba_api` from PyPI without a pre-downloaded wheel.

## v3.4 Multi-source warehouse repair
`multisource.py` supports audited imports from ESPN, StatMuse, FOX Sports, Basketball-Reference and NBA official exports. These are *source labels*, not claims that their websites can be scraped automatically. Supply legitimately exported CSV or JSON with: date, season, team, opponent, home, starter, minutes, pts, reb, ast, stl, blk, tov, fg3m. Missing home/starter values are rejected rather than invented. Reconciliation retains each source in `source_games`, selects by authority, and logs field-level disagreements in `source_conflicts`. No game logs are fabricated.

Example:
`python multisource.py --db nba_warehouse.sqlite import --source espn --player 'Giannis Antetokounmpo' --season 2025-26 giannis_2025_26.csv`

Try public ESPN endpoint (raw schema review required):
`python multisource.py fetch-espn --athlete-id 3032977 --season 2026 --output espn_raw.json`

Audit:
`python multisource.py --db nba_warehouse.sqlite audit --player 'Giannis Antetokounmpo'`

Live network access is environment-dependent. The ESPN raw endpoint response is **not** silently treated as validated normalized game logs. The warehouse remains empty until actual valid records are imported. ESPN player ID must be independently verified before live use.

## v3.5 GitHub Actions acquisition deployment
A new `.github/workflows/acquire-nba.yml` installs `nba_api` on a GitHub-hosted runner, runs tests, attempts official historical acquisitions for configured seasons, runs `acquisition_gate.py`, and uploads the SQLite database and diagnostic receipts even if the data gate fails. The gate **fails closed** if any requested season has zero records, invalid rows, duplicate dates, or missing provenance. Passing unit tests is not evidence of successful live acquisition.

To activate: create or grant access to a GitHub repository, upload the **contents** of this folder to its root, enable Actions, and run **BENFRANK NBA verified acquisition** via workflow_dispatch. Inspect the workflow artifact and `gate.json`. Data from Actions artifacts must be downloaded or separately persisted; the runner filesystem is ephemeral. This is not deployed yet.

Known caveat: NBA PlayerGameLog may omit actual starting-status information. The existing official importer defaults a missing GS to 1; do **not** interpret its `starter` field as verified. Before production use, join a verified official box score starting-five source and require actual game identity, season type, and player ID verification. The acquisition gate currently checks structural validity, not starter truth or official box-score cross-source agreement.

## v3.7 public dataset staging
`acquire_parquet.py` supports local CSV, JSON arrays, and Parquet files with explicit source-to-canonical column mappings. All records are **staged**, never automatically promoted to verified NBA game history. Missing starter, home, or official game ID remain explicit uncertainties. Use only provider-permitted data files.

```
python -m pip install pyarrow  # only required for Parquet
python acquire_parquet.py historical.parquet --source nba_official --mapping column_map.json --db nba_warehouse.sqlite --output import_receipt.json
python warehouse_v36.py --db nba_warehouse.sqlite audit --player 'Giannis Antetokounmpo'
```

Column map example: `{"player":"player_name","date":"game_date","season":"season","team":"team_abbreviation","opponent":"opponent_abbreviation","minutes":"minutes","pts":"points","reb":"rebounds","ast":"assists","stl":"steals","blk":"blocks","tov":"turnovers","fg3m":"three_pointers_made"}`. **Do not assume these source column names are correct:** inspect the actual dataset schema first. Required fields: player, date, season, team, opponent, minutes, pts, reb, ast, stl, blk, tov, fg3m. Optional home, starter, source_game_id, season_type. Stage accepts missing optional fields and marks them unverified.

`.github/workflows/import-public-parquet.yml` is an on-demand GitHub Actions workflow for a permitted direct HTTPS dataset file. It must be deployed and executed separately. It outputs an artifact containing staged SQLite and an acquisition receipt. The URL and schema must be validated against the actual source before running. It does not auto-discover the dataset file or certify the records. No real historical records have been imported in this environment.
