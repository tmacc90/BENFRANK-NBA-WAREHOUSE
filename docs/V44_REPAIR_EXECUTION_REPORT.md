# BENFRANK NBA v4.4 — development repair pack (additive)

This upgrade runs new executable modeling and data-source modules without deleting or replacing the historical warehouse. Passing tests **never** automatically certifies betting accuracy.

## Implemented in this repair pack

1. `benfrank_v44_calibration.py` — chronological exact-line probability evaluation, using **only immutable pre-tipoff sportsbook snapshot records** (not fake lines), real game settlements, and a train/holdout cutoff that keeps all props from the same game on one side. Reports Brier, log loss, accuracy, and official-verification gaps. Does not fabricate missing historical sportsbook lines. Requires at least 50 eligible snapshots to fit and evaluate.
2. `benfrank_v44_blind_worker.py` and `benfrank_v44_blind_orchestrator.py` — separate Python process runs player-specific trained ridge regression on lagged pregame features. The worker receives **no uploaded prop line, primary projection, player name, opponent or final direction**, with input hash and model training count. This is process isolation, not an independently audited secure sandbox. ML is not yet calibrated.
3. `benfrank_v44_twon.py` — real executable *sequential* 5-on-5 game-state model with possession-level scoring, rebounds, assists, fouls, steals, blocks, substitutions, turnover attribution and up to two overtime periods. Models full 48-minute regulation rotations and checks 240 team minutes. Requires sourced two-team lineups, player shot attempts/efficiencies, pace, matchup rates and pregame timestamps. **The model is not yet calibrated against real possession play-by-play, and must not be labeled fully certified Digital Twon.**
4. `benfrank_v44_injuries.py` — timestamped ESPN secondary injury collection with exact-source digest and records. Absence from the injury feed never implies clearance. Official NBA injury authority, starters and minute limits still require additional crosschecks.
5. `benfrank_v44_batch.py` — provisional outputs now use OVER/UNDER and include the physically separated ML challenger plus disagreement result. Ticket certification stays NO_TICKET.
6. `.github/workflows/v44-physical-validation.yml` — tests actual real-data blind ML against prior GitHub historical warehouse. Separately executes **25,000** 5-on-5 trial runs on a clearly labeled **synthetic-input software test**. This does *not* establish production-calibrated trial results.
7. `.github/workflows/v44-injury-evidence.yml` — repeatedly collects secondary injury evidence with strict source handling.

## How to execute manually

```bash
python benfrank_v44_blind_orchestrator.py --db /path/verified_archive.sqlite --player 'Jalen Brunson' --market points --asof 2026-10-29
python benfrank_v44_calibration.py --db /path/verified_archive.sqlite --snapshots real_pregame_lines.json --out calibration_receipt.json
python benfrank_v44_twon.py --context sourced_game_profiles.json --player 'Jalen Brunson' --market points --line 25.5 --trials 25000 --output twon_receipt.json
python -m unittest discover -s tests -v
```

**Do not run sample lines as if they were current sportsbook lines.** Historical betting line snapshots must include actual capture timestamp, tipoff timestamp, market, player, platform, game, exact line and a unique immutable snapshot ID.

## Remaining production blockers and explicit fixes

| Stage | Current state | Unblocking evidence |
|---|---|---|
| Official NBA data | CDN returns 403 on GitHub Actions; NBA Stats may time out | Provider-authorized feed or independently reconciled source mirror, each game/player certified |
| Full 2026-27 historical warehouse | ESPN collection works but new rows are secondary staging only | Reconcile source identity, scores, minute/shot stats; promote only verified rows with immutable source hashes |
| Starter / full game roster | Not continuously independently verified | Capture official starting lineups, substitution rotations, DNP, foul/midgame exits and minute forecasts as-of |
| Real 25K production Twon | Simulation code exists, 25K fixture validation required | Sourced full rosters and possession inputs, 25K execution receipt per real prop, observed play-by-play calibration |
| Independent Blind AI | Child-process ML runs, but not validated on holdouts | Source-backed no-lookahead walk-forward challenger vs primary, predeclared model promotion thresholds |
| Prop probability calibration | Real-snapshot method implemented; true historical prop snapshots not yet guaranteed in warehouse | At least 50 uniquely identified valid pregame snapshots, official settlement and leak-free split; evaluate out-of-sample metrics |
| NBA markets | Existing engine supports 12 markets | Verified source and scoring adapter for each additional market; do not invent the missing 68 definitions |
| Durable archival storage | GitHub Actions artifacts expire in 30 days | Private encrypted object storage, retention/manifest checks, scheduled backup and restore validation |
| Ticket eligibility | NO_TICKET for every result | Independent end-to-end certification and performance audit; no automatic promotion merely from software tests |

**Important:** the repo is public. Do not publish historical warehouse databases, account data or paid sportsbook snapshots into public GitHub releases without licensing and privacy review.
