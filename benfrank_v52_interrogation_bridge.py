"""Bridge genuine v5.2 result receipts to the 60-question interrogation.

Only mark a question verified when a source-backed value and execution receipt
are present. This bridge does not fetch histories or execute simulations.
"""
import argparse
import json
from pathlib import Path
from benfrank_interrogation_60 import evaluate, write_report

WINDOWS = ("L5", "L10", "L15", "L20", "L25", "L32", "L52")

def bridge(result, receipt_path):
    prop = result["prop"]
    receipt = str(receipt_path)
    answers = {}
    def add(key, value, source, measurement):
        if value is None:
            return
        answers[key] = {"status": "verified", "answer": str(value),
                        "source": source, "measurement": str(measurement),
                        "execution_receipt": receipt}
    add("exact_line", prop.get("line"), "captured board snapshot",
        prop.get("snapshot_id"))
    add("cutoff", result.get("analysis_cutoff_utc"),
        "v5.2 run clock", result.get("analysis_cutoff_utc"))
    windows = result.get("historical_windows", {})
    if all(windows.get(w, {}).get("over_count") is not None for w in WINDOWS):
        add("windows", {w: windows[w] for w in WINDOWS},
            "v5.2 warehouse game logs", "L5/L10/L15/L20/L25/L32/L52")
        add("push_counts", {w: windows[w].get("push_count") for w in WINDOWS},
            "v5.2 warehouse game logs", "push counts by window")
    main = result.get("main_simulation", {})
    if (main.get("complete_sequential_games") is True and
            main.get("trials_executed", 0) >= 25000 and
            main.get("trial_chain_sha256") and main.get("checkpoints")):
        add("simulation", {"over": main.get("over_count"),
                           "under": main.get("under_count"),
                           "push": main.get("push_count")},
            "v5.2 simulator", main["trial_chain_sha256"])
    blind = result.get("blind_model", {})
    if blind.get("projection") is not None:
        add("predictive_intelligence", blind["projection"],
            "v5.2 line-blind baseline (not independently validated AI)",
            blind.get("model", "baseline"))
    if result.get("scenario_side_flip") is not None:
        add("confidence_assessment", result.get("scenario_risk"),
            "v5.2 scenario stress", result["scenario_side_flip"])
    # Do not verify blind_ai, adversarial, calibration, or final_decision:
    # v5.2 explicitly describes its forecasts as unvalidated research.
    report = evaluate(answers, sport="NBA", player=prop["player"],
                      market=prop["market"], line=float(prop["line"]),
                      cutoff_utc=result.get("analysis_cutoff_utc", ""),
                      preferred_side=result.get("direction"))
    report["upstream_status"] = result.get("status")
    report["upstream_certification"] = result.get("certification")
    return report

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    for path in sorted(Path(args.results).glob("*.json")):
        if path.name == "comparison.json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "prop" not in raw:
                continue
            report = bridge(raw, path)
            write_report(str(out / path.name), report)
            summary.append({"player": report["player"],
                            "verified": report["verified_count"],
                            "certified": report["certified"]})
        except Exception as exc:
            summary.append({"file": str(path), "error": str(exc)})
    (out / "bridge_summary.json").write_text(json.dumps(summary, indent=2),
                                              encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary and all("error" not in r for r in summary) else 2

if __name__ == "__main__":
    raise SystemExit(main())
