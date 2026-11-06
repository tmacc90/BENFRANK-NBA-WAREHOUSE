"""Observed-game bootstrap, workload scenarios and an isolated line-blind ridge.

These are explicitly empirical statistical models. The 25K sequential draws
are not advertised as full possession-, point-, or play-by-play sports games.
"""
import bisect
import datetime as dt
import gzip
import hashlib
import json
import math
import random
import statistics
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from .contracts import canonical, sha, timestamp
from . import VERSION

WINDOWS = (5, 10, 15, 20, 25, 32, 52)


def side(value, line):
    return "OVER" if value > line else "UNDER" if value < line else "PUSH"


def counts(values, line):
    over = sum(v > line for v in values)
    under = sum(v < line for v in values)
    return {"n": len(values), "over": over, "under": under, "push": len(values) - over - under}


def historical(games, prop):
    windows = {}
    for n in WINDOWS:
        values = [g["value"] for g in games[-n:]]
        windows["L" + str(n)] = {**counts(values, prop["line"]), "requested": n, "complete": len(values) == n, "expected_line": statistics.mean(values)}
    seasons = sorted({g["season"] for g in games}, reverse=True)
    season_labels = [("CURRENT_SEASON", prop["current_season"])] if prop.get("current_season") else [("LATEST_FETCHED_SEASON", seasons[0])]
    if prop.get("previous_season"):
        season_labels.append(("PREVIOUS_SEASON", prop["previous_season"]))
    elif len(seasons) > 1:
        season_labels.append(("PRIOR_FETCHED_SEASON", seasons[1]))
    for label, season in season_labels:
        values = [g["value"] for g in games if g["season"] == season]
        windows[label] = {**counts(values, prop["line"]), "season": season, "expected_line": statistics.mean(values) if values else None}
    windows["ALL_FETCHED"] = {**counts([g["value"] for g in games], prop["line"]), "expected_line": statistics.mean(g["value"] for g in games), "career_complete": False}
    streak_side = side(games[-1]["value"], prop["line"])
    streak_n = 0
    for g in reversed(games):
        if side(g["value"], prop["line"]) != streak_side:
            break
        streak_n += 1
    h2h = [g for g in games if str(g["opponent"]) == str(prop["opponent"])]
    return {"windows": windows, "streak": {"side": streak_side, "length": streak_n}, "head_to_head": {**counts([g["value"] for g in h2h], prop["line"]), "mean": statistics.mean(g["value"] for g in h2h) if h2h else None}, "max_feature_start_utc": games[-1]["start_utc"], "missing_windows": [k for k, w in windows.items() if w.get("complete") is False]}


def probabilities(values, line):
    c = counts(values, line)
    return {"p_over": c["over"] / c["n"], "p_under": c["under"] / c["n"], "p_push": c["push"] / c["n"], "counts": c}


def choose(p):
    return "OVER" if p["p_over"] > p["p_under"] else "UNDER"


