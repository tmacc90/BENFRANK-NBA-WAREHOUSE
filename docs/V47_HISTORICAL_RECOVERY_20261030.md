# BENFRANK v4.7 Historical-Source Repair: independently verified 2026-10-30

This is an additive, fail-closed repair. Production code, archived source data, previous model measurements, and every pre-existing receipt remain untouched. Passing historical integrity does **not** imply model or wagering certification.

## Recovered complete source (external to GitHub)

Original owned Library file: `BENFRANK_NBA_v4_1_VERIFIED_WAREHOUSE.zip`.
Local physical source ZIP SHA-256: `9ae4facc039f19306144849f48b1231f6c22a7a4d35a107730b5a93784af8462`.
Its internal `nba_warehouse.sqlite` SHA-256: `76bd45d13047e7e4b0bf7b26a1546c631e82ae81bdd221bb5781e3b76e33d64b`.

On 2026-10-30, the saved ZIP was physically unpacked **outside the repository**. Its manifest and actual database hash agreed; SQLite `PRAGMA integrity_check` returned `ok`. Independent comparisons against both included original pinned `LeagueGameLog` JSON responses returned:
- 2024–25: 26,306 unique official game/player identities; 26,306 DB rows; zero missing identities; zero date/team/counting-stat discrepancies.
- 2025–26: 26,651 unique official identities; 26,651 DB rows; zero missing identities; zero date/team/counting-stat discrepancies.
- **52,957 total rows covering the selected seasons**.
- Official identity used `GAME_ID + PLAYER_ID`. Differences in Unicode/accent/punctuation and name suffixes (e.g. "Jr.") are **display-name aliases**, not game-stat conflicts; no player identities were guessed. Full source files and their hashes remain separately preserved.

These observations establish historical selected-season record completeness **with cached original official responses**, not current direct NBA endpoint accessibility or 2026–27 season coverage.

## Existing GitHub import remains partial

The latest `acquire-nba.yml` run against third-party NBA/ESPN archive mirrors reported 26,240 + 26,497 = 52,737 crosschecked records, 251 + 359 = 610 discrepancy events. Separate live `stats.nba.com` requests timed out. Its output may be internally consistent but is *not* the preferred complete selected-season historical source. Do not quietly call this run a success or erase its failure logs.

`benfrank_v47_history_diagnostics.py` now groups each retained discrepancy by failure category. The existing acquisition workflow writes `acquisition/failure_diagnostics.json` and an Actions summary on failure. That workflow remains honest (nonzero exit when no full coverage) and does not rewrite its inputs.

## New offline archive validation path

`benfrank_v47_saved_history_ci.py` checks a saved ZIP, requiring the exact pinned database hash. It safely extracts only the historical database, original receipt and two saved official NBA league response JSONs, then invokes the existing, independently tested `benfrank_v46_saved_history.audit_saved_history`. An optional pre-existing mirror-import SQLite database may be compared read-only. Missing original receipts, hash mismatches, changed baseline rows or the archive being absent fail closed.

`.github/workflows/v47-offline-history-restore.yml` can run the same verification on GitHub Actions **when the owner's original package has been made accessible as a protected GitHub Actions artifact**. It downloads the source by authorized run ID/artifact name, validates the original pinned SHA, and publishes **only the audit receipt**, not the large source database or original source JSONs.

The original full package presently exists in the user's ChatGPT Library, **not in a GitHub Actions artifact** accessible to this workflow. The code is deployed and the offline user-owned archive has been inspected locally, but do not report successful GitHub-side archive restoration until that transfer and workflow execution have happened. Because this GitHub repository is public, do not publish the raw ZIP or SQLite into the repository or a public release. Moving a raw user archive to other storage requires an approved private destination/access mechanism.

## Remaining release gates

- A durable, authorized source for the verified historical package on GitHub Actions; the offline audit code cannot fetch a ChatGPT Library file itself.
- Official/independent current-game lineup, injury, playing-time and team/matchup evidence, as-of each candidate prop.
- Fresh 2026–27 player game coverage and checked current exact-line snapshots.
- Broader independent prospective testing; v4.7 32-game October points-only test did not establish a statistically significant Brier improvement over baseline.
- All applicable market adapters, platform-specific scoring contracts, pregame evidence and 66-stage governing/ticket-authority checks. `NO_TICKET` remains required without certification.

The next priority is authorized delivery of the **already verified original package** into protected GitHub Actions storage, followed by the offline verification workflow. Do not substitute another nominally green unit-test job for that physical full-data execution.
