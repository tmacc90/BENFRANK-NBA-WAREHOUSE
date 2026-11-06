"""Append-only, per-sport forecasts/results and chronological calibration."""
import json
import math
import sqlite3
from pathlib import Path

from . import VERSION
from .contracts import SPORTS, canonical, now, number, sha, timestamp


def connect(state, sport):
    if sport not in SPORTS:
        raise ValueError("UNKNOWN_LEDGER_SPORT")
    root = Path(state) / sport.lower()
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "forecast_ledger.sqlite", timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS identity(sport TEXT PRIMARY KEY)")
    identities = [r[0] for r in conn.execute("SELECT sport FROM identity")]
    if identities and identities != [sport]:
        conn.close()
        raise ValueError("CROSS_SPORT_LEDGER_REJECTED")
    conn.execute("INSERT OR IGNORE INTO identity VALUES (?)", (sport,))
    conn.execute("CREATE TABLE IF NOT EXISTS forecasts(prop_id TEXT PRIMARY KEY, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS settlements(prop_id TEXT PRIMARY KEY REFERENCES forecasts(prop_id), receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
    for table in ("identity", "forecasts", "settlements"):
        for action in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY_LEDGER'); END")
    conn.commit()
    return conn


def record(state, result):
    sport = result["prop"]["sport"]
    conn = connect(state, sport)
    try:
        frozen = {**result, "ledger_recorded_at_utc": now()}
        if result["mode"] == "PREGAME" and not timestamp(result["prop"]["cutoff_utc"]) <= timestamp(frozen["ledger_recorded_at_utc"]) < timestamp(result["prop"]["event_start_utc"]):
            raise ValueError("CANNOT_RECORD_POSTGAME_RESULT_AS_PREGAME_FORECAST")
        raw, digest = canonical(frozen).decode(), sha(frozen)
        existing = conn.execute("SELECT receipt,receipt_sha256 FROM forecasts WHERE prop_id=?", (result["prop"]["prop_id"],)).fetchone()
        if existing:
            previous = json.loads(existing[0])
            if sha(previous) != existing[1]:
                raise ValueError("FORECAST_LEDGER_HASH_MISMATCH")
            previous.pop("ledger_recorded_at_utc", None)
            if sha(previous) != sha(result):
                raise ValueError("FROZEN_FORECAST_ALREADY_EXISTS")
            return
        conn.execute("INSERT INTO forecasts VALUES (?,?,?)", (result["prop"]["prop_id"], raw, digest))
        conn.commit()
    finally:
        conn.close()


def settle(state, sport, outcomes):
    conn = connect(state, sport)
    count = 0
    try:
        # Validate the entire batch before inserting any result.
        pending = []
        for outcome in outcomes:
            raw = conn.execute("SELECT receipt,receipt_sha256 FROM forecasts WHERE prop_id=?", (outcome["prop_id"],)).fetchone()
            if not raw:
                raise ValueError("UNKNOWN_FROZEN_FORECAST")
            forecast = json.loads(raw[0])
            if sha(forecast) != raw[1]:
                raise ValueError("FORECAST_LEDGER_HASH_MISMATCH")
            prop = forecast["prop"]
            if any(str(outcome.get(k)) != str(prop[k]) for k in ("sport", "event_id", "player_id", "market")):
                raise ValueError("SETTLEMENT_IDENTITY_MISMATCH")
            if not outcome.get("source_url") or not outcome.get("source_sha256") or not outcome.get("completed"):
                raise ValueError("COMPLETED_RESULT_AND_SOURCE_REQUIRED")
            if timestamp(outcome["retrieved_at_utc"]) <= timestamp(prop["event_start_utc"]) or timestamp(outcome["retrieved_at_utc"]) > timestamp(now()):
                raise ValueError("SETTLEMENT_TIME_INVALID")
            status = outcome.get("status", "SETTLED")
            if status not in ("SETTLED", "VOID"):
                raise ValueError("EXPLICIT_SETTLEMENT_STATUS_REQUIRED")
            value = None if status == "VOID" else number(outcome["value"])
            record = {**outcome, "value": value, "recorded_at_utc": now(), "outcome": "VOID" if status == "VOID" else "OVER" if value > prop["line"] else "UNDER" if value < prop["line"] else "PUSH"}
            pending.append((outcome["prop_id"], canonical(record).decode(), sha(record)))
        conn.executemany("INSERT INTO settlements VALUES (?,?,?)", pending)
        conn.commit()
        count = len(pending)
    finally:
        conn.close()
    return {"sport": sport, "settled": count, "accuracy_certified": False}


def stratum(prop):
    # Exact scope, platform/scoring rules and version; no pooling across sports.
    return sha({"sport": prop["sport"], "market": prop["market"], "scope": prop["scope"], "rules": prop["rules"], "platform": prop.get("platform", "UNSPECIFIED"), "code_revision": prop.get("execution_code_sha256"), "version": VERSION})


def isotonic(rows):
    groups = {}
    for row in rows:
        p = row["p"]
        item = groups.setdefault(p, [0., 0])
        item[0] += row["y"]
        item[1] += 1
    blocks = []
    for p, (wins, n) in sorted(groups.items()):
        blocks.append({"low": p, "high": p, "wins": wins, "n": n})
        while len(blocks) > 1 and blocks[-2]["wins"] / blocks[-2]["n"] > blocks[-1]["wins"] / blocks[-1]["n"]:
            a, b = blocks[-2:]
            blocks[-2:] = [{"low": a["low"], "high": b["high"], "wins": a["wins"] + b["wins"], "n": a["n"] + b["n"]}]
    # A fixed beta(1,1) avoids falsely certain 0/1 probabilities.
    for b in blocks:
        b["rate"] = (b["wins"] + 1) / (b["n"] + 2)
    # Independent smoothing can break monotonicity: pool again on final rates.
    while any(a["rate"] > b["rate"] for a, b in zip(blocks, blocks[1:])):
        merged = []
        for b in blocks:
            merged.append(b)
            while len(merged) > 1 and merged[-2]["rate"] > merged[-1]["rate"]:
                a, c = merged[-2:]
                wins, n = a["wins"] + c["wins"], a["n"] + c["n"]
                merged[-2:] = [{"low": a["low"], "high": c["high"], "wins": wins, "n": n, "rate": (wins + 1) / (n + 2)}]
        blocks = merged
    return blocks


def calibrated_probability(blocks, p):
    if not blocks:
        raise ValueError("EMPTY_CALIBRATION_MODEL")
    for i, block in enumerate(blocks):
        boundary = (block["high"] + blocks[i+1]["low"]) / 2 if i + 1 < len(blocks) else 1
        if p <= boundary:
            return block["rate"]
    return blocks[-1]["rate"]


def metrics(rows, ps):
    return {"n": len(rows), "brier": sum((p - r["y"])**2 for r, p in zip(rows, ps)) / len(rows), "log_loss": -sum(r["y"] * math.log(max(1e-9, p)) + (1-r["y"]) * math.log(max(1e-9, 1-p)) for r, p in zip(rows, ps)) / len(rows)}


def fit_rows(rows, *, sport, market, key, min_train=100, min_test_events=30):
    if min_train < 100 or min_test_events < 30:
        raise ValueError("CALIBRATION_MINIMUMS_CANNOT_BE_LOWERED")
    rows = sorted(rows, key=lambda r: (timestamp(r["event_start_utc"]), r["event_id"], r["prop_id"]))
    report = {"sport": sport, "market": market, "stratum": key, "version": VERSION, "fitted_at_utc": now(), "source_rows_sha256": sha(rows), "eligible_rows": len(rows), "accuracy_certified": False, "status": "INSUFFICIENT_GRADED_PREGAME_FORECASTS"}
    events = sorted({(timestamp(r["event_start_utc"]), r["event_id"]) for r in rows})
    if len(events) < min_test_events + 1:
        return report
    split = max(1, int(.7 * len(events)))
    split = min(split, len(events) - min_test_events)
    boundary = events[split][0]
    # Group every event at the same start time, including alternate lines, on one side.
    train = [r for r in rows if timestamp(r["event_start_utc"]) < boundary]
    test = [r for r in rows if timestamp(r["event_start_utc"]) >= boundary]
    test_events = {r["event_id"] for r in test}
    report.update(training_n=len(train), holdout_n=len(test), holdout_event_n=len(test_events), split_utc=boundary.isoformat())
    if len(train) < min_train or len(test_events) < min_test_events or len({r["y"] for r in train}) < 2:
        return report
    blocks = isotonic(train)
    raw = metrics(test, [r["p"] for r in test])
    calibrated = metrics(test, [calibrated_probability(blocks, r["p"]) for r in test])
    base = sum(r["y"] for r in train) / len(train)
    baseline = metrics(test, [base] * len(test))
    status = "VALIDATED_HOLDOUT" if calibrated["brier"] <= raw["brier"] and calibrated["brier"] < baseline["brier"] and calibrated["log_loss"] <= raw["log_loss"] else "REJECTED_HOLDOUT"
    report.update(status=status, blocks=blocks, raw_holdout=raw, calibrated_holdout=calibrated, constant_baseline_holdout=baseline, trained_event_ids=sorted({r["event_id"] for r in train}), evaluated_event_ids=sorted(test_events), trained_through_utc=max(r["event_start_utc"] for r in rows), usable_after_utc=now(), guarantee="Historical holdout results do not establish a future betting edge")
    return report


def calibrate(state, sport, market):
    conn = connect(state, sport)
    groups = {}
    try:
        for row in conn.execute("SELECT f.receipt f,f.receipt_sha256 fh,s.receipt s,s.receipt_sha256 sh FROM forecasts f JOIN settlements s USING(prop_id)"):
            forecast, settled = json.loads(row["f"]), json.loads(row["s"])
            if sha(forecast) != row["fh"] or sha(settled) != row["sh"]:
                raise ValueError("CALIBRATION_LEDGER_HASH_MISMATCH")
            p = forecast["prop"]
            if p["market"] != market or forecast["mode"] != "PREGAME" or forecast["version"] != VERSION or settled["outcome"] in ("PUSH", "VOID"):
                continue
            if not forecast.get("ledger_recorded_at_utc") or not timestamp(p["cutoff_utc"]) <= timestamp(forecast["ledger_recorded_at_utc"]) < timestamp(p["event_start_utc"]):
                continue
            probs = forecast["simulation"]["scenarios"]["BASELINE"]
            nonpush = probs["p_over"] + probs["p_under"]
            if nonpush <= 0:
                continue
            groups.setdefault(stratum(p), []).append({"prop_id": p["prop_id"], "event_id": p["event_id"], "event_start_utc": p["event_start_utc"], "p": probs["p_over"] / nonpush, "y": int(settled["outcome"] == "OVER")})
    finally:
        conn.close()
    reports = [fit_rows(rows, sport=sport, market=market, key=k) for k, rows in groups.items()]
    if not reports:
        reports = [{"sport": sport, "market": market, "version": VERSION, "status": "INSUFFICIENT_GRADED_PREGAME_FORECASTS", "eligible_rows": 0, "accuracy_certified": False}]
    root = Path(state) / sport.lower() / "calibration"
    root.mkdir(exist_ok=True)
    for report in reports:
        path = root / (sha(report) + ".json")
        if not path.exists():
            path.write_bytes(canonical(report))
    return reports


def apply_calibration(state, prop, probabilities):
    paths = sorted((Path(state) / prop["sport"].lower() / "calibration").glob("*.json"))
    models = []
    for path in paths:
        model = json.loads(path.read_text())
        if path.stem != sha(model):
            raise ValueError("CALIBRATION_MODEL_HASH_MISMATCH")
        models.append(model)
    models = [m for m in models if m.get("status") == "VALIDATED_HOLDOUT" and m.get("stratum") == stratum(prop) and m["version"] == VERSION and timestamp(m["usable_after_utc"]) <= timestamp(prop["cutoff_utc"])]
    if not models:
        return {"status": "NO_ELIGIBLE_MARKET_CALIBRATION", "applied": False, "accuracy_certified": False}
    model = max(models, key=lambda m: timestamp(m["usable_after_utc"]))
    mass = probabilities["p_over"] + probabilities["p_under"]
    if mass <= 0:
        return {"status": "NO_NONPUSH_MASS", "applied": False, "accuracy_certified": False}
    p = calibrated_probability(model["blocks"], probabilities["p_over"] / mass)
    return {"status": "APPLIED_HISTORICAL_HOLDOUT_CALIBRATION", "applied": True, "model_sha256": sha(model), "p_over": p * mass, "p_under": (1-p)*mass, "p_push": probabilities["p_push"], "push_mass_calibrated": False, "accuracy_certified": False}
