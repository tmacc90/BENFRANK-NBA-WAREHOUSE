# BENFRANK OMNI Automatic Data Research v1
This is an additive, deliberately uncertified ESPN game-log and bootstrap research adapter. It does not modify the existing warehouse. It captures raw JSON, derives exact-line coverage, executes 25,000 seeded empirical bootstrap draws per supported prop, saves each draw, and records a SHA-256 digest and failure receipt.

Run: `python scripts/omni_auto_data.py --props config/omni_props_example.json`

The JSON input must supply real ESPN athlete IDs, seasons and uploaded lines. Example config is intentionally empty to avoid fabricating identifiers or current lines. Supported markets: points, rebounds, assists, pra, ra. ESPN's unofficial schema may change and must be checked against real responses. Missing or changed data fails closed.

**Not yet implemented or certified:** official injury report ingestion, projected minutes, opponent defensive DNA crosschecks, 52-game multi-season merging, independent trained Blind AI, opponent-adjusted possession simulation, calibration, and full end-to-end verification. The baseline called blind_line_free_recent_mean is explicitly *not* independent ML. The bootstrap is a real simulation of historical outcomes but not a game-level possession simulation. A green GitHub job does not establish full certification.
