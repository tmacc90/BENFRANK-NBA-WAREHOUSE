# BENFRANK NBA v4.4 — batch controller (additive)

`benfrank_v44_batch.py` processes **one prop or more** with independent exact lines, dates and receipts. It reuses the repository's baseline projections, historical windows, statistical blind formula, empirical bootstrap and sequential **minute proxy**, without mislabeling any of those as complete possession-level Twon or independent AI.

It opens an existing SQLite file in read-only mode and makes a disposable SQLite backup for any schema migrations required by the legacy engine. The original warehouse is not modified.

Example board JSON:
```json
[
  {"player":"Sample Player","market":"points","line":19.5,"opponent":"CHA","game_date":"2026-10-29",
   "platform":"PrizePicks","snapshot_id":"board-001","captured_at":"2026-10-29T12:00:00Z",
   "tipoff_utc":"2026-10-29T23:00:00Z"}
]
```

Usage:
```bash
python benfrank_v44_batch.py --db /path/to/verified_nba.sqlite --board board.json --output evidence_receipts.json --trials 25000
python -m unittest discover -s tests -v
```

The runner fails when the warehouse path is missing and isolates failures per prop. It never substitutes example or fixture games as real data. On any stage that cannot be substantiated, the audit stays BLOCKED. The source of any PASS is written in the receipt. Outcomes remain provisional MORE/LESS or UNRESOLVED; ticket eligibility stays NO_TICKET.

**Not yet implemented:** automatic screenshot ingest, official current-season availability, live injury/lineup feeds, complete 68-market adapters, true possession-level 25K Twon, physically isolated Blind AI, calibrated probabilities, certification. A passing GitHub Actions test proves software functionality, not prediction accuracy.
