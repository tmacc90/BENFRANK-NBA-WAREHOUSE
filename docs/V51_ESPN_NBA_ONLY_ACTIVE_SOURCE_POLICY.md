# BENFRANK NBA v5.1 — ESPN.com and NBA.com as the Only Active Collection Providers

**Effective source policy for production GitHub Actions:** `.github/workflows/v51-multi-source-evidence.yml` calls only ESPN-owned and NBA-owned domains. The optional third-party archive modules still exist for historical research and tests, but **are NOT invoked by the scheduled pipeline**. Secondary PrizePicks collectors are not invoked. Nothing is deleted from the existing historical warehouse.

## Verified data pathways

| Required NBA evidence | Primary endpoint/source | What this proves / does not prove |
| --- | --- | --- |
| Scoreboard, games, teams, dates and game IDs | `site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=YYYYMMDD`; `cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json`; NBA live scoreboard | ESPN secondary / NBA primary when reachable; no guessed games, date-specific as-of policy |
| Current and career player box scores, minutes and 20+ count markets | Completed ESPN `summary?event=GAME_ID` and historical saved verified NBA boxes | Points, rebounds, assists, threes, field-goal makes/attempts, free throws, steals/blocks/turnovers, two-point attempts; validated equations |
| Shooting profile and shot coordinates | Each played field-goal `shootingPlay` in ESPN completed-game `summary.plays`; NBA CDN PBP when accessible | Observed source coordinates, shot makes, type, time and play identity. Physical court coordinate conventions and defender assignment require separate validation |
| Historical possession/rotation context | ESPN `summary.plays`, original NBA CDN `playbyplay_{game_id}.json` if reachable | Ordered events as observed; neither individual possessions nor on-court lineup for each play are certified without substitution reconstruction |
| Historical starters | `ESPN completed summary.boxscore.players` observed starters, NBA final box starters if accessible | Historical after-game reality; NOT tomorrow's verified starting lineup |
| ESPN-listed current pregame starters | ESPN future scoreboard and pregame `summary?event=` captured *before* actual tipoff | A row only if ESPN explicitly marks `starter: true`; source tier **ESPN_PREGAME_LISTED_STARTER_NOT_OFFICIAL**; zero claims of official five-player certainty |
| Official injury and availability statuses | Original printed NBA PDF via `official.nba.com` with printed time matched against UTC retrieval; `site.api.espn.com/.../injuries` separately | Original dated PDF is authoritative for listed statuses, but absence from it is UNKNOWN, not healthy; no inferred late scratch or minute cap |
| All team rosters and identity | ESPN `.../teams` and `.../teams/TEAM_ID/roster` for each 30 teams | Membership only, not starter confirmation |
| Matchup/news/coach context | ESPN `.../news` and observed NBA/ESPN game history | Editorial clues and completed-game rates only; no invented defensive coverage, tracking measurements or minutes |
| Cross-source settlement evidence | Check NBA CDN official completed box scores vs ESPN finalized same-game player stats when **both sources actually respond** | Each NBA player ID, ESPN event ID and twelve matching counting-stat fields; discrepancies quarantined rather than silently reconciled |
| Genuine native PrizePicks player prop snapshots | **NOT provided by ESPN.com or NBA.com** | Still requires captured original platform screenshot/receipt or an authorized native feed. An NBA game point spread is not a specific player's PrizePicks line |

## Source availability: actual GitHub Actions observations

The first v5.1 protected-branch live collection at `https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/runs/41157922226` retrieved five of seven public source endpoints, all **30 ESPN rosters**, and parsed the original NBA injury PDF. Both NBA CDN schedule and scoreboard returned **403 Forbidden** from the GitHub-hosted runner. Consequently **0 direct NBA CDN player box scores and 0 official PBP action sequences** were retrieved by that run. These are external provider restrictions. The code will attempt legitimate direct access on later runs and report exactly what was retrieved; it does not disguise a third-party archive as an official response or circumvent provider restrictions.

The direct ESPN game-detail fetches automatically produce a separate source-hashed SQLite dataset with completed game boxes, raw play actions, and observed shot coordinates, eligible only on games strictly **before** the requested game date. The pregame snapshot capture never recreates a historically missing lineup by pretending it was captured before tipoff. Original source files, hashes, malformed-player exclusions and failed provider calls are retained.

## Correctness and remaining certifications

The included contract and offline end-to-end regression tests cover completed event identity, teams, Eastern Time game date, field-goal scoring conservation, PBP/shot coordinates, no post-tipoff lineup capture, never inferring a fit/injured player, and `NOT_CERTIFIED/NO_TICKET` enforcement.

Provider data availability is separate from predictive accuracy. A successful auto-collection does not run 25,000 sequential trials for every prop, nor complete Blind AI calibration, exact sportsbook line authentication, confirmed final starters or retrospective/out-of-sample win-rate verification. Those stages can only advance on physical execution receipts with adequate real pregame inputs.

## How to run

From GitHub Actions select **BENFRANK v5.1 automatic official and secondary NBA evidence** and choose **Run workflow**, optionally setting `target_date` to an upcoming Eastern NBA game date. The workflow also runs at UTC 02:15, 14:15, 20:15 and 23:15 daily. Inspect the job summary and `benfrank-v51-multi-source-evidence-<run_id>` artifact for per-source status, raw SHA256 receipts, ESPN pregame source rows and original NBA PDF.

The 52,957 original archived official NBA player-game rows are never overwritten; these outputs are new source-stamped research artifacts.
