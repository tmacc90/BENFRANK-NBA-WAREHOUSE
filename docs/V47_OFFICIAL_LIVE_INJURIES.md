# v4.7 — Timestamped current official NBA injury feed (source gated)

This repair extends the original-PDF evidence pipeline into currently published NBA injury documents. It is additive and does **not** delete, replace or update any source warehouse, training artifact or pregame prediction receipt.

## Mechanics

1. At the time a workflow runs, `benfrank_v47_live_official_injuries.py` calculates an actual current UTC cutoff. It rejects future cutoffs or purported historical replays more than 24 hours in the past.
2. It searches only official NBA injury PDFs through the existing `benfrank_v46_official_injuries.capture_before` source adapter. Candidate filenames are derived from valid NBA injury publication quarter-hours.
3. It checks the original PDF signature, bounded file size and the **printed official report timestamp**. The printed time must agree with the official URL and be strictly earlier than capture cutoff.
4. It parses actual PDF column positions using the existing `benfrank_v47_availability.parse_pdf` parser; unresolved rows, absent players and teams that have not submitted reports remain explicit unknowns.
5. It writes an immutable-source hash and full retrieval timestamp. **Never use the report for a prediction made before its actual retrieval time**, even if the report itself is older. The source is a published availability observation, not an independently verified starting lineup or minutes projection.
6. The artifact includes original official PDF/text, `official-injury-captures.json` in a format readable by the existing `benfrank_v47_availability.load_archive`, and `live-official-injury-receipt.json` with capture/parse/issue counts.

## Scheduling and limits

`.github/workflows/v47-official-live-injuries.yml` runs four times daily via UTC cron after merged into `main`, and can also be manually dispatched. Workflow runs fail when they cannot retrieve and validate a current official report, rather than inventing availability. The scheduled provider result is not claimed to be successful before execution.

The existing ESPN secondary injury pipeline remains a fallback/source comparison, **not** independent official clearance. A player unlisted in both sources remains **UNKNOWN**, not AVAILABLE. A team missing from the PDF remains unverified. Matchup/start/rotation/usage verification and as-of exact prop lines require their own independent evidence.

No injury record or passing test can award FULL or enable a ticket: `certification=NOT_CERTIFIED` and `ticket_authority=NO_TICKET`.

## Reproduce on an authorized internet-enabled runner

```bash
python -m unittest discover -s tests -p test_v47_live_official_injuries.py -v
python benfrank_v47_live_official_injuries.py --output-dir /private/receipts/official-live --require-report
python benfrank_v47_availability.py --archive /private/receipts/official-live --out /private/receipts/parsed.json
```

**Security:** Only user-supplied data and official published PDF source are collected. Original documents are public NBA reports; do not publish personalized sportsbook screenshots or private NBA warehouse files to GitHub Actions artifacts.
