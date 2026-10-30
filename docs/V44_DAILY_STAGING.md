# BENFRANK NBA v4.4 daily secondary NBA staging

The daily job runs at 15:15 UTC, after the previous NBA local calendar day's games are generally complete. The selected date is the previous UTC date unless supplied manually.

- Retrieves the ESPN scoreboard (secondary provider) and at most 20 completed regular-season game summaries.
- Parses available counting statistics and starter flags and writes an isolated `espn_staging.sqlite` into a GitHub Actions artifact.
- Saves the source provenance and per-event retrieval results.
- **Never** writes or replaces the existing production `games` warehouse or falsely claims NBA official verification.
- NBA CDN HTTP 403 and direct Stats API timeouts remain distinct external access limitations.
- Artifacts automatically expire according to the 30-day retention setting. This is not a durable historical warehouse backup.
- The batch prediction pipeline can read only verified historical warehouse rows; newly staged ESPN records require appropriate reconciliation and versioned promotion before they can join the production warehouse.
- The workflow executes when GitHub scheduling is enabled, and each run must be inspected for actual completion. No assertion of future executions is made.

To inspect: Actions -> BENFRANK NBA v4.4 daily current-season secondary staging.
