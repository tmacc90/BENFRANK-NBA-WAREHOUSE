"""Additive BENFRANK NBA v4.4 evidence receipt. Never asserts unrun stages passed."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

STAGES = [
  {
    "id": "prop_identity",
    "group": "Intake and official truth"
  },
  {
    "id": "exact_line",
    "group": "Intake and official truth"
  },
  {
    "id": "market_support",
    "group": "Intake and official truth"
  },
  {
    "id": "game_date",
    "group": "Intake and official truth"
  },
  {
    "id": "opponent_identity",
    "group": "Intake and official truth"
  },
  {
    "id": "source_provenance",
    "group": "Intake and official truth"
  },
  {
    "id": "asof_timestamp",
    "group": "Intake and official truth"
  },
  {
    "id": "schedule_authority",
    "group": "Intake and official truth"
  },
  {
    "id": "availability_authority",
    "group": "Intake and official truth"
  },
  {
    "id": "lineup_authority",
    "group": "Intake and official truth"
  },
  {
    "id": "career_sample",
    "group": "Historical player DNA"
  },
  {
    "id": "season_sample",
    "group": "Historical player DNA"
  },
  {
    "id": "recent_L5",
    "group": "Historical player DNA"
  },
  {
    "id": "recent_L10",
    "group": "Historical player DNA"
  },
  {
    "id": "recent_L15",
    "group": "Historical player DNA"
  },
  {
    "id": "recent_L20",
    "group": "Historical player DNA"
  },
  {
    "id": "exact_line_mirror",
    "group": "Historical player DNA"
  },
  {
    "id": "role_splits",
    "group": "Historical player DNA"
  },
  {
    "id": "minutes_distribution",
    "group": "Historical player DNA"
  },
  {
    "id": "teammate_splits",
    "group": "Historical player DNA"
  },
  {
    "id": "opponent_pace",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "opponent_defense",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "positional_matchup",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "scheme_coverage",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "on_off_matchups",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "home_away",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "rest_travel",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "game_script",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "foul_risk",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "opponent_personnel",
    "group": "Opponent and matchup DNA"
  },
  {
    "id": "minutes_forecast",
    "group": "Market opportunity"
  },
  {
    "id": "usage_forecast",
    "group": "Market opportunity"
  },
  {
    "id": "shot_attempts",
    "group": "Market opportunity"
  },
  {
    "id": "shot_quality",
    "group": "Market opportunity"
  },
  {
    "id": "three_attempts",
    "group": "Market opportunity"
  },
  {
    "id": "potential_assists",
    "group": "Market opportunity"
  },
  {
    "id": "rebound_chances",
    "group": "Market opportunity"
  },
  {
    "id": "stocks_opportunity",
    "group": "Market opportunity"
  },
  {
    "id": "combo_stat_dependencies",
    "group": "Market opportunity"
  },
  {
    "id": "fantasy_scoring_authority",
    "group": "Market opportunity"
  },
  {
    "id": "conversion_efficiency",
    "group": "Probability and failure"
  },
  {
    "id": "regression",
    "group": "Probability and failure"
  },
  {
    "id": "variance",
    "group": "Probability and failure"
  },
  {
    "id": "sample_shrinkage",
    "group": "Probability and failure"
  },
  {
    "id": "more_case",
    "group": "Probability and failure"
  },
  {
    "id": "less_case",
    "group": "Probability and failure"
  },
  {
    "id": "exact_line_margin",
    "group": "Probability and failure"
  },
  {
    "id": "minutes_downside",
    "group": "Probability and failure"
  },
  {
    "id": "usage_downside",
    "group": "Probability and failure"
  },
  {
    "id": "efficiency_downside",
    "group": "Probability and failure"
  },
  {
    "id": "teammate_reallocation",
    "group": "Probability and failure"
  },
  {
    "id": "hell_reverse",
    "group": "Probability and failure"
  },
  {
    "id": "data_freshness",
    "group": "Execution and certification"
  },
  {
    "id": "source_conflict",
    "group": "Execution and certification"
  },
  {
    "id": "missing_data_fallback",
    "group": "Execution and certification"
  },
  {
    "id": "warehouse_integrity",
    "group": "Execution and certification"
  },
  {
    "id": "simulation_input_validation",
    "group": "Execution and certification"
  },
  {
    "id": "sequential_twon_25000",
    "group": "Execution and certification"
  },
  {
    "id": "simulation_reproducibility",
    "group": "Execution and certification"
  },
  {
    "id": "independent_blind_ai",
    "group": "Execution and certification"
  },
  {
    "id": "model_disagreement",
    "group": "Execution and certification"
  },
  {
    "id": "walk_forward_calibration",
    "group": "Execution and certification"
  },
  {
    "id": "no_hindsight",
    "group": "Execution and certification"
  },
  {
    "id": "immutable_snapshot",
    "group": "Execution and certification"
  },
  {
    "id": "direction_adjudication",
    "group": "Execution and certification"
  },
  {
    "id": "ticket_authority",
    "group": "Execution and certification"
  }
]
ALLOWED = {"PASS", "FAIL", "BLOCKED", "NOT_APPLICABLE"}
CRITICAL = {"exact_line", "market_support", "availability_authority", "asof_timestamp",
            "source_provenance", "warehouse_integrity", "sequential_twon_25000",
            "independent_blind_ai", "walk_forward_calibration", "ticket_authority"}

def build_receipt(prop, evidence=None):
    """evidence: {stage_id: {status, source, asof, detail}}; absent means BLOCKED."""
    evidence = evidence or {}
    required = {"player", "market", "line", "opponent", "game_date"}
    missing = sorted(required - set(prop))
    if missing:
        raise ValueError("Missing prop fields: " + ", ".join(missing))
    if not isinstance(prop["line"], (int, float)) or isinstance(prop["line"], bool):
        raise ValueError("line must be numeric")
    dt.date.fromisoformat(prop["game_date"])
    known = {s["id"] for s in STAGES}
    unknown = set(evidence) - known
    if unknown:
        raise ValueError("Unknown stages: " + ", ".join(sorted(unknown)))
    checks = []
    for stage in STAGES:
        item = evidence.get(stage["id"], {})
        status = item.get("status", "BLOCKED")
        if status not in ALLOWED:
            raise ValueError("Invalid status for " + stage["id"])
        if status == "PASS" and (not item.get("source") or not item.get("asof")):
            raise ValueError("PASS requires source and asof: " + stage["id"])
        checks.append({**stage, "status": status, "source": item.get("source"),
                       "asof": item.get("asof"), "detail": item.get("detail", "No verified execution receipt")})
    blockers = [c["id"] for c in checks if c["id"] in CRITICAL and c["status"] != "PASS"]
    payload = {"framework": "BENFRANK NBA v4.4", "prop": prop, "stages": checks,
               "counts": {s: sum(c["status"] == s for c in checks) for s in sorted(ALLOWED)},
               "critical_blockers": blockers, "ticket_authority": "NO_TICKET",
               "direction": "UNRESOLVED", "certification": "NOT_CERTIFIED"}
    payload["receipt_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return payload

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prop-json", required=True, help="JSON file with player, market, line, opponent, game_date")
    p.add_argument("--evidence-json", help="Optional JSON map of stage receipts")
    p.add_argument("--output", help="Optional receipt output path")
    a = p.parse_args()
    prop = json.loads(Path(a.prop_json).read_text())
    evidence = json.loads(Path(a.evidence_json).read_text()) if a.evidence_json else {}
    result = build_receipt(prop, evidence)
    data = json.dumps(result, indent=2) + "\n"
    if a.output:
        Path(a.output).write_text(data)
    else:
        print(data)

if __name__ == "__main__":
    main()
