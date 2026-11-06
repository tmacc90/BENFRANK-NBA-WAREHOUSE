"""Connect six screenshot props to the additive 60-question audit.

Usage:
 python benfrank_six_prop_batch.py --inputs real_stage_results.json --output reports
The input JSON must contain a 'props' list with 'stage_answers' for each prop.
No simulation or blind-model result is invented by this adapter.
"""
import argparse
import json
from pathlib import Path
from benfrank_interrogation_60 import evaluate, write_report

PROPS = [
    ("Luka Doncic", "3PM", 4.5, "POR"),
    ("Tyrese Maxey", "PTS", 25.5, "CLE"),
    ("Ziaire Williams", "PTS_REB", 10.5, "POR"),
    ("Isaiah Hartenstein", "REB", 10.5, "MEM"),
    ("Ajay Mitchell", "PTS_REB", 24.5, "MEM"),
    ("Donovan Mitchell", "PTS", 24.5, "PHI"),
]

def run(payload, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    incoming = {(p["player"], p["market"], float(p["line"])): p
                for p in payload.get("props", [])}
    summary = []
    for idx, (player, market, line, opponent) in enumerate(PROPS, 1):
        raw = incoming.get((player, market, line), {})
        report = evaluate(raw.get("stage_answers", {}), sport="NBA",
                          player=player, market=market, line=line,
                          cutoff_utc=raw.get("cutoff_utc", ""),
                          preferred_side=raw.get("preferred_side"))
        report["opponent"] = opponent
        report["source_type"] = "screenshot-line + supplied execution results"
        write_report(str(output / f"prop_{idx:02}.json"), report)
        summary.append({"player": player, "market": market, "line": line,
                        "verified": report["verified_count"],
                        "certified": report["certified"],
                        "side": report["preferred_side"]})
    (output / "batch_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", default="reports/interrogation")
    args = parser.parse_args()
    with open(args.inputs, encoding="utf-8") as f:
        payload = json.load(f)
    print(json.dumps(run(payload, args.output), indent=2))
