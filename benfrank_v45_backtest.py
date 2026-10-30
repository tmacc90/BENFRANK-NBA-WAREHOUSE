"""Replay source-linked pregame snapshots through the ACTUAL 5-on-5 simulator.

This is an auditable retrospective replay, never a falsely backdated live pick.
No snapshots/context means no simulations. Every output remains uncertified.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from benfrank_v44_blind_orchestrator import run_separate
from benfrank_v44_calibration import (check_snapshot, instant, probability_from_history,
                                      fit_isotonic, calibrate, scores, record_verified)
from benfrank_v44_twon import trial_run, validate
from benfrank_v45_evidence import digest, readonly, write_json
from benfrank_v45_readiness import inspect_ledger
from engine import stat

BAND_WIDTHS = {"points": 5, "rebounds": 2, "assists": 2, "threes": 1,
               "steals": 1, "blocks": 1, "turnovers": 1,
               "pra": 5, "pr": 5, "pa": 5, "ra": 5, "fantasy_score": 10}


def stratum(row):
    width = BAND_WIDTHS[row["market"]]
    return (row["platform"].strip().casefold(), row["market"], row.get("scoring_contract", ""),
            math.floor(row["line"] / width) * width)


def outcome_key(snapshot, nba_game_id):
    return (snapshot["platform"].strip().casefold(), snapshot["player"], snapshot["market"],
            nba_game_id, snapshot.get("scoring_contract", ""))


def validate_context(context, snapshot, nba_game_id, root):
    validate(context)
    capture, tipoff = check_snapshot(snapshot)
    if context.get("game_id") != nba_game_id or context["game_date"] != snapshot["game_date"]:
        raise ValueError("CONTEXT_GAME_ID_OR_DATE_CONFLICT")
    if instant(context["tipoff_utc"]) != tipoff:
        raise ValueError("CONTEXT_TIPOFF_CONFLICT")
    if context.get("input_mode") != "ASOF_PREGAME_FORECAST":
        raise ValueError("PREGAME_FORECAST_REQUIRED_ACTUAL_ROTATIONS_ARE_NOT_FORECASTS")
    if instant(context["feature_cutoff_utc"]) > capture:
        raise ValueError("FEATURES_AVAILABLE_AFTER_LINE_CAPTURE")
    if dt.date.fromisoformat(context["history_through_date"]) >= dt.date.fromisoformat(snapshot["game_date"]):
        raise ValueError("TARGET_GAME_IN_FEATURE_HISTORY")
    timestamps = [context["pace_asof"]] + [r["asof"] for r in context["team_rates"].values()]
    timestamps += [p["asof"] for roster in context["rosters"].values() for p in roster]
    if any(instant(t) > capture for t in timestamps):
        raise ValueError("RATE_OR_ROSTER_SOURCE_AFTER_CAPTURE")
    records = context.get("evidence_files")
    if not isinstance(records, list) or not records:
        raise ValueError("CONTEXT_ORIGINAL_SOURCE_FILES_REQUIRED")
    required = {"lineup_forecast", "shooting_history", "pace_and_matchup"}
    kinds = set()
    for record in records:
        source = (root / record["file"]).resolve()
        if root not in source.parents or not source.is_file() or digest(source) != record["sha256"]:
            raise ValueError("CONTEXT_SOURCE_FILE_HASH_MISMATCH")
        if instant(record["available_at"]) > capture:
            raise ValueError("CONTEXT_SOURCE_NOT_AVAILABLE_PREGAME")
        kinds.add(record["kind"])
    if not required <= kinds:
        raise ValueError("CONTEXT_PROVENANCE_CATEGORIES_INCOMPLETE")


def clustered_brier_interval(rows, field, baseline=None, resamples=1000):
    by_game = collections.defaultdict(list)
    for row in rows:
        error = (row[field] - row["over_result"]) ** 2
        if baseline:
            error -= (row[baseline] - row["over_result"]) ** 2
        by_game[row["game_id"]].append(error)
    if len(by_game) < 10:
        return {"status": "INSUFFICIENT_DISTINCT_GAMES", "games": len(by_game)}
    rng, clusters = random.Random(20261030), list(by_game.values())
    draws = []
    for _ in range(resamples):
        sampled = [rng.choice(clusters) for _ in clusters]
        draws.append(sum(map(sum, sampled)) / sum(map(len, sampled)))
    draws.sort()
    return {"status": "DESCRIPTIVE_GAME_CLUSTER_BOOTSTRAP", "games": len(clusters),
            "resamples": resamples, "percentile_95pct": [draws[24], draws[974]]}


def evaluate_predictions(rows, min_train=30, min_test=20, min_train_games=10, min_test_games=10):
    result = {"status": "BLOCKED_NO_ELIGIBLE_SIMULATION_PREDICTIONS", "eligible": len(rows),
              "model": "ACTUAL_SEQUENTIAL_5_ON_5_PROBABILITIES", "certification": "NOT_CERTIFIED",
              "ticket_authority": "NO_TICKET", "promotion_policy_applied": False,
              "minimum_is_execution_only": True, "strata": []}
    if not rows:
        return result
    # Freeze one GLOBAL split. An NBA game cannot leak across model/market bins.
    game_tipoffs = {}
    for r in rows:
        tipoff = instant(r["tipoff_utc"])
        if r["game_id"] in game_tipoffs and game_tipoffs[r["game_id"]] != tipoff:
            raise ValueError("Conflicting tipoff for the same canonical game")
        game_tipoffs[r["game_id"]] = tipoff
    groups = sorted(set(game_tipoffs.values()))
    if len(groups) < 2:
        result["status"] = "BLOCKED_INSUFFICIENT_DISTINCT_TIPOFF_GROUPS"
        return result
    cutoff = groups[max(1, min(len(groups)-1, int(len(groups)*.6)))]
    result["global_holdout_cutoff_utc"] = cutoff.isoformat()
    result["unique_games"] = len(game_tipoffs)
    bins = collections.defaultdict(list)
    for row in rows:
        bins[stratum(row)].append(row)
    for key, records in sorted(bins.items()):
        train = [r for r in records if instant(r["tipoff_utc"]) < cutoff]
        test = [r for r in records if instant(r["tipoff_utc"]) >= cutoff]
        item = {"platform": key[0], "market": key[1], "scoring_contract": key[2], "line_band_low": key[3],
                "line_band_width": BAND_WIDTHS[key[1]], "train_n": len(train), "holdout_n": len(test),
                "train_games": len({r["game_id"] for r in train}),
                "holdout_games": len({r["game_id"] for r in test}),
                "status": "INSUFFICIENT_STRATUM_SAMPLE"}
        if (len(train) >= min_train and len(test) >= min_test and
                item["train_games"] >= min_train_games and item["holdout_games"] >= min_test_games):
            model = fit_isotonic([(r["p_over_raw"], r["over_result"]) for r in train])
            test = [{**r, "p_over_calibrated": calibrate(r["p_over_raw"], model)} for r in test]
            reliability = []
            for i in range(10):
                subset = [r for r in test if min(9, int(r["p_over_calibrated"]*10)) == i]
                if subset:
                    reliability.append({"bin": i, "n": len(subset),
                                        "predicted": statistics.mean(r["p_over_calibrated"] for r in subset),
                                        "observed": statistics.mean(r["over_result"] for r in subset)})
            item.update(status="EVALUATED_UNCERTIFIED", isotonic_bins=model,
                        raw_holdout=scores(test, "p_over_raw"),
                        calibrated_holdout=scores(test, "p_over_calibrated"),
                        historical_baseline_holdout=scores(test, "p_over_baseline"),
                        reliability=reliability,
                        brier_interval=clustered_brier_interval(test, "p_over_calibrated"),
                        brier_delta_vs_baseline=clustered_brier_interval(test, "p_over_calibrated", "p_over_baseline"),
                        predictive_90pct_coverage=statistics.mean(r["q05"] <= r["actual"] <= r["q95"] for r in test),
                        simulator_mae=statistics.mean(abs(r["mean"]-r["actual"]) for r in test),
                        holdout_results=test)
            blind = [r for r in test if r.get("blind_prediction") is not None]
            item["blind_challenger"] = {"evaluated": len(blind),
                "mae": statistics.mean(abs(r["blind_prediction"]-r["actual"]) for r in blind) if blind else None,
                "validation": "DESCRIPTIVE_HOLDOUT_ONLY_NO_AUTOMATIC_PROMOTION"}
        result["strata"].append(item)
    result["status"] = "EVALUATED_UNCERTIFIED" if all(x["status"] == "EVALUATED_UNCERTIFIED" for x in result["strata"]) else "BLOCKED_INSUFFICIENT_STRATUM_SAMPLE"
    return result


def replay(warehouse, ledger, evidence_root, context_manifest, out_dir, trials=25000):
    if not 25000 <= trials <= 50000:
        raise ValueError("Real replay requires 25,000..50,000 trials per exact-line snapshot")
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    ready = inspect_ledger(ledger, evidence_root)
    write_json(out / "snapshot_readiness.json", ready)
    result = {"prediction_origin": "RETROSPECTIVE_REPLAY_NOT_LIVE_PREGAME_PICK",
              "executed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "predictions": [], "rejections": [], "simulation_trials_executed": 0,
              "status": "BLOCKED_NO_SOURCE_LINKED_PREGAME_SNAPSHOTS"}
    if not ready["eligible_snapshots"]:
        write_json(out / "backtest.json", result)
        return result
    if not context_manifest or not Path(context_manifest).is_file():
        result["status"] = "BLOCKED_MISSING_PREGAME_CONTEXT_MANIFEST"
        write_json(out / "backtest.json", result)
        return result
    root = Path(context_manifest).resolve().parent
    manifest = json.loads(Path(context_manifest).read_text())
    before = digest(warehouse)
    conn = readonly(warehouse)
    selected_outcomes = set()
    try:
        for snapshot in sorted(ready["eligible_snapshots"], key=lambda s: (check_snapshot(s)[1], check_snapshot(s)[0], s["snapshot_id"])):
            sid = snapshot["snapshot_id"]
            try:
                observed = conn.execute("SELECT * FROM games WHERE player=? AND date=? AND opponent=?",
                    (snapshot["player"], snapshot["game_date"], snapshot["opponent"])).fetchall()
                if len(observed) != 1 or not record_verified(conn, observed[0]):
                    raise ValueError("MISSING_UNIQUE_VERIFIED_SETTLEMENT")
                row = observed[0]
                relation = "verified_history" if conn.execute("SELECT 1 FROM sqlite_master WHERE name='verified_history'").fetchone() else "game_verifications"
                gid = conn.execute("SELECT nba_game_id FROM " + relation + " WHERE player=? AND date=? AND team=?",
                    (row["player"], row["date"], row["team"])).fetchone()[0]
                identity = outcome_key(snapshot, gid)
                if identity in selected_outcomes:
                    raise ValueError("DUPLICATE_CANONICAL_GAME_OUTCOME_EXCLUDED")
                selected_outcomes.add(identity)
                context_file = (root / manifest[sid]).resolve()
                if root not in context_file.parents:
                    raise ValueError("CONTEXT_PATH_OUTSIDE_MANIFEST_ROOT")
                context = json.loads(context_file.read_text())
                expected_home = row["team"] if row["home"] else row["opponent"]
                expected_away = row["opponent"] if row["home"] else row["team"]
                if context.get("home") != expected_home or context.get("away") != expected_away:
                    raise ValueError("CONTEXT_HOME_AWAY_IDENTITY_CONFLICT")
                validate_context(context, snapshot, gid, root)
                if snapshot["player"] not in {p["player"] for p in context["rosters"][row["team"]]}:
                    raise ValueError("TARGET_PLAYER_ON_WRONG_TEAM")
                if snapshot["market"] == "fantasy_score" and snapshot.get("scoring_contract") != "PTS1_REB1.2_AST1.5_STL3_BLK3_TOV-1":
                    raise ValueError("UNSUPPORTED_PLATFORM_FANTASY_SCORING_CONTRACT")
                history = conn.execute("SELECT * FROM games WHERE player=? AND date<? ORDER BY date DESC",
                    (snapshot["player"], snapshot["game_date"])).fetchall()
                baseline = probability_from_history(history, snapshot["market"], snapshot["line"])
                if baseline is None:
                    raise ValueError("INSUFFICIENT_PRIOR_HISTORY_FOR_BASELINE")
                seed = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16)
                receipt = trial_run(context, snapshot["player"], snapshot["market"], snapshot["line"], trials, seed)
                if (receipt["trials_executed"] != trials or
                        sum(receipt[k] for k in ("over_count", "under_count", "push_count")) != trials):
                    raise ValueError("ACTUAL_TRIAL_RECEIPT_COUNT_MISMATCH")
                result["simulation_trials_executed"] += receipt["trials_executed"]
                receipt.update(snapshot_id=sid, captured_at=snapshot["captured_at"],
                               platform=snapshot["platform"], nba_game_id=gid,
                               input_context_file_sha256=digest(context_file), prediction_origin=result["prediction_origin"],
                               executed_at=dt.datetime.now(dt.timezone.utc).isoformat())
                receipt_name = hashlib.sha256(sid.encode()).hexdigest() + ".json"
                write_json(out / receipt_name, receipt)
                actual = float(stat(row, snapshot["market"]))
                nonpush = receipt["over_count"] + receipt["under_count"]
                if actual == snapshot["line"] or not nonpush:
                    raise ValueError("PUSH_EXCLUDED_FROM_BINARY_CALIBRATION_RECEIPT_RETAINED")
                blind = run_separate(conn, snapshot["player"], snapshot["market"], snapshot["game_date"])
                result["predictions"].append({**{k: snapshot[k] for k in
                    ("snapshot_id", "platform", "player", "market", "line", "tipoff_utc", "captured_at")},
                    "scoring_contract": snapshot.get("scoring_contract", ""), "game_id": gid,
                    "actual": actual, "over_result": int(actual > snapshot["line"]),
                    "p_over_raw": receipt["over_count"] / nonpush,
                    "push_probability": receipt["push_count"] / trials,
                    "p_over_baseline": baseline["p_over_raw"], "mean": receipt["mean"],
                    "q05": receipt["quantiles"]["0.05"], "q95": receipt["quantiles"]["0.95"],
                    "blind_prediction": blind.get("projection"), "blind_receipt": blind,
                    "simulation_receipt": receipt_name})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                result["rejections"].append({"snapshot_id": sid, "reason": str(exc)})
        evaluation = evaluate_predictions(result["predictions"])
        result.update(evaluation=evaluation, status=evaluation["status"])
    finally:
        conn.close()
        result.update(warehouse_sha256=before, warehouse_unchanged=before == digest(warehouse),
                      ledger_unchanged=ready.get("ledger_unchanged", False))
        write_json(out / "backtest.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--warehouse", required=True)
    p.add_argument("--ledger")
    p.add_argument("--evidence-root")
    p.add_argument("--contexts")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--trials", type=int, default=25000)
    a = p.parse_args()
    result = replay(a.warehouse, a.ledger, a.evidence_root, a.contexts, a.out_dir, a.trials)
    print(json.dumps({k: v for k, v in result.items() if k not in ("predictions", "evaluation")}, indent=2))
    if result["status"].startswith("BLOCKED"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
