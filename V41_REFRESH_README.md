# BENFRANK NBA v4.1 — Evidence refresh deployment bundle

The workflow fetches **official CDN evidence** for 44 NBA games spanning 51 unresolved player-games in the v3.9 ledger. It validates game ID and final status, stores original JSON and SHA256 receipts, and extracts player-ID statistics when present. **It does not import records into SQLite or certify full acquisition.** Official NBA CDN cannot necessarily resolve historical JSON; failed fetches are individually logged and fail the workflow while retaining artifacts.

## Install
Copy `refresh_and_audit.py` and `v39_unresolved.json` to the GitHub repository root, and `.github/workflows/refresh-unresolved.yml` to the same path in the repository. On GitHub, open **Actions > BENFRANK official unresolved refresh > Run workflow**. A push adding the three files also triggers it. It requires internet on the GitHub runner and `actions/upload-artifact`.

## Local
`python refresh_and_audit.py --ledger v39_unresolved.json --out official_refresh`

Optional read-only database row audit: add `--db /path/to/nba_warehouse.sqlite`. The script does not modify that database.

## Status
`v39` baseline verified 52,906 player-game rows; unresolved 51 player-game records. No v4.1 online fetch is claimed. GitHub API write returned 403 on this attempt, so the workflow has not been deployed or executed from this chat.
