# BENFRANK v5.3 — First end-to-end runner

Command:

```bash
python benfrank_v53_run.py --config /private/early-config.json --output /private/immutable-v53-run-001
```

This wrapper executes the unchanged v5.2 source collector and 25K complete-game forecasting pipeline, then creates **separate** v5.3 companion receipts for successful v5.2 props. It does not alter the v5.2 ledger or source receipts. It replays the exact uploaded line against actual prior game outcomes, calculates historical windows, 100 source-gated DNA checks and same-player similarity where feature coverage permits, and includes the v5.2 primary simulation and Blind results.

It is intentionally honest about what remains unavailable: automatic opponent position and tracking feeds, as-of peer-role analogues, all five independent model families, calibrated probabilities, and live charts. The 60-question philosophy is a governing checklist, not yet a source-backed auto-answer engine. For markets whose warehouse schema lacks the required actual game statistics, companion creation fails explicitly. A successful software run does not certify betting accuracy.

**Privacy and provenance:** Never commit private boards, historical database, exact prop receipts or user-supplied contexts to GitHub. Use a new output directory for every run. Preserve all prior forecasts and version identifiers. Do not promote this challenger into the mainline or claim FULL certification without chronological outcome validation.

**Testing needed in an internet-enabled execution environment:** dependency import, fixture unit tests, live warehouse schema mapping, source freshness and cutoff audits, true 25K trial receipts, Blind independence, missing-market failure cases, and settlement against verified postgame results.
