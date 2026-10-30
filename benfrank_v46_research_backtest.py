"""Measured actual-Twon research on a frozen, prior-history reconstructed cohort.

This can test the model. It cannot turn reconstructed historical availability or
secondary archive lines into independently timestamped production evidence.
"""
import argparse
import collections
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path

from benfrank_v44_blind_orchestrator import run_separate
from benfrank_v44_calibration import probability_from_history, record_verified
from benfrank_v44_twon import trial_run
from benfrank_v45_backtest import evaluate_predictions
from benfrank_v45_evidence import digest, readonly, write_json
from benfrank_v45_readiness import inspect_ledger
from benfrank_v46_reconstructed_replay import build_context
from engine import stat


def execute_one(job):
    context_file, snapshot, out, trials = job
    context = json.loads(Path(context_file).read_text())
    seed = int(hashlib.sha256(snapshot["snapshot_id"].encode()).hexdigest()[:8], 16)
    result = trial_run(context, snapshot["player"], snapshot["market"], snapshot["line"], trials, seed)
    result.update(snapshot_id=snapshot["snapshot_id"], input_context_file_sha256=digest(context_file),
                  prediction_origin="RETROSPECTIVE_PRIOR_HISTORY_RESEARCH_NOT_LIVE_PREGAME",
                  input_mode=context["input_mode"], executed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    write_json(out, result)
    return snapshot, result, out


def run(warehouse, shots, ledger, evidence_root, out_dir, sample_size=60, workers=6, trials=25000):
    if not 50 <= sample_size <= 200 or not 1 <= workers <= 8 or not 25000 <= trials <= 50000:
        raise ValueError("RESEARCH_LIMITS: 50..200 snapshots, 1..8 workers, 25K..50K trials each")
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "contexts").mkdir()
    (out / "simulations").mkdir()
    ready = inspect_ledger(ledger, evidence_root)
    # Predeclare one market/line band. Neither actual results nor simulation
    # predictions enter cohort selection. One outcome per NBA game is selected.
    per_game = {}
    for s in sorted(ready["eligible_snapshots"], key=lambda s: (s["tipoff_utc"], s["player"], s["captured_at"], s["snapshot_id"])):
        if s["market"] == "points" and 25 <= s["line"] < 30:
            per_game.setdefault(s["game_id"], s)
    candidates = list(per_game.values())
    # Even temporal spacing is frozen before any outcomes are loaded.
    indices = sorted({round(i * (len(candidates) - 1) / (sample_size - 1)) for i in range(sample_size)}) if candidates else []
    selected = [candidates[i] for i in indices]
    jobs, source_rejections = [], []
    for s in selected:
        sid = hashlib.sha256(s["snapshot_id"].encode()).hexdigest()
        try:
            context = build_context(warehouse, shots, s)
            if s["player"] not in {p["player"] for r in context["rosters"].values() for p in r}:
                raise ValueError("TARGET_ABSENT_FROM_PRIOR_ONLY_ROTATION_FORECAST")
            path = out / "contexts" / (sid + ".json")
            write_json(path, context)
            jobs.append((str(path), s, str(out / "simulations" / (sid + ".json")), trials))
        except (ValueError, KeyError, TypeError) as exc:
            source_rejections.append({"snapshot_id": s["snapshot_id"], "reason": str(exc)})
    manifest = {"policy": "FIRST_LEXICOGRAPHIC_PLAYER_PER_GAME_POINTS_25_TO_30_EVEN_TEMPORAL_SPACING",
        "outcomes_used_for_selection": False, "candidate_games": len(candidates),
        "selected_before_context_gates": len(selected), "context_eligible": len(jobs),
        "source_rejections": source_rejections, "source_tiers": ready.get("source_tiers", {}),
        "backtester_sha256": digest(__file__), "model_source_sha256": digest(Path(__file__).with_name("benfrank_v44_twon.py")),
        "context_builder_sha256": digest(Path(__file__).with_name("benfrank_v46_reconstructed_replay.py")),
        "snapshot_ids": [j[1]["snapshot_id"] for j in jobs], "trials_per_exact_line": trials,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    write_json(out / "selection_manifest.json", manifest)
    before = digest(warehouse)
    result = {"status": "RUNNING_RECONSTRUCTED_RESEARCH", "predictions": [], "rejections": list(source_rejections),
              "simulation_trials_executed": 0, "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "input_mode": "RETROSPECTIVE_PRIOR_HISTORY_RECONSTRUCTION", "production_calibration": False,
              "selection_manifest_sha256": digest(out / "selection_manifest.json")}
    conn = readonly(warehouse)
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_one, job): job[1] for job in jobs}
            for future in concurrent.futures.as_completed(futures):
                s = futures[future]
                try:
                    _, receipt, path = future.result()
                    if (receipt["trials_executed"] != trials or sum(receipt[k] for k in
                            ("over_count", "under_count", "push_count")) != trials):
                        raise ValueError("ACTUAL_TRIAL_RECEIPT_INCONSISTENT")
                    result["simulation_trials_executed"] += trials
                    row = conn.execute("SELECT * FROM games WHERE player=? AND date=? AND team=? AND opponent=?",
                                       (s["player"], s["game_date"], s["team"], s["opponent"])).fetchone()
                    if row is None or not record_verified(conn, row):
                        raise ValueError("VERIFIED_SETTLEMENT_MISSING")
                    actual = float(stat(row, s["market"]))
                    if actual == s["line"]:
                        raise ValueError("PUSH_EXCLUDED_FROM_BINARY_CALIBRATION_RECEIPT_RETAINED")
                    context = json.loads(Path(jobs[manifest["snapshot_ids"].index(s["snapshot_id"])][0]).read_text())
                    history = conn.execute("SELECT * FROM games WHERE player=? AND date<=? ORDER BY date DESC",
                                           (s["player"], context["history_through_date"])).fetchall()
                    baseline = probability_from_history(history, s["market"], s["line"])
                    if baseline is None:
                        raise ValueError("INSUFFICIENT_PRIOR_BASELINE_HISTORY")
                    blind_asof = (dt.date.fromisoformat(context["history_through_date"]) + dt.timedelta(days=1)).isoformat()
                    blind = run_separate(conn, s["player"], s["market"], blind_asof)
                    nonpush = receipt["over_count"] + receipt["under_count"]
                    if not nonpush:
                        raise ValueError("NO_NONPUSH_SIMULATION_TRIALS")
                    result["predictions"].append({**{k: s[k] for k in ("snapshot_id", "platform", "player", "market",
                        "line", "game_id", "tipoff_utc", "captured_at")}, "actual": actual,
                        "over_result": int(actual > s["line"]), "p_over_raw": receipt["over_count"] / nonpush,
                        "p_over_baseline": baseline["p_over_raw"], "mean": receipt["mean"],
                        "q05": receipt["quantiles"]["0.05"], "q95": receipt["quantiles"]["0.95"],
                        "blind_prediction": blind.get("projection"), "blind_receipt": blind,
                        "simulation_receipt": str(Path(path).relative_to(out))})
                    print(json.dumps({"completed_predictions": len(result["predictions"]),
                                      "actual_trials_executed": result["simulation_trials_executed"]}), flush=True)
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    result["rejections"].append({"snapshot_id": s["snapshot_id"], "reason": str(exc)})
        result["evaluation"] = evaluate_predictions(result["predictions"])
        result["evaluation"]["input_mode"] = result["input_mode"]
        result["status"] = "RECONSTRUCTED_RESEARCH_" + result["evaluation"]["status"]
        result["warning"] = "Research cohort only. No historical injury/news attestation, production promotion policy, independent future test or all-market certification."
        return result
    finally:
        conn.close()
        result.update(warehouse_sha256=before, warehouse_unchanged=before == digest(warehouse))
        write_json(out / "research-backtest.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--shooting-database", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    result = run(args.warehouse, args.shooting_database, args.ledger, args.evidence_root,
                 args.out_dir, args.sample_size, args.workers)
    print(json.dumps({k: v for k, v in result.items() if k not in ("predictions", "evaluation", "rejections")}, indent=2))


if __name__ == "__main__":
    main()
