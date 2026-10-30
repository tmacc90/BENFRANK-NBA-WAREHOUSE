# v4.6 certification data recovery

This additive repair preserves both the saved v4.1 warehouse and the newer GitHub import. FULL is a per-prop, evidence-backed release decision under the inherited 66 stages. A working repository or a complete historical season does not grant it automatically.

## Executed source recovery

The saved `BENFRANK_NBA_v4_1_VERIFIED_WAREHOUSE.zip` contains **52,957** player-games, all **2,460** regular-season games in 2024-25 and 2025-26. `benfrank_v46_saved_history.py` rechecks every record against the saved original official LeagueGameLog responses and their original acquisition hashes. Both seasons pass, with zero missing official identities, duplicate identities or counting-stat conflicts. The newer GitHub artifact has 52,737 rows; every one is present and identical in v4.1, which contains 220 additional records. Neither database is modified. The complete saved database hash remains `76bd45d13047e7e4b0bf7b26a1546c631e82ae81bdd221bb5781e3b76e33d64b`.

This establishes coverage for those selected seasons and their official league logs. It does not establish current live endpoint access, other seasons, shot profiles, historical injuries or every governing requirement. The current direct NBA endpoint failure is not grounds for discarding previously retrieved, hash-verified historical responses.

The public [PrizePicks collector archive](https://github.com/enkday/prizepicks-data-mirror) supplies an additional free research route. The 67 frozen commits in `configs/v46_public_capture_commits.json` cover February 1 through April 12, 2026. Recovery downloaded all 67 with no fetch failures and linked **13,117** lines to verified player-game settlements across **498** games. Exact source rows, raw JSON, pinned URLs, collector timestamps, commit timestamps and file hashes are retained. Unsupported markets, modified captures, uncertain player identities and material schedule conflicts are rejected. The official NBA scheduled time takes precedence over a provider's delayed displayed start time.

The collector is secondary. Its commit timestamps are metadata, not independent timestamp attestations, and its normalized publication is not an authenticated native platform response. The ledger explicitly retains `SECONDARY_PUBLIC_COLLECTOR_NOT_PLATFORM_ATTESTED`. It cannot claim stronger authenticity by changing a flag. No fantasy-score contract is invented.

## Measured research

First-capture outcome selection reduces the 13,117 linked rows to 13,077 selected outcomes. After 305 pushes and 15 insufficient-history cases, the empirical baseline has 12,757 eligible outcomes. It evaluates 26 separate platform/market/line-band strata with one global game-grouped chronological holdout. These are baseline results, never substitute simulator results.

The actual 5-on-5 simulator has also executed 25,000 sequential trials on Jalen Brunson's archived February 1, 2026 points line of 26.5. Its context uses only earlier verified game and shooting history, conserves 240 minutes for both teams, and is explicitly a retrospective reconstruction. It is not a live pregame prediction. The source forecast was constructed on October 30; historical injury and coach-news evidence is not backdated.

`benfrank_v46_research_backtest.py` extends that test to a frozen, temporally spaced cohort in the points 25-to-30 line band. Cohort selection uses source/context eligibility without filtering outcomes. Every accepted exact line gets its own actual 25K simulation receipt, seed, context hash, raw probabilities and separate-process blind challenger. Context gaps are excluded and retained. Calibration and Brier/log loss, interval coverage and game-cluster uncertainty use the actual simulator predictions. Every result remains research / NO TICKET until production evidence and promotion requirements pass.

The binary score helper now treats an exact 0.5 probability with an explicit frozen OVER tie rule and reports the tie count. Previously such cases counted as incorrect regardless of the actual outcome. Probability metrics retain their existing definitions.

## Reproduce

```bash
# Read only; use the already saved original v4.1 package.
python benfrank_v46_saved_history.py --package /private/v41-original --baseline /private/github-import/nba_warehouse.sqlite --out /private/saved-audit.json

# New output directory; retrieve pinned public captures without a paid API key.
python benfrank_v46_public_lines.py --commits configs/v46_public_capture_commits.json --warehouse /private/v41-original/nba_warehouse.sqlite --out-dir /private/new-lines

python benfrank_v46_baseline.py --warehouse /private/v41-original/nba_warehouse.sqlite --ledger /private/new-lines/snapshots.sqlite --evidence-root /private/new-lines --out-dir /private/new-baseline

# Actual simulations on reconstructed prior-history forecasts; this may take several minutes.
python benfrank_v46_research_backtest.py --warehouse /private/v41-original/nba_warehouse.sqlite --shooting-database /private/verified_evidence.sqlite --ledger /private/new-lines/snapshots.sqlite --evidence-root /private/new-lines --sample-size 100 --workers 6 --out-dir /private/new-research-backtest
```

The GitHub v4.6 workflow independently reruns source recovery and the empirical baseline using the latest retained GitHub import. That import can still have fewer historical rows than the saved v4.1 package. The saved-history audit and the actual simulation study have their own receipts. A successful workflow does not silently inherit the stronger source scope of another input database.

## Remaining release requirements

Public line capture and complete selected-season logs remove two data acquisition obstacles. Production FULL still requires source-backed pregame availability/rotation and matchup evidence for the actual prop, a validated simulator and independent challenger, adequately powered held-out calibration, a documented promotion policy evaluated out of sample, final line/availability rechecks, and all applicable inherited governing gates. Research receipts never auto-promote themselves or rewrite an earlier decision.
