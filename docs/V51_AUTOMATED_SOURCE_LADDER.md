> **Update — current governing workflow:** The user selected **ESPN.com and NBA.com only** for active scheduled source ingestion. See [V51_ESPN_NBA_ONLY_ACTIVE_SOURCE_POLICY.md](V51_ESPN_NBA_ONLY_ACTIVE_SOURCE_POLICY.md). Third-party archives and public line collectors described below remain **optional research code only** and are **not run in the scheduled workflow**. Provider-restricted NBA CDN results remain blocked rather than substituted as official.

# BENFRANK NBA v5.1 automatic source acquisition and certification gaps

## Real execution evidence (October 30, 2026)

The first protected-branch GitHub Actions source run (41157922226) finished successfully as an **acquisition audit**:

- 5/7 raw allowlisted provider endpoints were retrieved and SHA-256 pinned. NBA CDN season schedule and current scoreboard both returned HTTP 403 to the GitHub-hosted runner. No attempt was made to bypass the provider restriction or impersonate a privileged account.
- ESPN's team index plus all **30 current NBA team roster endpoints** were successfully collected. This is roster membership, **not** confirmed pre-tipoff starters, injury clearance, or minute restrictions.
- The original official NBA 2026–27 injury PDF was retrieved and parsed, recording 33 team/game reports. The PDF and its printed report time are preserved. Unlisted players and teams without submissions remain UNKNOWN.
- Direct original NBA CDN past-game boxes and PBP currently remain **blocked** at that runner, and no independent NBA-vs-ESPN current-game player crosschecks can be claimed from this source path.

The scheduled v5.1 pipeline now also attempts **versioned, third-party redistributed public releases** for the current ending-2027 season, so that the same official CDN 403 cannot prevent every nonofficial research feed.

## Automated source ladder

| Evidence category | Live collector or source | Provenance and trust | Released use |
| --- | --- | --- | --- |
| Completed NBA box scores, minutes, rebounds, makes and attempts | Official NBA CDN `boxscore_{game_id}.json`; ESPN final game summary and 2027 player-box release fallback | Direct NBA source only if actually retrieved; otherwise ESPN secondary or NBA-origin republished mirror | Historical role and scoring features only for games strictly earlier than prediction target |
| NBA schedules and identity | NBA CDN official schedule; ESPN `scoreboard?dates=`; existing pinned NBA-derived schedule master | Explicit NBA/ESPN source tiers, hashed | Never use a scoreboard from after tipoff as pregame verification |
| Player and team shots, shot location | SportsDataverse public `espn_nba_shots` ending-2027 Parquet | ESPN SECONDARY | Empirical shot profiles where date is verified; not tracking or a guaranteed field-goal forecast |
| Full possessions and play-by-play | Direct NBA CDN `playbyplay_{game_id}.json`; fallback SportsDataverse `espn_nba_pbp`, `nba_stats_pbp`, `nba_stats_possessions` | Direct / mirror separately labeled | Offline possession and rotation research; missing exact pregame role blocks certified Twon |
| Lineup and substitution histories | SportsDataverse `nba_stats_game_lineups`, `espn_nba_game_rosters` | Official-derived mirror or ESPN secondary, *historical game observations* | Historical starting five and lineup rates only; **not** next-game confirmed starters |
| Current team membership | ESPN site API teams index and all 30 team rosters | ESPN secondary, current retrieval timestamp | Candidate participant pool only; absence from injury PDF not confirmation |
| Injury and player availability | Original dated PDF via official.nba.com plus ESPN injuries secondary source | NBA primary document (verified header) or ESPN secondary | Listed source statuses with printed timestamp; never assume unlisted players are healthy |
| Coach/role updates | ESPN timestamped NBA news feed; team-issued PR only with independent source | News/editorial source, not lineup confirmation | Risk annotation, must be tied to exact player/team and as-of time |
| Exact-line historical public collector | Secondary archived `enkday/prizepicks-data-mirror` latest SHA, original `scrapedAt` and commit time | **SECONDARY collector, not native PrizePicks certified** | Historical research and as-of candidate snapshot where pregame timestamp is verifiable |
| Genuine native PrizePicks player-prop snapshots | Authorized platform API or directly captured authenticated primary receipts | **NOT CONNECTED.** No invented source or rate-limit evasion | Await an explicitly authorized provider connection or user-uploaded immutable screenshots |
| Opponent defensive scheme, player tracking and defender assignment | NBA.com/stats tracking/defense and other specialist providers | Provider terms/access conditions apply; CDN/CDN-mirror stats ≠ tracking coverage | Partial efficiency/possessions from public evidence; do **not** claim full defensive scheme reconstructed |
| Rookie college/G League history | SportsDataverse MBB sources; NBA G League official stats if authorized | Separate league + identity crosswalk + season translation required | Supplemental priors only; do not merge into NBA box-score outcome tables without provenance |
| Full predictive calibration | Own immutable pregame forecast and later independently reconciled outcomes | Must actually issue prediction before event and score as-of | Not solved by adding a feed; requires prospective walk-forward testing and independent blind model |

Public mirror releases can be read through the maintained SportsDataverse release tags at `https://github.com/sportsdataverse/sportsdataverse-data/releases` and the upstream original project `https://github.com/sportsdataverse/hoopR-nba-stats-data`. Published mirror timestamp is **not** proof that official NBA itself was directly available at the same time.

## Scheduled automation

`.github/workflows/v51-multi-source-evidence.yml` runs every day at **02:15, 14:15, 20:15 and 23:15 UTC**, and on manual workflow dispatch with an optional as-of game date. Every run:
1. Tests schema, source host, game-date exclusion, shooting accounting, identity and line provenance.
2. Captures source response bytes and SHA-256/UTC receipts, plus explicit 403/429/error reasons.
3. Fetches team rosters, source-grounded historical NBA final game boxes/PBP when directly accessible, and secondary ESPN final boxes.
4. Falls back to public versioned 2027 Parquet assets for box-score, shots, PBP, lineups, possessions, team stats and roster history; only **rows with validated dates strictly earlier than the requested target game date** are eligible for as-of modeling.
5. Performs independent NBA/ESPN player counting-stat source checks only if both sources actually load.
6. Attempts original dated NBA injury PDF validation and latest public secondary collector exact-line capture; neither clears unknown lineups nor attests a native wagering line.
7. Publishes separate original source receipts, quality issues and isolated SQLite/Parquet research sources as 30-day GitHub Actions artifacts. Previous verified warehouse and production code remain unmodified.

## FULL vs research execution

A successful automated collection is evidence **availability**; it does **not** grant predictive certification. An actual production candidate still needs immutable, pretipoff exact-line and team context, confirmed starters/rotation risk, independent blind challenger, 25K genuinely sequential possession trials **for that exact line**, prospective model calibration and scored outcomes. The v4.8 certification release authority stays **NOT_CERTIFIED / NO_TICKET**.

The public multi-source collection stack is intentionally additive and fails closed for missing/unauthorized providers. No proprietary API keys are distributed or guessed. GitHub-hosted runner limits do not justify claiming that blocked NBA CDN data was successfully downloaded.
