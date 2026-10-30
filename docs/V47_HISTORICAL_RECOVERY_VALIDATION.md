# BENFRANK v4.7 — repair receipt: saved official warehouse + legacy import diagnostics

## Actual completed verification (October 30, 2026)

The **original user-owned** `BENFRANK_NBA_v4_1_VERIFIED_WAREHOUSE.zip` was retrieved from their private file library in an authorized working container and audited **read-only**, using `benfrank_v47_verified_package.py`. Its database and original NBA Stats LeagueGameLog responses are not added to this public source repository.

- Original ZIP SHA256: `9ae4facc039f19306144849f48b1231f6c22a7a4d35a107730b5a93784af8462`
- Original embedded SQLite SHA256: `76bd45d13047e7e4b0bf7b26a1546c631e82ae81bdd221bb5781e3b76e33d64b`
- SQLite `PRAGMA integrity_check`: **ok**.
- LeagueGameLog 2024–25 response SHA256: `01b8baa55acd6d88bb1dc1c7b5e150fbcf61d1c8fa7c0b22d99546a36367ba58` — **26,306 of 26,306** distinct original player-game identities match.
- LeagueGameLog 2025–26 response SHA256: `2b192646f7a2bf4092667a72fee94b9da436a469f2dc6cb39240103e1134e00c` — **26,651 of 26,651** distinct original player-game identities match.
- Combined **52,957 / 52,957** source-linked historical player-games matched, **0 missing** in these two selected seasons, and zero observed source conflicts. NBA fields and archived canonical receipts were cross-checked. No user database was modified.
- Status: **PASS_COMPLETE_SELECTED_SEASONS_OFFLINE**, **NOT_CERTIFIED** predictions, **NO_TICKET**.

This supersedes the *incompleteness of the newer 52,737-row mirror reconciliation* only for the **two historical seasons represented in this original archive**. It does **not** prove that the GitHub Actions direct endpoint works; there is no basis for claiming that 2026–27 live games, injured players, pregame roster projections or every prop market are certified.

## Why existing GitHub historical import still fails

The previous main-branch `acquire-nba.yml` ran the original pinned *cross-source mirror import*, yielding 26,240 and 26,497 regular-season player-games and 251 + 359 discrepancy events. The separate direct NBA Stats verification step timed out for both seasons. These are **two independently observable blockers**. The recorded failures should not be hidden or waived.

The new `benfrank_v47_history_diagnostics.py` sorts every previously unstructured failure into explicit identity, starter, schedule and cross-source buckets and preserves the underlying evidence. The `acquire-nba.yml` report step now runs the diagnostic after an unsuccessful import (without falsely turning that job green).

The original complete source archive and the mirror importer represent **different acquisition methods and different completeness scopes**. When a complete original official-source archive is available, a cached original-response audit can verify historical coverage *without retrying inaccessible live endpoints*. Do not silently label secondary mirror rows as official.

## Run locally without upload

```bash
python benfrank_v47_verified_package.py \
  --archive /private/BENFRANK_NBA_v4_1_VERIFIED_WAREHOUSE.zip \
  --expected-db-sha256 76bd45d13047e7e4b0bf7b26a1546c631e82ae81bdd221bb5781e3b76e33d64b \
  --output /private/receipts/verified_original_archive.json
```

## Option to validate the original archive in GitHub Actions

`.github/workflows/v47-verified-original-archive.yml` runs offline source-validator regression tests on pull requests. A separate **manually dispatched** step can audit the original ZIP from private temporary storage if repository-maintainer secrets are configured:

- `BENFRANK_VERIFIED_ARCHIVE_URL`: a private time-limited **HTTPS** signed download URL for the original ZIP;
- `BENFRANK_VERIFIED_ARCHIVE_ZIP_SHA256`: `9ae4facc039f19306144849f48b1231f6c22a7a4d35a107730b5a93784af8462`.

The runner verifies the **full ZIP SHA256 before opening it**, rechecks the embedded verified SQLite SHA256, re-audits source receipts, deletes the ZIP after the run and uploads only summary JSON. It neither commits the archive to this public repo nor uploads the raw data as an Action artifact.

**These secrets have not been installed by this change.** Until a permitted private-download source and secret configuration exist, GitHub Actions cannot ingest an archive that is only available inside the user's ChatGPT file library. Do not invent a signed URL, commit a public copy, or misreport the manual workflow as executed.

## Remaining scope after this fix

This branch adds a reproducible complete selected-season offline historical audit and detailed failure accounting. FULL per-prop certification remains blocked by reliable as-of current-season injury/lineup authority, validated future minutes and matchup evidence, independent outcome settlement, sufficient strictly future held-out model calibration across markets, and ticket-release stages. Successful software unit tests are not evidence of predictive edge.
