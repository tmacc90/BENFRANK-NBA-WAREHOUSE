"""BENFRANK Stage 24 calibration receipt.

Stage 24A and 24B are intentionally separate:
- 24A: historical exact-line research evidence. Existing baseline studies may
  describe calibration behavior, but cannot calibrate a different simulator.
- 24B: live immutable BENFRANK forward-cohort maturity from the append-only
  early prediction/settlement ledger.

This module never silently promotes historical baseline calibration into the
current v5.2/lineup-enhanced simulator. A current-simulator calibration model
must be separately trained, versioned, validated, and supplied before any
probability may be labeled calibrated.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

LIVE_MIN_SETTLED = 50
LIVE_MIN_UNIQUE_GAMES = 30
DEFAULT_BASELINE = Path(__file__).with_name("diagnostics") / "v46-baseline-evaluation-20261030.json"


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _line_band(line: float, width: int = 5) -> tuple[int, int]:
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise ValueError("FINITE_LINE_REQUIRED")
    low = math.floor(float(line) / width) * width
    return int(low), int(low + width)


def _baseline_match(prop: dict[str, Any], baseline_path: str | Path = DEFAULT_BASELINE) -> dict[str, Any]:
    path = Path(baseline_path)
    if not path.is_file():
        return {
            "status": "MISSING_HISTORICAL_BASELINE_ARTIFACT",
            "quality": "LIMITED",
            "applicable_to_current_simulator": False,
        }
    doc = json.loads(path.read_text())
    platform = str(prop.get("platform") or "").lower()
    market = str(prop.get("market") or "")
    line = float(prop["line"])
    candidates = []
    for row in doc.get("stratum_metrics", []):
        if str(row.get("platform") or "").lower() != platform or row.get("market") != market:
            continue
        low = row.get("line_band_low")
        width = row.get("line_band_width")
        if not isinstance(low, (int, float)) or not isinstance(width, (int, float)) or width <= 0:
            continue
        if float(low) <= line < float(low) + float(width):
            candidates.append(row)
    if len(candidates) != 1:
        return {
            "status": "NO_UNIQUE_HISTORICAL_BASELINE_STRATUM",
            "quality": "LIMITED",
            "matching_strata": len(candidates),
            "baseline_sha256": _sha256(path),
            "applicable_to_current_simulator": False,
            "exact_reason": "Historical baseline is descriptive only and no unique exact platform/market/line band matched.",
        }
    row = candidates[0]
    evaluated = row.get("status") == "EVALUATED_BASELINE_ONLY" and row.get("raw_holdout") and row.get("calibrated_holdout")
    return {
        "status": row.get("status"),
        "quality": "FULL" if evaluated else "LIMITED",
        "platform": row.get("platform"),
        "market": row.get("market"),
        "line_band": [row.get("line_band_low"), row.get("line_band_low", 0) + row.get("line_band_width", 0)],
        "train_n": row.get("train_n"),
        "train_games": row.get("train_games"),
        "holdout_n": row.get("holdout_n"),
        "holdout_games": row.get("holdout_games"),
        "raw_holdout": row.get("raw_holdout"),
        "historically_calibrated_holdout": row.get("calibrated_holdout"),
        "brier_delta": row.get("brier_delta"),
        "baseline_model": doc.get("model"),
        "baseline_status": doc.get("status"),
        "baseline_sha256": _sha256(path),
        "applicable_to_current_simulator": False,
        "exact_reason": "This artifact evaluates an empirical historical baseline, not the current v5.2 lineup-enhanced 25K simulator.",
    }


def live_maturity(ledger_path: str | Path) -> dict[str, Any]:
    """Read the live forward cohort without creating or mutating its ledger."""
    path = Path(ledger_path)
    if not path.is_file():
        return {
            "status": "LIVE_COHORT_NOT_STARTED",
            "quality": "LIMITED",
            "predictions_frozen": 0,
            "settlements": 0,
            "strata": [],
            "maturity_threshold": {
                "settled_nonpush_per_stratum": LIVE_MIN_SETTLED,
                "unique_games_per_stratum": LIVE_MIN_UNIQUE_GAMES,
            },
        }
    conn = sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"early_predictions", "early_settlements"} <= tables:
            raise ValueError("LIVE_LEDGER_SCHEMA_MISSING")
        predictions = {r["id"]: json.loads(r["payload_json"]) for r in conn.execute(
            "SELECT * FROM early_predictions ORDER BY issued_at,id")}
        settlements = [json.loads(r["payload_json"]) for r in conn.execute(
            "SELECT * FROM early_settlements ORDER BY observed_at,id")]
    finally:
        conn.close()

    # First-issued exact game/player/market/line/platform forecast only.
    first: dict[tuple[Any, ...], str] = {}
    cohort_ids = set()
    for rid, receipt in predictions.items():
        prop = receipt["prop"]
        key = tuple(prop.get(k, rid) for k in ("game_id", "player", "market", "line", "platform"))
        if key not in first:
            first[key] = rid
            cohort_ids.add(rid)

    groups: dict[tuple[str, str, tuple[int, int]], list[dict[str, Any]]] = {}
    for label in settlements:
        rid = label.get("prediction_id")
        if rid not in cohort_ids or label.get("outcome") == "PUSH":
            continue
        receipt = predictions[rid]
        prop = receipt["prop"]
        band = _line_band(float(prop["line"]))
        key = (str(prop.get("platform") or "").lower(), prop["market"], band)
        groups.setdefault(key, []).append({
            "game_id": prop.get("game_id"),
            "correct": label.get("correct"),
            "p_over_raw": receipt.get("main_simulation", {}).get("p_over_raw"),
            "outcome": label.get("outcome"),
        })

    strata = []
    for (platform, market, band), rows in sorted(groups.items()):
        valid = [r for r in rows if isinstance(r.get("p_over_raw"), (int, float))]
        games = {r["game_id"] for r in valid if r.get("game_id")}
        mature = len(valid) >= LIVE_MIN_SETTLED and len(games) >= LIVE_MIN_UNIQUE_GAMES
        brier = None
        if valid:
            total = 0.0
            for r in valid:
                y = 1 if r["outcome"] == "OVER" else 0
                total += (float(r["p_over_raw"]) - y) ** 2
            brier = total / len(valid)
        strata.append({
            "platform": platform,
            "market": market,
            "line_band": list(band),
            "settled_nonpush_n": len(valid),
            "unique_games": len(games),
            "raw_brier": brier,
            "mature_for_calibration_research": mature,
        })
    return {
        "status": "LIVE_COHORT_MATURE_FOR_RESEARCH" if any(s["mature_for_calibration_research"] for s in strata)
                  else "LIVE_COHORT_IMMATURE",
        "quality": "FULL" if any(s["mature_for_calibration_research"] for s in strata) else "LIMITED",
        "predictions_frozen": len(predictions),
        "settlements": len(settlements),
        "unique_primary_forecasts": len(cohort_ids),
        "strata": strata,
        "maturity_threshold": {
            "settled_nonpush_per_stratum": LIVE_MIN_SETTLED,
            "unique_games_per_stratum": LIVE_MIN_UNIQUE_GAMES,
        },
        "ledger_sha256": _sha256(path),
    }


def stage24_receipt(prop: dict[str, Any], raw_probability: float | None,
                    ledger_snapshot: dict[str, Any],
                    baseline_path: str | Path = DEFAULT_BASELINE) -> dict[str, Any]:
    historical = _baseline_match(prop, baseline_path)
    band = _line_band(float(prop["line"]))
    platform = str(prop.get("platform") or "").lower()
    live_stratum = next((s for s in ledger_snapshot.get("strata", [])
                         if s.get("platform") == platform
                         and s.get("market") == prop.get("market")
                         and tuple(s.get("line_band", [])) == band), None)
    live = {
        "status": "NO_SETTLED_LIVE_ROWS_FOR_STRATUM" if live_stratum is None
                  else ("MATURE_FOR_CALIBRATION_RESEARCH" if live_stratum["mature_for_calibration_research"]
                        else "IMMATURE_LIVE_SAMPLE"),
        "quality": "FULL" if live_stratum and live_stratum["mature_for_calibration_research"] else "LIMITED",
        "stratum": live_stratum,
        "cohort_snapshot": {
            k: ledger_snapshot.get(k) for k in
            ("status", "predictions_frozen", "settlements", "unique_primary_forecasts", "ledger_sha256")
        },
        "maturity_threshold": ledger_snapshot.get("maturity_threshold"),
    }
    return {
        "stage": 24,
        "name": "Projection Error & Calibration",
        "execution": "EXECUTED",
        "quality": "LIMITED",
        "24A_historical_calibration": historical,
        "24B_live_benfrank_calibration": live,
        "raw_p_over": raw_probability,
        "p_over_calibrated": None,
        "calibration_applied": False,
        "accuracy_certified": False,
        "current_simulator_calibration_model_present": False,
        "decision_effect": "NONE",
        "exact_reason": (
            "Historical calibration evidence is retained as research context only. "
            "The current v5.2 lineup-enhanced simulator has no separately validated calibration model, "
            "and live forward calibration may not be promoted until the exact stratum matures."
        ),
        "independence_family": "CALIBRATION_EVALUATION_NOT_DIRECTIONAL_EVIDENCE",
    }
