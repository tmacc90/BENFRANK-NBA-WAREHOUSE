"""Held-out EMPIRICAL baseline on recovered real lines, not Twon calibration.

Every game stays on one side of the global chronological cutoff. Results remain
separate by platform, market and fixed line band. No deployment promotion occurs.
"""
import argparse
import collections
import json
from pathlib import Path

from acquire_history import verification_relation
from benfrank_v44_calibration import (calibrate, fit_isotonic, instant, probability_from_history,
                                      record_verified, scores)
from benfrank_v45_backtest import stratum, BAND_WIDTHS, clustered_brier_interval
from benfrank_v45_evidence import digest, readonly, write_json
from benfrank_v45_readiness import inspect_ledger
from engine import stat


def evaluate_rows(rows, minimum_train=30, minimum_test=20, minimum_games=10):
    result = {"status": "BLOCKED_INSUFFICIENT_GAMES", "model": "EMPIRICAL_PRIOR_20_GAME_BASELINE",
              "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "simulation_trials_executed": 0, "simulator_calibrated": False,
              "promotion_policy_applied": False, "eligible_outcomes": len(rows), "strata": []}
    games = {}
    for row in rows:
        tipoff = instant(row["tipoff_utc"])
        if row["game_id"] in games and games[row["game_id"]] != tipoff:
            raise ValueError("CONFLICTING_CANONICAL_GAME_TIPOFF")
        games[row["game_id"]] = tipoff
    groups = sorted(set(games.values()))
    if len(groups) < 2:
        return result
    cutoff = groups[max(1, min(len(groups) - 1, int(len(groups) * .6)))]
    result.update(global_holdout_cutoff_utc=cutoff.isoformat(), unique_games=len(games))
    bins = collections.defaultdict(list)
    for row in rows:
        bins[stratum(row)].append(row)
    for key, records in sorted(bins.items()):
        train = [r for r in records if instant(r["tipoff_utc"]) < cutoff]
        test = [r for r in records if instant(r["tipoff_utc"]) >= cutoff]
        item = {"platform": key[0], "market": key[1], "line_band_low": key[3],
                "line_band_width": BAND_WIDTHS[key[1]], "train_n": len(train), "holdout_n": len(test),
                "train_games": len({r["game_id"] for r in train}),
                "holdout_games": len({r["game_id"] for r in test}),
                "status": "INSUFFICIENT_STRATUM_SAMPLE"}
        if (len(train) >= minimum_train and len(test) >= minimum_test and
                min(item["train_games"], item["holdout_games"]) >= minimum_games):
            model = fit_isotonic([(r["p_over_raw"], r["over_result"]) for r in train])
            evaluated = [{**r, "p_over_calibrated": calibrate(r["p_over_raw"], model)} for r in test]
            item.update(status="EVALUATED_BASELINE_ONLY", isotonic_bins=model,
                        raw_holdout=scores(evaluated, "p_over_raw"),
                        calibrated_holdout=scores(evaluated, "p_over_calibrated"),
                        brier_delta=clustered_brier_interval(evaluated, "p_over_calibrated", "p_over_raw"),
                        holdout_results=evaluated)
        result["strata"].append(item)
    result["evaluated_strata"] = sum(s["status"] == "EVALUATED_BASELINE_ONLY" for s in result["strata"])
    result["status"] = "EVALUATED_BASELINE_ONLY" if result["evaluated_strata"] else "BLOCKED_INSUFFICIENT_STRATUM_SAMPLE"
    result["warning"] = "Measured baseline results never calibrate the different 5-on-5 model. Public collector coverage and played-player selection can bias this sample."
    return result


def run(warehouse, ledger, evidence_root, out_dir):
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    readiness = inspect_ledger(ledger, evidence_root)
    write_json(out / "readiness.json", {k: v for k, v in readiness.items() if k != "eligible_snapshots"})
    before = digest(warehouse)
    conn = readonly(warehouse)
    predictions, rejected, known = [], [], set()
    try:
        relation = verification_relation(conn)
        for s in readiness["eligible_snapshots"]:
            matches = conn.execute("SELECT * FROM games WHERE player=? AND date=? AND team=? AND opponent=?",
                (s["player"], s["game_date"], s["team"], s["opponent"])).fetchall()
            if len(matches) != 1 or not record_verified(conn, matches[0]):
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": "UNVERIFIED_SETTLEMENT"})
                continue
            canonical = conn.execute("SELECT nba_game_id FROM " + relation + " WHERE player=? AND date=? AND team=?",
                                     (s["player"], s["game_date"], s["team"])).fetchone()
            if canonical is None or s["game_id"] != canonical[0]:
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": "CANONICAL_GAME_ID_CONFLICT"})
                continue
            key = (s["game_id"], s["player"], s["market"], s["platform"].casefold())
            if key in known:
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": "DUPLICATE_GAME_OUTCOME"})
                continue
            known.add(key)
            actual = float(stat(matches[0], s["market"]))
            if actual == s["line"]:
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": "PUSH_EXCLUDED_FROM_BINARY_SCORE"})
                continue
            history = conn.execute("SELECT * FROM games WHERE player=? AND date<? ORDER BY date DESC",
                                   (s["player"], s["game_date"])).fetchall()
            probability = probability_from_history(history, s["market"], s["line"])
            if probability is None:
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": "INSUFFICIENT_PRIOR_HISTORY"})
                continue
            predictions.append({**{k: s[k] for k in ("snapshot_id", "platform", "player", "market", "line",
                                "game_id", "game_date", "tipoff_utc", "captured_at")},
                                "actual": actual, "over_result": int(actual > s["line"]), **probability})
        result = evaluate_rows(predictions)
        result.update(input_selected_snapshots=readiness["selected_outcomes"], rejections=rejected,
                      rejection_reasons=dict(collections.Counter(r["reason"] for r in rejected)),
                      warehouse_sha256=before, warehouse_unchanged=before == digest(warehouse),
                      evidence_tiers=readiness.get("source_tiers", {}))
        write_json(out / "baseline.json", result)
        return result
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    result = run(args.warehouse, args.ledger, args.evidence_root, args.out_dir)
    print(json.dumps({k: v for k, v in result.items() if k not in ("strata", "rejections")}, indent=2))


if __name__ == "__main__":
    main()