def simulate(games, prop, root, trials=25000, seed=1729):
    if type(trials) is not int or not 25000 <= trials <= 1_000_000:
        raise ValueError("SIMULATION_TRIALS_MUST_BE_25000_TO_1000000")
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("INTEGER_SIMULATION_SEED_REQUIRED")
    # No line or decision participates in draw generation or parameter estimates.
    input_hash = sha({"games": games, "rules": prop["rules"], "sport": prop["sport"], "market": prop["market"], "version": VERSION})
    rng = random.Random(seed)
    weights = [2 ** (-(len(games) - 1 - i) / 20) * (1.25 if str(g["opponent"]) == str(prop["opponent"]) else 1) for i, g in enumerate(games)]
    values = [g["value"] for g in games]
    center, spread = statistics.mean(values), max(statistics.pstdev(values), .25)
    workloads = [g["workload"] for g in games[-10:] if g.get("workload") is not None]
    units = {g.get("workload_unit") for g in games}
    workload_complete = len(workloads) == min(10, len(games)) and all(g.get("workload") is not None and g["workload"] > 0 for g in games) and len(units) == 1 and None not in units and prop["sport"] not in ("F1", "GOLF")
    target = statistics.median(workloads[-5:]) if workload_complete else None
    if prop.get("projected_workload") is not None:
        supplied = prop["projected_workload"]
        if not isinstance(supplied, dict) or not supplied.get("source_url") or timestamp(supplied["asof_utc"]) > timestamp(prop["cutoff_utc"]):
            raise ValueError("PROJECTED_WORKLOAD_REQUIRES_PREGAME_SOURCE")
        from .contracts import number
        target = number(supplied["value"])
        if target <= 0:
            raise ValueError("POSITIVE_PROJECTED_WORKLOAD_REQUIRED")
        workload_complete = workload_complete and all(g.get("workload") is not None for g in games)
    discrete = prop["market"] != "fantasy_score" and all(float(v).is_integer() for v in values)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    summaries, baseline = {}, None
    for scenario, factor in (("BASELINE", 1.), ("WORKLOAD_DOWN" if workload_complete else "LOW_OUTCOME_TILT", .85), ("WORKLOAD_UP" if workload_complete else "HIGH_OUTCOME_TILT", 1.15)):
        scenario_weights = weights if workload_complete or factor == 1 else [w * math.exp(max(-3, min(3, (v - center) / spread)) * (1 if factor > 1 else -1) * .4) for w, v in zip(weights, values)]
        cumulative, total = [], 0
        for weight in scenario_weights:
            total += weight
            cumulative.append(total)
        draws, digest = [], hashlib.sha256()
        path = root / (scenario.lower() + ".jsonl.gz")
        # Every sample is retained; receipt counts can be independently recomputed.
        with gzip.open(path, "wt", encoding="utf8") as out:
            for i in range(trials):
                index = min(len(games) - 1, bisect.bisect_left(cumulative, rng.random() * total))
                g = games[index]
                value = g["value"]
                if workload_complete:
                    opportunity = workloads[rng.randrange(len(workloads))]
                    opportunity *= target / statistics.median(workloads) * factor
                    value *= opportunity / g["workload"]
                    if discrete:
                        floor = math.floor(value)
                        value = floor + int(rng.random() < value - floor)
                value = float(value)
                digest.update(struct.pack("!d", value))
                draws.append(value)
                out.write(json.dumps({"trial": i, "source_game_id": g["game_id"], "value": value}, separators=(",", ":")) + "\n")
        ordered = sorted(draws)
        summary = {**probabilities(draws, prop["line"]), "trials": trials, "mean": statistics.mean(draws), "p10": ordered[int(.1 * (trials - 1))], "median": ordered[(trials - 1) // 2], "p90": ordered[int(.9 * (trials - 1))], "draws_sha256": digest.hexdigest(), "trace_file": str(path.name), "trace_sha256": sha(path.read_bytes()), "scenario": scenario, "assumption": "Observed opportunities shifted +/-15%; not an availability forecast" if factor != 1 and workload_complete else "Observed outcome distribution reweighted; not a measured matchup effect" if factor != 1 else "Observed-game resampling with recency and modest same-opponent weighting"}
        summaries[scenario] = summary
        if scenario == "BASELINE":
            baseline = draws
    ladder = [{"line": prop["line"] + delta, **probabilities(baseline, prop["line"] + delta)} for delta in (-2, -1, -.5, 0, .5, 1, 2)]
    selected = choose(summaries["BASELINE"])
    if summaries["BASELINE"]["p_push"] == 1:
        raise ValueError("ALL_SIMULATED_OUTCOMES_PUSH_NO_DIRECTIONAL_FORECAST")
    flips = [s for s, p in summaries.items() if s != "BASELINE" and choose(p) != selected]
    mass = summaries["BASELINE"]["p_over" if selected == "OVER" else "p_under"]
    z, n = 1.96, trials
    radius = z * math.sqrt(mass * (1 - mass) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    midpoint = (mass + z * z / (2 * n)) / (1 + z * z / n)
    return {"model": "BENFRANK_" + prop["sport"] + "_EMPIRICAL_WORKLOAD_" + VERSION, "algorithm": "Sequential observed-game bootstrap; not a full play-by-play sports simulator", "input_sha256": input_hash, "seed": seed, "baseline_trials": trials, "total_trials_including_stress": 3 * trials, "scenarios": summaries, "side": selected, "sensitivity": ladder, "scenario_reversals": flips, "mc_interval_only": [max(0, midpoint - radius), min(1, midpoint + radius)], "effective_history_n": sum(weights)**2 / sum(w*w for w in weights), "workload": {"observed_games": len(workloads), "applied": workload_complete, "target": target, "method": "Supplied sourced projection" if prop.get("projected_workload") else "Recent observed median"}, "calibrated": False}


def feature(games):
    avg = lambda n: statistics.mean(g["value"] for g in games[-n:])
    workload = [g["workload"] for g in games[-3:] if g.get("workload") is not None]
    return [avg(3), avg(10), avg(20), statistics.median(workload) if workload else 0., avg(3) - avg(20)]


def blind(games):
    train = []
    for i in range(5, len(games)):
        prior = [g for g in games[:i] if (timestamp(g.get("available_after_utc") or g.get("completed_utc")) if g.get("available_after_utc") or g.get("completed_utc") else timestamp(g["start_utc"]) + dt.timedelta(hours=18)) < timestamp(games[i]["start_utc"])]
        if len(prior) >= 5:
            train.append({"x": feature(prior), "y": games[i]["value"]})
    if len(train) < 20:
        return {"status": "INSUFFICIENT_CHRONOLOGICAL_TRAINING", "training_n": len(train), "required": 20, "line_received": False, "validated": False}
    data = {"train": train, "candidate": feature(games), "ridge": .15}
    worker = Path(__file__).resolve().parents[1] / "benfrank_v44_blind_worker.py"
    with tempfile.TemporaryDirectory(prefix="omni-blind-") as temp:
        result = subprocess.run([sys.executable, "-I", str(worker)], input=json.dumps(data, allow_nan=False), text=True, capture_output=True, cwd=temp, timeout=30)
    if result.returncode:
        raise ValueError("LINE_BLIND_WORKER_FAILED:" + result.stdout[-200:])
    forecast = json.loads(result.stdout)
    forecast.update(worker_sha256=sha(worker.read_bytes()), payload_sha256=sha(data), independence="Separate process, same source history, numeric lagged features only; no line, sport identity, primary forecast or decision", validated=False)
    return forecast


def dna(games, prop):
    over, under = [[g for g in games if side(g["value"], prop["line"]) == s] for s in ("OVER", "UNDER")]
    def group(rows):
        workload = [g["workload"] for g in rows if g.get("workload") is not None]
        return {"n": len(rows), "mean_result": statistics.mean(g["value"] for g in rows) if rows else None, "mean_workload": statistics.mean(workload) if workload else None, "observed_examples": [{"game_id": g["game_id"], "value": g["value"], "workload": g.get("workload"), "opponent": g["opponent"]} for g in rows[-3:]]}
    return {"covered_over": group(over), "covered_under": group(under), "interpretation": "Observed associations, not causal explanations or guaranteed future paths"}
