"""Chronological NBA prop probability audit; no synthetic lines or postgame leakage.

Requires real immutable pre-tipoff snapshot records. Works from a copied or read-only
SQLite warehouse. Fixed hypothetical lines are never passed off as historical odds.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import sqlite3
import statistics
from pathlib import Path

from engine import MARKETS, stat

MIN_TRAIN = 30
MIN_TEST = 20

def instant(value):
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must contain a timezone")
    return parsed.astimezone(dt.timezone.utc)

def check_snapshot(snapshot):
    required = ("player", "market", "line", "opponent", "game_date",
                "platform", "snapshot_id", "captured_at", "tipoff_utc")
    if not isinstance(snapshot, dict):
        raise ValueError("Prop snapshot must be a JSON object")
    missing = [k for k in required if k not in snapshot or snapshot[k] in (None, "")]
    if missing:
        raise ValueError("Snapshot missing: " + ", ".join(missing))
    if snapshot["market"] not in MARKETS:
        raise ValueError("Unsupported existing engine market")
    if isinstance(snapshot["line"], bool) or not isinstance(snapshot["line"], (float, int)) or not math.isfinite(snapshot["line"]):
        raise ValueError("Exact line must be a finite number")
    date = dt.date.fromisoformat(snapshot["game_date"])
    capture = instant(snapshot["captured_at"])
    tipoff = instant(snapshot["tipoff_utc"])
    if capture >= tipoff:
        raise ValueError("Snapshot captured at/after tipoff")
    if tipoff.date() < date - dt.timedelta(days=1) or tipoff.date() > date + dt.timedelta(days=1):
        raise ValueError("Tipoff UTC date inconsistent with local game date")
    if snapshot["market"] == "fantasy_score" and not snapshot.get("scoring_contract"):
        raise ValueError("Fantasy Score requires an explicit platform scoring contract")
    return capture, tipoff

def record_verified(conn, row):
    sources = {x[0] for x in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    rel = "verified_history" if "verified_history" in sources else (
        "game_verifications" if "game_verifications" in sources else None)
    if not rel:
        return False
    try:
        hit = conn.execute(
            "SELECT 1 FROM " + rel + " WHERE player=? AND date=? AND team=? LIMIT 1",
            (row["player"], row["date"], row["team"])).fetchone()
        return hit is not None
    except sqlite3.OperationalError:
        return False

def probability_from_history(history, market, line):
    """Fixed prior 20-game empirical hit distribution with Jeffreys shrinkage."""
    if len(history) < 12:
        return None
    values = [stat(row, market) for row in history[:20]]
    over = sum(v > line for v in values)
    under = sum(v < line for v in values)
    pushes = len(values) - over - under
    nonpush = over + under
    if nonpush < 10:
        return None
    return {"p_over_raw": round((over + 1.0) / (nonpush + 2.0), 8),
            "p_under_raw": round((under + 1.0) / (nonpush + 2.0), 8),
            "history_n": len(values), "history_nonpush_n": nonpush,
            "history_push_n": pushes,
            "historical_mean": round(statistics.mean(values), 4),
            "method": "Beta(1,1) smoothed empirical exact-line hit counts; not calibrated"}

def fit_isotonic(rows):
    """Fit nondecreasing bin predictions with a pooled adjacent violators algorithm."""
    blocks = []
    for p, y in sorted(rows, key=lambda x: x[0]):
        blocks.append([float(p), float(p), float(y), 1])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks[-1]
            left[1] = right[1]
            left[2] += right[2]
            left[3] += right[3]
    return [{"min": a, "max": b, "rate": (s + 1) / (n + 2), "n": n}
            for a, b, s, n in blocks]

def calibrate(p, blocks):
    if not blocks:
        raise ValueError("Calibration requires fitted blocks")
    for block in blocks:
        if p <= block["max"]:
            return block["rate"]
    return blocks[-1]["rate"]

def scores(rows, field):
    if not rows:
        return None
    probabilities = [min(1 - 1e-6, max(1e-6, float(r[field]))) for r in rows]
    outcomes = [r["over_result"] for r in rows]
    return {"n": len(rows),
            "brier": round(statistics.mean((p - y)**2 for p, y in zip(probabilities, outcomes)), 6),
            "log_loss": round(statistics.mean(-y*math.log(p) - (1-y)*math.log(1-p)
                                              for p, y in zip(probabilities, outcomes)), 6),
            "directional_accuracy": round(statistics.mean(
                int((p > .5 and y == 1) or (p < .5 and y == 0))
                for p, y in zip(probabilities, outcomes)), 6)}

def evaluate(conn, snapshots, min_train=MIN_TRAIN, min_test=MIN_TEST):
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("Real snapshot JSON array required; no fixed-line substitutions")
    known = set()
    normalized = []
    for s in snapshots:
        capture, tipoff = check_snapshot(s)
        identity = (s["platform"], s["snapshot_id"], s["player"], s["market"], s["game_date"])
        if identity in known:
            raise ValueError("Duplicate snapshot identity; immutable history required")
        known.add(identity)
        normalized.append((tipoff, capture, s))
    normalized.sort(key=lambda x: (x[0], x[1]))
    rows = []
    rejected = []
    for tipoff, capture, s in normalized:
        observed = conn.execute(
            "SELECT * FROM games WHERE lower(player)=lower(?) AND date=? AND lower(opponent)=lower(?)",
            (s["player"], s["game_date"], s["opponent"])).fetchall()
        if len(observed) != 1:
            rejected.append({"snapshot_id": s["snapshot_id"], "reason": "SETTLEMENT_NOT_UNIQUE_OR_MISSING"})
            continue
        result = stat(observed[0], s["market"])
        if result == s["line"]:
            rejected.append({"snapshot_id": s["snapshot_id"], "reason": "EXACT_LINE_PUSH_EXCLUDED_FROM_BINARY_CALIBRATION"})
            continue
        history = conn.execute(
            "SELECT * FROM games WHERE lower(player)=lower(?) AND date<? ORDER BY date DESC",
            (s["player"], s["game_date"])).fetchall()
        probability = probability_from_history(history, s["market"], s["line"])
        if probability is None:
            rejected.append({"snapshot_id": s["snapshot_id"], "reason": "INSUFFICIENT_PREGAME_HISTORY"})
            continue
        if s["market"] == "fantasy_score":
            # Scoring contract must be explicitly compatible with engine weights.
            if s["scoring_contract"] != "PTS1_REB1.2_AST1.5_STL3_BLK3_TOV-1":
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": "UNSUPPORTED_PLATFORM_SCORING_CONTRACT"})
                continue
        rows.append({"snapshot_id": s["snapshot_id"], "player": s["player"],
                     "market": s["market"], "date": s["game_date"], "tipoff_utc": tipoff.isoformat(),
                     "captured_at": capture.isoformat(), "line": s["line"],
                     "actual": result, "over_result": int(result > s["line"]),
                     "official_game_verified": record_verified(conn, observed[0]), **probability})
    result = {"method": "chronological snapshot-level probability calibration",
              "input_snapshots": len(snapshots), "eligible": len(rows),
              "rejected": rejected, "certification": "NOT_CERTIFIED",
              "ticket_authority": "NO_TICKET",
              "snapshot_sha256": hashlib.sha256(json.dumps(snapshots, sort_keys=True).encode()).hexdigest(),
              "chronological_cutoff_policy": "Every snapshot timestamp must precede tipoff; game history must precede game date",
              "fixed_line_backtest": False}
    if len(rows) < min_train + min_test:
        result.update({"status": "INSUFFICIENT_SNAPSHOTS",
                      "required_eligible": min_train + min_test,
                      "official_verified_eligible": sum(x["official_game_verified"] for x in rows)})
        return result
    # Strict forward split. No held-out outcome contributes to isotonic fit.
    split = max(min_train, int(len(rows)*0.6))
    split = min(split, len(rows) - min_test)
    train, test = rows[:split], rows[split:]
    model = fit_isotonic([(r["p_over_raw"], r["over_result"]) for r in train])
    for r in test:
        r["p_over_calibrated"] = calibrate(r["p_over_raw"], model)
    result.update({
        "status": "EVALUATED_UNCERTIFIED",
        "train_n": len(train),
        "holdout_n": len(test),
        "train_latest_tipoff": train[-1]["tipoff_utc"],
        "holdout_earliest_tipoff": test[0]["tipoff_utc"],
        "official_verified_eligible": sum(x["official_game_verified"] for x in rows),
        "all_eligible_official_verified": all(x["official_game_verified"] for x in rows),
        "raw_holdout": scores(test, "p_over_raw"),
        "calibrated_holdout": scores(test, "p_over_calibrated"),
        "isotonic_bins": model,
        "holdout_results": test,
        "warning": "No certified deployment threshold, independent multi-season test, or future-prop winning probability is claimed"
    })
    if not result["all_eligible_official_verified"]:
        result["status"] = "EVALUATED_SOURCE_VERIFICATION_PENDING"
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--snapshots", required=True, help="Actual pregame exact-line snapshot array")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    if not Path(a.db).is_file():
        raise SystemExit("Existing verified historical warehouse is required")
    snapshots = json.loads(Path(a.snapshots).read_text())
    conn = sqlite3.connect("file:" + str(Path(a.db).resolve()) + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        result = evaluate(conn, snapshots)
    finally:
        conn.close()
    Path(a.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result.get(k) for k in
                      ("status","input_snapshots","eligible","official_verified_eligible","train_n","holdout_n","certification")}))
    if result["status"] == "INSUFFICIENT_SNAPSHOTS":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
