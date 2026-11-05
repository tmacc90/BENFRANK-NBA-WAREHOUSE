"""Single command entry point: run real v5.2 + v5.3, then audit receipts.

Usage: python benfrank_v60_run.py --config CONFIG.json --output NEW_DIRECTORY
Requires the existing v5.2 config with board, contexts, history_db, ledger.
No synthetic evidence or certification is produced.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

def run(config, output):
    root = Path(output)
    if root.exists():
        raise FileExistsError("IMMUTABLE_RUN_DIRECTORY_EXISTS")
    root.mkdir(parents=True)
    command = [sys.executable, str(Path(__file__).with_name("benfrank_v53_run.py")),
               "--config", str(config), "--output", str(root / "pipeline")]
    proc = subprocess.run(command, check=False)
    config_data = json.loads(Path(config).read_text())
    board = json.loads(Path(config_data["board"]).read_text())
    comparison_path = root / "pipeline" / "v53" / "comparison.json"
    comparison = json.loads(comparison_path.read_text()) if comparison_path.exists() else {}
    by_id = {r.get("snapshot_id"): r for r in comparison.get("results", [])}
    reports = []
    seen_snapshots = set()
    for prop in board:
        snapshot = prop["snapshot_id"]
        if snapshot in seen_snapshots:
            raise ValueError("DUPLICATE_SNAPSHOT_ID: " + snapshot)
        seen_snapshots.add(snapshot)
        early_path = root / "pipeline" / "v52" / "results" / (snapshot + ".json")
        dna_path = root / "pipeline" / "v53" / (snapshot + ".json")
        early = json.loads(early_path.read_text()) if early_path.exists() else None
        dna = json.loads(dna_path.read_text()) if dna_path.exists() else None
        sim = early.get("main_simulation", {}) if early else {}
        blind = early.get("blind_model", {}) if early else {}
        trials = sim.get("trials_executed")
        # Claimed trial counts and nonempty blind results are not execution proof.
        sim_proof = sim.get("trial_evidence", {})
        sim_verified = (
            isinstance(trials, int) and not isinstance(trials, bool)
            and trials >= 25000 and isinstance(sim_proof, dict)
            and sim_proof.get("verified") is True
            and bool(sim_proof.get("trials_sha256"))
            and sim_proof.get("seed") is not None
            and bool(sim_proof.get("input_sha256"))
        )
        blind_proof = blind.get("independence_evidence", {})
        blind_verified = (
            isinstance(blind_proof, dict)
            and blind_proof.get("verified") is True
            and bool(blind_proof.get("model_id"))
            and bool(blind_proof.get("training_cutoff_utc"))
            and bool(blind_proof.get("feature_manifest_sha256"))
            and blind_proof.get("line_excluded") is True
            and blind_proof.get("primary_prediction_excluded") is True
        )
        checks = {
            "exact_prop": bool(prop.get("player") and prop.get("market") and isinstance(prop.get("line"), (int,float))),
            "v52_receipt": early is not None,
            "v53_dna_receipt": dna is not None,
            "sequential_25000": bool(sim_verified),
            "blind_model": bool(blind_verified),
            "source_cutoff": bool(early and early.get("analysis_cutoff_utc")),
            "dna_tests": bool(dna and dna.get("dna_100_test_results")),
        }
        direction = early.get("direction") if early else None
        if direction not in ("OVER","UNDER"):
            direction = None
        reports.append({
            "snapshot_id":snapshot,"player":prop.get("player"),"market":prop.get("market"),
            "line":prop.get("line"),"opponent":prop.get("opponent"),
            "side":direction,"research_only":True,"certified":False,
            "execution_status":"COMPONENT_RECEIPTS_VERIFIED" if all(checks.values()) else "INCOMPLETE",
            "checks":checks,"missing":[k for k,v in checks.items() if not v],
            "v53_status":by_id.get(snapshot,{}).get("status","MISSING"),
            "simulation_trials_reported":trials,
            "simulation_trials_independently_verified":bool(sim_verified),
            "blind_independence_verified":bool(blind_verified),
            "warning":"Receipt presence is not independent source, calibration, or accuracy certification."
        })
    result = {"version":"BENFRANK_V60","pipeline_exit_code":proc.returncode,
              "status":"RESEARCH_ONLY","props":reports}
    (root / "run_report.json").write_text(json.dumps(result,indent=2)+"\n")
    for p in reports:
        icon = "✅" if p["execution_status"] == "COMPONENT_RECEIPTS_VERIFIED" else "⚠️"
        print(f'{icon} {p["player"]} | {p["market"]} {p["line"]} | {p["side"] or "NO SIDE"} | {p["execution_status"]}')
        if p["missing"]:
            print("   Missing:",", ".join(p["missing"]))
    return 0 if proc.returncode == 0 and all(not p["missing"] for p in reports) else 2

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    raise SystemExit(run(args.config,args.output))
