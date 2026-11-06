"""One batch: source collection -> freeze -> models -> evidence report -> audit."""
import gzip
import hashlib
import html
import json
import math
import struct
from pathlib import Path

from . import VERSION
from .context import collect as collect_context
from .contracts import SPORTS, canonical, eligible_games, now, sha, timestamp, validate_prop
from .ledger import apply_calibration, record
from .model import blind, choose, dna, historical, probabilities, simulate
from .sources import Capture, collect_history


def write(path, data):
    # Exclusive creation catches accidental report overwrites even within a run.
    with Path(path).open("xb") as stream:
        stream.write(canonical(data) + b"\n")


def verify_run(root):
    root = Path(root)
    receipt = json.loads((root / "execution_receipt.json").read_text())
    for relative, digest in receipt["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or sha(path.read_bytes()) != digest:
            raise ValueError("RUN_FILE_HASH_MISMATCH:" + relative)
    checked, trials = 0, 0
    for item in receipt["results"]:
        if item["status"] == "BLOCKED":
            continue
        report = json.loads((root / item["report_file"]).read_text())
        prop = report["prop"]
        for scenario, summary in report["simulation"]["scenarios"].items():
            path = root / item["report_file"]
            trace = path.parent / "traces" / summary["trace_file"]
            if sha(trace.read_bytes()) != summary["trace_sha256"]:
                raise ValueError("SIMULATION_TRACE_HASH_MISMATCH")
            values, digest = [], hashlib.sha256()
            with gzip.open(trace, "rt") as f:
                for i, line in enumerate(f):
                    row = json.loads(line)
                    if row["trial"] != i:
                        raise ValueError("SIMULATION_TRIAL_SEQUENCE_FAILURE")
                    value = row["value"]
                    if not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError("INVALID_SIMULATION_DRAW")
                    digest.update(struct.pack("!d", value))
                    values.append(value)
            if len(values) != summary["trials"] or len(values) < 25000 or digest.hexdigest() != summary["draws_sha256"]:
                raise ValueError("SIMULATION_EXECUTION_PROVENANCE_FAILURE")
            actual = probabilities(values, prop["line"])
            if actual["counts"] != summary["counts"] or any(abs(actual[k] - summary[k]) > 1e-12 for k in ("p_over", "p_under", "p_push")):
                raise ValueError("SIMULATION_REPORTED_PROBABILITY_MISMATCH")
            trials += len(values)
        checked += 1
    return {"status": "EXECUTION_FILES_AND_TRACES_VERIFIED", "completed_props": checked, "verified_statistic_draws": trials, "accuracy_certified": False, "physical_play_by_play_simulation_asserted": False}


def make_report(root, reports, receipt):
    lines = ["# 🧬 BENFRANK OMNI-GOD — execution report", "", "**" + receipt["mode"] + " · probabilities require forward validation · no accuracy certification.**", "", "Every simulation below is an empirical statistic draw from observed games, with explicit workload scenarios. It is not a full play-by-play sports simulation.", "", "| Sport | Player | Market / line | Decision | Raw OVER | Raw UNDER | Push | Trials | Evidence gaps |", "|---|---|---|---|---:|---:|---:|---:|---|"]
    cards = []
    for result in reports:
        p = result["prop"]
        if result["status"] == "BLOCKED":
            lines.append(f"| {p.get('sport')} | {p.get('player')} | {p.get('market')} {p.get('line')} | BLOCKED | — | — | — | 0 | {result['blocker']} |")
            cards.append("<section><h2>" + html.escape(str(p.get("player"))) + "</h2><p>Blocked: " + html.escape(result["blocker"]) + "</p></section>")
            continue
        sim = result["simulation"]
        base = sim["scenarios"]["BASELINE"]
        lines.append(f"| {p['sport']} | {p['player']} | {p['market']} {p['line']:g} | **{result['decision']}** | {base['p_over']:.1%} | {base['p_under']:.1%} | {base['p_push']:.1%} | {sim['baseline_trials']:,} + {2*sim['baseline_trials']:,} stress | {len(result['evidence_gaps'])} |")
    for result in reports:
        if result["status"] == "BLOCKED":
            continue
        p, history, sim = result["prop"], result["history"], result["simulation"]
        lines += ["", f"## 📊 {p['sport']} · {p['player']} · {p['market']} {p['line']:g} → {result['decision']}", "", f"Expected result: **{sim['scenarios']['BASELINE']['mean']:.2f}** · central simulated range {sim['scenarios']['BASELINE']['p10']:.2f}–{sim['scenarios']['BASELINE']['p90']:.2f} (10th–90th percentiles).", "", "| Window | Observed | OVER | UNDER | PUSH | Mean |", "|---|---:|---:|---:|---:|---:|"]
        for label, w in history["windows"].items():
            mean = f"{w['expected_line']:.2f}" if w['expected_line'] is not None else "—"
            lines.append(f"| {label} | {w['n']} | {w['over']} | {w['under']} | {w['push']} | {mean} |")
        lines += ["", f"🔥 Exact-line streak: {history['streak']['side']} × {history['streak']['length']}. These counts are descriptive.", "", "🧠 Line-blind model: " + result["blind_model"]["status"] + (f" · {result['blind_model']['projection']:.2f}" if "projection" in result["blind_model"] else ""), "", "🔄 Opposite-side stress reversals: " + (", ".join(sim["scenario_reversals"]) or "None in the tested scenarios"), "", "| Hypothetical line | Raw OVER | Raw UNDER | Push |", "|---|---:|---:|---:|"]
        for rung in sim["sensitivity"]:
            lines.append(f"| {rung['line']:g} | {rung['p_over']:.1%} | {rung['p_under']:.1%} | {rung['p_push']:.1%} |")
        lines += ["", "Sensitivity lines are tests, not verified available platform lines.", "", "Calibration: " + result["calibration"]["status"] + ".", "", "**Evidence gaps and risk factors:**", ""]
        lines += ["- " + gap for gap in result["evidence_gaps"]]
        lines += ["", "Receipt: `" + p["prop_id"] + "` · source hashes and all trial traces are included."]
        bars = []
        for label, w in history["windows"].items():
            pc = 100 * w["over"] / w["n"] if w["n"] else 0
            bars.append(f'<div class="row"><span>{html.escape(label)} ({w["n"]})</span><div class="track"><div style="width:{pc:.2f}%"></div></div><b>{pc:.0f}% OVER</b></div>')
        cards.append(f'<section><small>{html.escape(p["sport"])} · {html.escape(p["market"])} {p["line"]:g}</small><h2>{html.escape(p["player"])} → {result["decision"]}</h2><p>Historical exact-line OVER coverage; descriptive, not calibrated probabilities</p>{"".join(bars)}<p>{html.escape(" · ".join(result["evidence_gaps"]))}</p></section>')
    lines += ["", "## 🏆 Per-sport research ranking", "", "Ranked by the lowest raw selected-side probability across the three tested scenarios. This is a model screening score, not a measured betting hit rate; correlated props are not an independently validated slip.", ""]
    for sport, ranked in receipt.get("rankings", {}).items():
        lines.append(f"**{sport} — top {min(6, len(ranked))} uploaded props:**")
        lines.append("")
        for item in ranked[:6]:
            lines.append(f"- {'⭐' if item['rank'] <= 2 else '📌'} #{item['rank']} {item['player']} · {item['market']} {item['line']:g} → {item['decision']} · stress floor {item['stress_floor']:.1%}; {item['gap_count']} evidence gaps.")
        lines.append("")
    (root / "report.md").write_text("\n".join(lines) + "\n")
    (root / "report.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BENFRANK OMNI execution</title><style>body{font:16px system-ui;background:#0c1324;color:#edf3ff;max-width:1050px;margin:auto;padding:28px}h1{color:#81dfcb}section{background:#17223a;border:1px solid #344462;border-radius:16px;padding:24px;margin:22px 0}p{line-height:1.6;color:#bcc9df}.row{display:grid;grid-template-columns:160px 1fr 100px;gap:12px;align-items:center;margin:13px 0}.track{background:#49618a;border-radius:10px;height:14px;overflow:hidden}.track div{height:100%;background:#6ed9c0}b{font-size:13px}@media(max-width:600px){body{padding:14px}.row{grid-template-columns:100px 1fr 74px;font-size:11px}}</style><h1>🧬 BENFRANK OMNI-GOD</h1><p>' + html.escape(receipt["mode"]) + ' · Empirical model execution. Accuracy is not certified. The Markdown report includes full evidence, stress tests and hypothetical alternative lines.</p>' + "".join(cards) + '</html>')


def run(input_path, output, state, trials=25000, seed=1729):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    raw = Path(input_path).read_bytes()
    (root / "request.json").write_bytes(raw)
    manifest = json.loads(raw)
    code_root = Path(__file__).parent
    code_revision = sha({p.name: sha(p.read_bytes()) for p in sorted(code_root.glob("*.py"))})
    mode = manifest.get("mode", "PREGAME")
    explicit_cutoff = manifest.get("cutoff_utc")
    intake_cutoff = explicit_cutoff or now()
    captures = {}
    props = manifest.get("props", [])
    if manifest.get("board_source"):
        cap = Capture(root / "sources" / "board")
        captures["board"] = cap
        data, proof = cap.get(manifest["board_source"]["url"])
        props = data["props"]
        write(root / "board_capture.json", {"props": props, "source": proof})
    if not isinstance(props, list) or not 1 <= len(props) <= 250:
        raise ValueError("BATCH_REQUIRES_ONE_TO_250_EXPLICIT_SPORT_PROPS")
    prepared, reports = [], []
    for index, raw_prop in enumerate(props):
        try:
            p = validate_prop(raw_prop, intake_cutoff, mode)
            capture = captures.setdefault(p["sport"], Capture(root / "sources" / p["sport"].lower()))
            configs = raw_prop.get("history_sources", manifest.get("history_sources", {}).get(p["sport"], []))
            games, fallbacks = collect_history(p, configs, capture)
            context = collect_context(p, capture, intake_cutoff, mode) if manifest.get("collect_opponent_context", True) else {"schedule_verified": False, "gaps": ["OPPONENT_CONTEXT_COLLECTION_DISABLED_FOR_EXPLICIT_RESEARCH"]}
            if mode == "PREGAME" and not context["schedule_verified"]:
                raise ValueError("PREGAME_SOURCE_SCHEDULE_NOT_VERIFIED")
            prepared.append((index, raw_prop, games, fallbacks, context))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            reports.append({"index": index, "status": "BLOCKED", "prop": raw_prop, "blocker": str(exc), "simulations_executed": 0, "accuracy_certified": False})
    # Every source is collected before the automatic cutoff is frozen.
    cutoff = explicit_cutoff or now()
    write(root / "freeze.json", {"cutoff_utc": cutoff, "mode": mode, "request_sha256": sha(raw), "sources_frozen_before_models": True})
    for capture in captures.values():
        capture.save()
    seen = set()
    for index, raw_prop, games, fallbacks, context in prepared:
        directory = root / "props" / f"{index:03d}"
        directory.mkdir(parents=True)
        try:
            prop = validate_prop({**raw_prop, "execution_code_sha256": code_revision}, cutoff, mode)
            if prop["prop_id"] in seen:
                raise ValueError("DUPLICATE_EXACT_PROP_REQUEST")
            seen.add(prop["prop_id"])
            observed, excluded = eligible_games(games, prop, cutoff, mode)
            write(directory / "observed_games.json", observed)
            history = historical(observed, prop)
            simulation = simulate(observed, prop, directory / "traces", trials, seed + index)
            try:
                independent = blind(observed)
            except (ValueError, OSError) as exc:
                independent = {"status": "WORKER_FAILED", "blocker": str(exc), "validated": False}
            calibration = apply_calibration(state, prop, simulation["scenarios"]["BASELINE"])
            decision = choose(calibration) if calibration["applied"] else simulation["side"]
            blind_side = "OVER" if independent.get("projection", prop["line"]) > prop["line"] else "UNDER"
            disagreement = "projection" in independent and blind_side != decision
            gaps = list(context["gaps"])
            gaps += ["INCOMPLETE_HISTORY_WINDOW:" + w for w in history["missing_windows"]]
            if independent.get("status") != "EXECUTED_PROCESS_SEPARATE_ML":
                gaps.append("LINE_BLIND_MODEL:" + independent["status"])
            if not simulation["workload"]["applied"]:
                gaps.append("OBSERVED_OPPORTUNITY_FIELD_UNAVAILABLE_USING_OUTCOME_BOOTSTRAP")
            if not calibration["applied"]:
                gaps.append("NO_VALIDATED_CALIBRATION_FOR_THIS_SPORT_MARKET_AND_RULESET")
            if disagreement:
                gaps.append("PRIMARY_AND_LINE_BLIND_MODEL_DISAGREE")
            if simulation["scenario_reversals"]:
                gaps.append("SIDE_REVERSES_UNDER_TESTED_STRESS")
            base = simulation["scenarios"]["BASELINE"]
            if abs(base["p_over"] - base["p_under"]) < .02:
                gaps.append("DIRECTIONAL_EDGE_NEAR_TIE")
            if base["p_over"] in (0, 1) or base["p_under"] in (0, 1):
                gaps.append("EXTREME_EMPIRICAL_PROBABILITY_IS_NOT_FUTURE_CERTAINTY")
            if mode != "PREGAME":
                gaps.append("RETROSPECTIVE_OR_SOFTWARE_TEST_NOT_A_FROZEN_LIVE_PICK")
            result = {"index": index, "status": "EXECUTED_WITH_EVIDENCE_GAPS" if gaps else "EXECUTED", "version": VERSION, "mode": mode, "prop": prop, "model_id": SPORTS[prop["sport"]]["model_id"], "ledger_id": SPORTS[prop["sport"]]["ledger_id"], "source_fallbacks": fallbacks, "excluded_games": excluded, "history": history, "player_dna": dna(observed, prop), "context": context, "simulation": simulation, "blind_model": independent, "model_disagreement": disagreement, "calibration": calibration, "decision": decision, "decision_probability_kind": "CALIBRATED_CONDITIONAL_NONPUSH_MODEL" if calibration["applied"] else "UNCALIBRATED_EMPIRICAL_MODEL", "evidence_gaps": gaps, "accuracy_certified": False}
            result["stage_results"] = {"exact_line_and_rules": "FROZEN", "source_history": len(observed), "historical_windows": "CALCULATED", "player_dna": "OBSERVED_ASSOCIATIONS", "opponent_evidence": "CAPTURED" if context.get("opponent") else "GAP", "workload": simulation["workload"]["method"] if simulation["workload"]["applied"] else "GAP", "sequential_stat_draws": simulation["total_trials_including_stress"], "blind_model": independent["status"], "reverse_stress": "EXECUTED", "line_sensitivity": "EXECUTED", "calibration": calibration["status"], "final_decision": decision}
            write(directory / "prediction.json", result)
            record(state, result)
            reports.append(result)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            reports.append({"index": index, "status": "BLOCKED", "prop": raw_prop, "blocker": str(exc), "accuracy_certified": False})
    reports.sort(key=lambda r: r["index"])
    write(root / "batch_results.json", reports)
    summary = {"version": VERSION, "mode": mode, "cutoff_utc": cutoff, "input_sha256": sha(raw), "requested_props": len(props), "completed_props": sum(r["status"] != "BLOCKED" for r in reports), "blocked_props": sum(r["status"] == "BLOCKED" for r in reports), "accuracy_certified": False, "results": [{"index": r["index"], "status": r["status"], "report_file": f"props/{r['index']:03d}/prediction.json" if r["status"] != "BLOCKED" else None, "blocker": r.get("blocker")} for r in reports]}
    rankings = {}
    for result in reports:
        if result["status"] == "BLOCKED":
            continue
        prop = result["prop"]
        metric = "p_over" if result["decision"] == "OVER" else "p_under"
        floor = min(s[metric] for s in result["simulation"]["scenarios"].values())
        rankings.setdefault(prop["sport"], []).append({"prop_id": prop["prop_id"], "player": prop["player"], "market": prop["market"], "line": prop["line"], "decision": result["decision"], "stress_floor": floor, "gap_count": len(result["evidence_gaps"])})
    for values in rankings.values():
        values.sort(key=lambda r: (-r["stress_floor"], r["gap_count"], r["prop_id"]))
        for i, value in enumerate(values):
            value["rank"] = i + 1
    summary["rankings"] = rankings
    make_report(root, reports, summary)
    summary["files"] = {str(p.relative_to(root)): sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}
    write(root / "execution_receipt.json", summary)
    audit = verify_run(root)
    write(root / "verification.json", audit)
    return {"output": str(root), **{k: summary[k] for k in ("requested_props", "completed_props", "blocked_props")}, "verification": audit}, (2 if summary["blocked_props"] else 0)
