# BENFRANK NBA v4.4 — additive 66-stage evidence gate

This module is **not** the full prediction engine. It adds a fail-closed, machine-readable verification receipt without modifying existing historical data, existing engine.py, or production workflows.

Run:
```bash
python -m unittest discover -s tests -v
python benfrank_v44_audit.py --prop-json example_prop.json --output receipt.json
```

Required prop JSON fields: `player`, `market`, `line`, `opponent`, `game_date` (YYYY-MM-DD).

Optional `--evidence-json` maps stage identifiers to `{"status":"PASS","source":"...","asof":"...","detail":"..."}`. Only `PASS`, `FAIL`, `BLOCKED`, `NOT_APPLICABLE` are accepted. PASS without source and timestamp is rejected. Missing stages default to BLOCKED. Every receipt includes a deterministic SHA-256 digest.

**Current limitation:** This stage gate does not fetch sources, validate source truth, run 25K possession trials, produce an independent AI projection, or calibrate probabilities. It intentionally returns `UNRESOLVED` and `NO_TICKET` until those engines are built and independently validated. It is the safe foundation for integrating them, not evidence that 66 stages ran.

The existing v4.1 warehouse and workflows remain intact. Changes are proposed on an isolated branch and require review before merging.
