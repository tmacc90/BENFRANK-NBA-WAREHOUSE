# BENFRANK NBA v4.1 official refresh

The original package was deployed and executed in GitHub Actions run 40153314955. It fetched zero games: all 44 CDN requests returned HTTP 403. The original package only captured evidence and could not update SQLite.

The repaired collector sends the NBA page Referer, limits requests to four workers, preserves each request attempt, checkpoints receipts, and treats HTTP 400/401/403/404 as terminal. Its local executed capture fetched all 44 final games and found the exact official player IDs for all 51 targets.

`reconcile_refresh.py` operates on a copy of the SHA-256 pinned v3.9 baseline (`e64f50b037f027fb6b8d1629bdfa739b4d73be99e207e01d9392f5692a4d5a76`). It checks IDs, final regular-season schedule, local league date, both teams and scores, home/away, five starters per team, explicit played/starter status, minutes and seven counting stats. It does not overwrite baseline games or fabricate ESPN matches. Rounded NBA archive seconds such as `21:60` are carried to 22 minutes and checked against precise official time. Zero-minute appearances require explicit official played status.

Two CDN assist totals disagree with the archived NBA Stats data. Promotion of those records requires newly fetched official Stats V3 box scores and official league logs to agree with all seven archived stats. The CDN disagreements remain in the receipt. These are multiple deliveries of the same statistical authority, not independent statistical providers.

New receipts are in `official_refresh_verifications`; original NBA/ESPN receipts stay in `game_verifications`. The `verified_history` view combines identities while leaving new ESPN IDs and hashes null. Audits and acquisition gates recognize both methods.

## Reproduce on the preserved baseline

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python refresh_and_audit.py --ledger v39_unresolved.json --out acquisition/official_refresh
python fetch_official_stats.py --games 0022400871 --seasons 2024-25 2025-26 --out acquisition/fresh_stats
python reconcile_refresh.py --baseline /path/to/v39/nba_warehouse.sqlite --ledger v39_unresolved.json --evidence acquisition/official_refresh --confirmation-dir acquisition/fresh_stats --out acquisition/reconciled_v41
```

The output directory must not already exist. A wrong baseline hash, duplicate identity, unsupported source discrepancy or missing evidence fails closed. Exit 2 means unresolved records remain. Capture success alone does not imply database import success.

## Execution evidence

Local reconciliation physically imported 51 records: 52,906 before, 52,957 after, zero unresolved targets, SQLite integrity ok, zero original rows changed or removed. An intermediate copied database failed integrity and was rejected; the accepted database was rebuilt from the preserved baseline in an isolated working directory with a copy-hash guard. The initial test run exposed two SQLite URI attachment errors, corrected before deployment. Full logs, earlier failures and final audits are supplied with the database deliverable.

GitHub Actions and local runs are distinct. The original failed GitHub run remains part of the evidence. Inspect later run receipts for remote capture results; the database reconciliation above was performed locally against the retrieved v3.9 baseline. No prediction or model certification is claimed: NO_TICKET.
