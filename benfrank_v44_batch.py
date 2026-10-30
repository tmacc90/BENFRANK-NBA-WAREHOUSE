"""v4.4 batch controller: one prop or more, exact-line isolation, fail-closed evidence receipts.

Runs the provisional engine without changing source SQLite. Source-backed
v47_context inputs additionally execute the repaired possession-level model;
the legacy bootstrap and minute proxy retain their separate labels.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import sqlite3
import tempfile
from pathlib import Path

from benfrank_v44_audit import build_receipt
from benfrank_v44_governance import governing_receipt
from benfrank_v44_blind_orchestrator import run_separate
from engine import MARKETS
from production import report

UTC = dt.timezone.utc


def parse_instant(value):
    stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return stamp.astimezone(UTC)


def stage(evidence, name, source, asof, detail):
    evidence[name] = {"status": "PASS", "source": source, "asof": asof, "detail": detail}


def input_evidence(prop, now):
    e = {}
    when = now.isoformat()
    stage(e, "market_support", "engine.py MARKETS registry", when,
          "Market has an implemented provisional baseline adapter; this does not imply full 68-market coverage")
    for key, name in [("player", "prop_identity"), ("game_date", "game_date"),
                      ("opponent", "opponent_identity")]:
        if prop.get(key):
            stage(e, name, "submitted prop payload", when,
                  "Captured from input only; independent official identity / schedule verification remains blocked")
    capture = prop.get("captured_at")
    cutoff = None
    if capture:
        cutoff = parse_instant(capture)
        tipoff = parse_instant(prop["tipoff_utc"]) if prop.get("tipoff_utc") else None
        if tipoff and cutoff >= tipoff:
            raise ValueError("captured_at must precede tipoff_utc")
        if cutoff.date() > dt.date.fromisoformat(prop["game_date"]):
            raise ValueError("captured_at occurs after game date")
        if tipoff:
            stage(e, "asof_timestamp", "submitted captured_at + tipoff_utc", when,
                  "Pregame ordering checked; official tipoff not independently verified")
    if all(prop.get(x) for x in ("platform", "snapshot_id", "captured_at")):
        stage(e, "exact_line", "submitted " + str(prop["platform"]) + " snapshot " + str(prop["snapshot_id"]), when,
              "Immutable exact-line input captured; external book verification not performed")
    return e, (cutoff.isoformat() if cutoff else prop["game_date"] + "T00:00:00+00:00")


def enrich_from_baseline(e, base, prop, now):
    when = now.isoformat()
    windows = base.get("windows", {})
    for k, name, required in [("L5", "recent_L5", 5), ("L10", "recent_L10", 10),
                              ("L15", "recent_L15", 15), ("L20", "recent_L20", 20)]:
        w = windows.get(k) or {}
        if w.get("n", 0) >= required:
            stage(e, name, "existing warehouse games table + engine.py window_summary", when,
                  f"Computed n={w['n']} historical games; source verification is separate")
    if (windows.get("career") or {}).get("n", 0) >= 3:
        # Not counted as 'career complete': this may be a subset of the player's career.
        pass
    l10 = windows.get("L10") or {}
    if l10.get("n", 0) >= 10:
        stage(e, "exact_line_mirror", "existing warehouse games table + engine.py exact-line counts", when,
              f"At exact line {prop['line']}: MORE={l10.get('more')}, LESS={l10.get('less')}, PUSH={l10.get('push')}; no odds implied")
        if l10.get("stdev") is not None:
            stage(e, "variance", "engine.py window_summary standard deviation", when,
                  "Historical L10 variability calculated; small-sample uncertainty remains")
        if l10.get("minutes_avg") is not None:
            stage(e, "minutes_distribution", "engine.py L10 minute aggregates", when,
                  "Historical minutes measured; future role/minutes not verified")
        for name in ("more_case", "less_case"):
            stage(e, name, "engine.py exact-line L10 outcome counts", when,
                  "Recorded historical side counts; not a predictive winning probability")
    forecast = base.get("baseline_projection")
    if forecast is not None and math.isfinite(float(forecast)):
        stage(e, "exact_line_margin", "engine.py provisional blended forecast", when,
              f"Projection {forecast}; exact line {prop['line']}; correlated-window heuristic, uncalibrated")


def stress_diagnostics(base, line):
    pred = base.get("baseline_projection")
    if pred is None:
        return {"status": "INSUFFICIENT_DATA", "scenarios": []}
    pred = float(pred)
    return {"status": "HEURISTIC_ONLY_NOT_FULL_HELL",
            "scenarios": [
                {"name": "baseline", "projection": round(pred, 3)},
                {"name": "minutes_down_10pct", "projection": round(pred * 0.9, 3)},
                {"name": "minutes_down_20pct", "projection": round(pred * 0.8, 3)},
                {"name": "efficiency_down_10pct", "projection": round(pred * 0.9, 3)},
                {"name": "opportunities_up_10pct", "projection": round(pred * 1.1, 3)}],
            "adverse_20pct_crosses_line": pred > line and pred * 0.8 <= line,
            "warning": "Simple scale stress only; cannot substitute for opponent, teammate, or possession modeling"}


def repaired_execution(prop,trials):
    context=prop.get('v47_context')
    if context is None:return None
    if not isinstance(context,dict):raise ValueError('v47_context must be source-backed JSON')
    if context.get('input_mode')!='RECONSTRUCTED_ASOF_WITH_ORIGINAL_OFFICIAL_AVAILABILITY':
        raise ValueError('Unsupported v4.7 context provenance mode')
    for key in ('game_date','snapshot_id'):
        if not prop.get(key) or prop[key]!=context.get(key):raise ValueError('V47_PROP_CONTEXT_CONFLICT: '+key)
    if prop.get('game_id') and prop['game_id']!=context.get('game_id'):
        raise ValueError('V47_PROP_CONTEXT_CONFLICT: game_id')
    if str(prop.get('platform','')).casefold()!=str(context.get('platform','')).casefold():
        raise ValueError('V47_PROP_CONTEXT_PLATFORM_CONFLICT')
    if parse_instant(prop['captured_at'])!=parse_instant(context['line_capture_utc']):
        raise ValueError('V47_PROP_CONTEXT_CAPTURE_CONFLICT')
    if parse_instant(prop['tipoff_utc'])!=parse_instant(context['tipoff_utc']):
        raise ValueError('V47_PROP_CONTEXT_TIPOFF_CONFLICT')
    if parse_instant(context['official_report_time_utc'])>parse_instant(prop['captured_at']):
        raise ValueError('V47_OFFICIAL_REPORT_AFTER_CAPTURE')
    if context['max_feature_game_date']>=prop['game_date']:raise ValueError('V47_TARGET_OR_FUTURE_FEATURE')
    for team,roster in context['rosters'].items():
        if prop['player'] in {p['player'] for p in roster}:
            if prop['opponent'] not in {context['home'],context['away']}-{team}:
                raise ValueError('V47_TARGET_OPPONENT_CONFLICT')
    calibration=prop.get('v47_calibration')
    if calibration is None:
        calibration=json.loads(Path(__file__).with_name('models').joinpath('v47_prizepicks_points_25_30_calibration.json').read_text())
    from benfrank_v47_run import run
    return run(context,prop['player'],prop['market'],prop['line'],prop['platform'],calibration,trials)


def run_one(connection, prop, trials=25000, db_integrity=False):
    now = dt.datetime.now(UTC)
    if not isinstance(prop, dict):
        raise ValueError("Each prop must be a JSON object")
    # A missing required field is a data error, not an opportunity to guess.
    required = ("player", "market", "line", "opponent", "game_date")
    missing = [k for k in required if not prop.get(k) and prop.get(k) != 0]
    if missing:
        raise ValueError("Missing fields: " + ", ".join(missing))
    if prop["market"] not in MARKETS:
        raise ValueError("Market not implemented in current engine: " + str(prop["market"]))
    if not isinstance(prop["line"], (int, float)) or isinstance(prop["line"], bool) or not math.isfinite(prop["line"]):
        raise ValueError("Line must be a finite number")
    dt.date.fromisoformat(prop["game_date"])
    e, cutoff = input_evidence(prop, now)
    base = report(connection, prop["player"], prop["market"], prop["line"],
                  prop["opponent"], asof=prop["game_date"], cutoff=cutoff, trials=trials)
    enrich_from_baseline(e, base, prop, now)
    if db_integrity:
        stage(e, "warehouse_integrity", "SQLite PRAGMA integrity_check on isolated database copy", now.isoformat(),
              "Structural integrity passed; not a statement about historical coverage or source accuracy")
    audit = build_receipt({k: prop[k] for k in ("player", "market", "line", "opponent", "game_date")}, e)
    prediction = base.get("baseline_projection")
    repaired=repaired_execution(prop,trials)
    if repaired is not None:
        forecast=repaired.get('forecast') or {}
        prediction=forecast.get('mean_adjusted',forecast.get('mean'))
        execution=repaired['simulation']
        if execution.get('trials_executed',0)>=25000:
            stage(e,'sequential_twon_25000','benfrank_v47_model.py actual complete-game execution',now.isoformat(),
                  f"Actual games={execution['trials_executed']}; voids={execution.get('void_count',0)}; model/source qualification remains separate")
        audit=build_receipt({k:prop[k] for k in ('player','market','line','opponent','game_date')},e)
    direction = ("MORE" if prediction > prop["line"] else "LESS" if prediction < prop["line"] else "UNRESOLVED") if prediction is not None else "UNRESOLVED"
    if repaired is not None:
        direction={'OVER':'MORE','UNDER':'LESS'}.get(repaired.get('direction'),'UNRESOLVED')
    margin = round(prediction - prop["line"], 3) if prediction is not None else None
    # Dedicated child process cannot receive prop line or primary forecast.
    challenger = run_separate(connection, prop["player"], prop["market"], prop["game_date"])
    challenger_value = challenger.get("projection") if challenger.get("status") == "EXECUTED_PROCESS_SEPARATE_ML" else None
    if challenger_value is not None and prediction is not None:
        competitor_direction = "OVER" if challenger_value > prop["line"] else "UNDER" if challenger_value < prop["line"] else "PUSH"
        preliminary_direction = {"MORE":"OVER","LESS":"UNDER"}.get(direction,"PUSH")
        disagreement = competitor_direction != preliminary_direction
        stage(e, "model_disagreement", "benfrank_v44_blind_orchestrator.py separate ML process", now.isoformat(),
              "Independent post-hoc disagreement checked; challenger not calibrated or production-certified")
        audit = build_receipt({k: prop[k] for k in ("player", "market", "line", "opponent", "game_date")}, e)
    else:
        disagreement = None
    direction_label = ("OVER" if direction == "MORE" else "UNDER" if direction == "LESS" else "UNRESOLVED")
    governing = governing_receipt(prop, audit["stages"], direction_label, "NO_TICKET",
                                  execution_receipt=repaired['simulation'] if repaired else None)
    return {"player": prop["player"], "market": prop["market"], "line": prop["line"],
            "opponent": prop["opponent"], "game_date": prop["game_date"],
            "direction": direction_label, "direction_status": "PROVISIONAL_NO_TICKET" if direction != "UNRESOLVED" else "NO_EVIDENCE",
            "projection": prediction, "margin": margin,
            "historical_games": base.get("games_available"), "historical_windows": base.get("windows"),
            "empirical_bootstrap": base.get("simulation"),
            "minute_proxy": base.get("sequential_minute_proxy"),
            "availability_aware_twon": repaired,
            "legacy_baseline_projection":base.get('baseline_projection'),
            "blind_statistical_formula": base.get("blind_statistical_model"),
            "blind_ml_challenger": challenger,
            "blind_ml_disagreement": disagreement,
            "stress_diagnostics": stress_diagnostics(base, prop["line"]),
            "official_coverage_certified": False, "possession_twon_certified": False,
            "independent_blind_ai_certified": False, "calibration_certified": False,
            "ticket_authority": "NO_TICKET", "audit": audit, "governing_66": governing}


def run_board(db_path, props, trials=25000):
    """Use SQLite backup to protect warehouse. No CSV or database mutation in the source."""
    if not isinstance(props, list) or not props:
        raise ValueError("Board must be a non-empty JSON array (one prop or more)")
    if not 1 <= trials <= 250000:
        raise ValueError("trials must be 1-250000")
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError("Warehouse not found; historical records cannot be assumed: " + str(db_path))
    result = {"framework": "BENFRANK NBA v4.4", "input_count": len(props),
              "results": [], "status": "PROVISIONAL_ONLY"}
    with tempfile.TemporaryDirectory(prefix="benfrank-v44-") as tmp:
        target = Path(tmp) / "isolated.sqlite"
        source = sqlite3.connect("file:" + str(db_path.resolve()) + "?mode=ro", uri=True)
        try:
            copy = sqlite3.connect(str(target))
            try:
                source.backup(copy)
                integrity = copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                if not integrity:
                    raise RuntimeError("SQLite copy failed integrity check")
                copy.row_factory = sqlite3.Row
                for i, prop in enumerate(props):
                    try:
                        outcome = run_one(copy, prop, trials=trials, db_integrity=True)
                        result["results"].append({"index": i, "status": "ANALYZED_PROVISIONAL", **outcome})
                    except Exception as exc:
                        result["results"].append({"index": i, "status": "BLOCKED", "error": str(exc),
                                                  "player": prop.get("player") if isinstance(prop, dict) else None})
            finally:
                copy.close()
        finally:
            source.close()
    result["analyzed_count"] = sum(r["status"] == "ANALYZED_PROVISIONAL" for r in result["results"])
    result["blocked_count"] = len(props) - result["analyzed_count"]
    result["board_sha256"] = hashlib.sha256(json.dumps(props, sort_keys=True).encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description="Fail-closed one-or-more prop controller")
    parser.add_argument("--db", required=True, help="Existing source warehouse SQLite file (read-only)")
    parser.add_argument("--board", required=True, help="JSON array containing one prop or more")
    parser.add_argument("--output", required=True, help="Write full evidence receipts to this JSON file")
    parser.add_argument("--trials", type=int, default=25000, help="Per-prop trials; v47_context executes actual games and requires 25000-50000")
    args = parser.parse_args()
    board = json.loads(Path(args.board).read_text(encoding="utf-8"))
    result = run_board(args.db, board, args.trials)
    from benfrank_v47_run import save_receipt
    save_receipt(args.output,result)
    print(json.dumps({"framework": result["framework"], "input_count": result["input_count"],
                      "analyzed_count": result["analyzed_count"], "blocked_count": result["blocked_count"],
                      "output": args.output, "ticket_authority": "NO_TICKET"}, indent=2))


if __name__ == "__main__":
    main()
