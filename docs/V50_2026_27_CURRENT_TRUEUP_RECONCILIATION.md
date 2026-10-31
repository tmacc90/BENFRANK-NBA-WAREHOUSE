# BENFRANK NBA v5.0 — 2026–27 current-game true-up and retrospective audit

## Purpose and safety

This additive source-backed challenger addresses a specific systematic limitation: the previous 45-prop screenshot evaluation used only 2024–25/2025–26 historical records and did not reflect 2026–27 actual recent minutes, rates, or new team assignments. No frozen previous model, original official warehouse, production results or user prop snapshot is rewritten.

**The goal is improved forecast research, not a false FULL or winning-probability certificate.** Every output remains `NO_TICKET`; per-prop 25K research bootstraps are not the independently calibrated full possession Digital Twon.

## Physically executed October 30, 2026 as-of data recovery

- Original saved 2024–25/2025–26 official NBA LeagueGameLog warehouse: **52,957** archived verified player-game records, unchanged.
- v4.9 supplementary source-validated shooting ledger on that saved archive: **52,913** rows; another 44 have explicitly unfilled extra-shooting fields and remain quarantined.
- A new 2026–27 current-season source run collected **1,382** nonzero-minute player-game records from ESPN secondary finalized game summaries before October 30 (excluding source-unavailable Oct 26).
- `benfrank_v50_recover_espn_gap.py` recovered **210** additional previously absent records from 13 individually checked Oct 26–27 final-game summaries, making **1,592** source-backed observed current-season rows on dates October 20–29.
- Three source zero-minute entries were explicitly excluded rather than treated as game appearances. The 13 final games were independently checked for event identity, Eastern Time date, opponents, completion status and nontrivial player coverage. A changing ESPN JSON body hash alone never overwrites a previously saved consistent game/row; genuine counting-stat conflicts are quarantined.
- The ESPN source can be revalidated through GitHub Actions; it remains secondary and does **not** become official NBA independent box-score verification by passing integrity checks.
- No player game dated October 30 or later is eligible for an Oct 30 pregame reconstruction. This was executed after some games may have started and is accordingly **retrospective as-of reconstruction**, *not* an original live pregame pick ledger.

## Source-backed availability limits

A genuine official NBA injury report printed **2026-10-30 4:45 PM ET** was preserved with an evidence receipt from **2026-10-30T21:07:46Z**. It lists Indiana's Tyrese Haliburton and T.J. McConnell as Out, Andrew Nembhard and Aaron Nesmith as Probable, and Obi Toppin as Questionable, among other statuses. Minnesota's Anthony Edwards and Donte DiVincenzo are listed Out. An unlisted player is **UNKNOWN_NOT_CLEARED**, not confirmed healthy. This report does not establish final lineup, in-game starting five, rotation minutes or lineup lock. The empirical true-up retains these risk flags but **does not fabricate a numerical minute transfer**.

## What the v5.0 estimator actually does

- Reads original 2024–26 records, joins genuine v4.9 observed shooting components where available, and retrieves 2026–27 played game rows.
- Resolves only a source-supported player identity alias (Bobby Portis Jr. from screenshot versus Bobby Portis in the original NBA/ESPN records). All other names use accent/punctuation-normalized exact identity, never fuzzy guesses.
- Starts with the prior historical exact-line-independent window blend (L5, L10, L20, most recent season, previous season).
- Shrinks the 2026–27 player's stat-per-minute output toward about six prior-games' exposure, blends recent current-season minutes against a four-game historical role prior, caps unreasonable adjustments, and adds at most 5% strongly shrunk defensive context only when prior full-team box scores exist.
- Never uses any game's final results as features for that same game. The official injury report is recorded separately rather than fabricating a role change.
- Can be invoked with `python benfrank_v50_trueup.py --board <private_json> --historical-db <original_copy> --current-db <2026_27_artifact> --target-date 2026-10-30 --output <new_json>`. The personal 45-prop board stays outside this public repository.

## Actual 45-prop research rerun

On the owner's original 52,957-row warehouse joined to the full 1,592-current-row pre-Oct-30 database, **all 45 screenshot props received a current-season player-history match**, and **9 historical-only OVER/UNDER directions changed**. A total of **1,125,000 observed-game bootstrap resampling draws** ran across the 45 separate exact lines; those draws remain uncalibrated and are not possession-level simulator trials.

The corrected context changes specific lines, but a changed direction is not inherently a better prediction. The full exact-line comparison, trial distributions and injury-risk flags are exported separately in the owner's local evaluation archive, not committed as private bet-board content.

## As-of chronological outcome error benchmark

To test a measurable outcome rather than assertion, a *retrospective chronological* evaluation used **1,039 player-game outcomes across 57 previously completed NBA games** through Oct 29. Each case uses the historical 2024–26 warehouse and only **earlier** 2026–27 player games. The opponent-context signal likewise excludes the held-out game's own stats. The same cohort was evaluated using unchanged historical-window-only estimates and the new current-season rate/minute/limited-defensive model.

| Market | Historical baseline MAE | New true-up MAE | Difference (new minus old) |
| --- | ---: | ---: | ---: |
| Points | 5.247 | **4.930** | -0.317 |
| Rebounds | 2.124 | **2.031** | -0.093 |
| Assists | 1.479 | **1.405** | -0.075 |
| Threes made | 0.980 | **0.947** | -0.033 |
| Field goals made | 2.004 | **1.879** | -0.125 |
| Two-point attempts | 2.392 | **2.208** | -0.185 |
| Fantasy score (specified illustrative contract) | 9.062 | **8.442** | -0.620 |
| PRA | 7.148 | **6.523** | -0.625 |
| Rebounds + assists | 2.986 | **2.803** | -0.183 |

This is *outcome error*, **not** a verified PrizePicks historical exact-line OVER/UNDER win rate. Outcomes are from ESPN secondary box scores and the test was retrospectively constructed, not an immutable originally-issued pregame prediction ledger. A bootstrap over game IDs, instead of individual correlated player-markets, was used for descriptive confidence diagnostics; this does not remove source/schedule/season sampling bias. These comparisons must not be used to grant model certification or prove betting profitability.

## Reproducibility and remaining releases

- `benfrank_v50_current_asof.py`: collects pre-target completed 2026–27 games, validating shooting and nonnegative, nonzero minutes.
- `benfrank_v50_recover_espn_gap.py`: source-dated final-game recovery when ESPN's date scoreboard endpoint fails.
- `benfrank_v50_trueup.py`: general read-only role/rate shrinker with exact-line decisions, no invented current game data.
- `.github/workflows/v50-current-asof.yml`: produces source SQLite and immutable collection/recovery receipts; designed for manual future as-of target parameters. Can run against 2026–27 dates only.
- Unit/contract tests cover the target-game cutoff, source bounds, output uncertainty, immutable source overwrite policy and no automatic ticket release.

To claim **FULL** on a specific player prop still requires as-of verified final starters/minute restrictions, genuinely timestamp-attested pregame lines, official/independent box-score settlement, a source-backed 25K sequential possession simulation per exact line, independent Blind AI and calibration on a new prospective cohort. The earlier v4.8 gates remain controlling: **NOT_CERTIFIED / NO_TICKET**.
