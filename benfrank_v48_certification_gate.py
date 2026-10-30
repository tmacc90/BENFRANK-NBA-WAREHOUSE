"""Fail-closed production certification evidence gate for BENFRANK NBA.

This gate never treats unit tests, demo simulations, historical-only evidence,
or model-authored claims as proof of real-game predictive certification.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

REQUIRED = {
    "historical_coverage": ("source_receipt", "covered_seasons", "verified_rows"),
    "current_game_feed": ("source_receipt", "as_of_utc", "completed_game_ids"),
    "injury_lineup_feed": ("source_receipt", "as_of_utc", "team_ids"),
    "genuine_pregame_lines": ("source_receipt", "line_snapshots", "as_of_utc"),
    "possession_simulator": ("execution_receipt", "real_game_trials", "engine_sha256"),
    "independent_blind_model": ("execution_receipt", "model_sha256", "independent_feature_manifest_sha256"),
    "walk_forward_calibration": ("evaluation_receipt", "n_out_of_sample", "baseline_brier", "model_brier", "bootstrap_ci_upper"),
    "market_adapters": ("execution_receipt", "supported_market_ids", "scoring_contract_sha256"),
    "governing_stage_audit": ("execution_receipt", "executed_stage_ids", "required_stage_ids"),
}
SHA_FIELDS = {"engine_sha256", "model_sha256", "independent_feature_manifest_sha256", "scoring_contract_sha256"}
def valid_sha(s):
    return isinstance(s,str) and len(s)==64 and all(x in "0123456789abcdef" for x in s.lower())
def valid_time(value):
    try:
        t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        return t.tzinfo is not None and t.utcoffset() is not None
    except (AttributeError,ValueError,TypeError):
        return False
def check_receipt(name, item):
    problems=[]
    if not isinstance(item,dict):
        return ["MISSING_EVIDENCE_RECEIPT"]
    for field in REQUIRED[name]:
        if field not in item or item[field] in ("",None,[],{}):
            problems.append("MISSING_"+field.upper())
    for field in SHA_FIELDS & item.keys():
        if not valid_sha(item[field]):problems.append("INVALID_"+field.upper())
    if "as_of_utc" in item and not valid_time(item["as_of_utc"]):
        problems.append("INVALID_AS_OF_UTC")
    if item.get("evidence_kind") in ("synthetic","demo","unit_test","illustrative"):
        problems.append("NON_PRODUCTION_EVIDENCE")
    if item.get("verified") is not True:
        problems.append("NOT_INDEPENDENTLY_VERIFIED")
    if name=="historical_coverage":
        count=item.get("verified_rows")
        seasons=item.get("covered_seasons")
        if (not isinstance(count,int) or isinstance(count,bool) or count<52957
                or not isinstance(seasons,list)
                or not {"2024-25","2025-26"}.issubset(set(x for x in seasons if isinstance(x,str)))):
            problems.append("INCOMPLETE_SELECTED_SEASON_HISTORY")
    if name=="possession_simulator":
        count=item.get("real_game_trials")
        if not isinstance(count,int) or isinstance(count,bool) or count<25000:
            problems.append("FEWER_THAN_25000_REAL_GAME_TRIALS")
        if item.get("simulation_granularity")!="possession_with_rotations":
            problems.append("NOT_POSSESSION_ROTATION_SIMULATOR")
    if name=="independent_blind_model" and item.get("trained_independently") is not True:
        problems.append("NOT_INDEPENDENTLY_TRAINED")
    if name=="walk_forward_calibration":
        if item.get("chronological_holdout") is not True:problems.append("NOT_CHRONOLOGICAL_HOLDOUT")
        count=item.get("n_out_of_sample")
        if not isinstance(count,int) or isinstance(count,bool) or count<500:
            problems.append("INSUFFICIENT_OUT_OF_SAMPLE")
        try:
            if not (0<=item["model_brier"]<item["baseline_brier"]<=1):
                problems.append("NO_BASELINE_BRIER_IMPROVEMENT")
            if not item["bootstrap_ci_upper"]<0:
                problems.append("NO_SIGNIFICANT_CONFIDENCE_INTERVAL")
        except (KeyError,TypeError,ValueError):
            problems.append("INVALID_CALIBRATION_METRICS")
    if name=="governing_stage_audit":
        executed=item.get("executed_stage_ids")
        required=item.get("required_stage_ids")
        if (not isinstance(executed,list) or not isinstance(required,list)
                or not required or not all(isinstance(x,int) and not isinstance(x,bool) for x in required)
                or not all(isinstance(x,int) and not isinstance(x,bool) for x in executed if isinstance(executed,list))
                or (isinstance(executed,list) and isinstance(required,list) and set(executed)!=set(required))):
            problems.append("GOVERNING_STAGES_NOT_ALL_EXECUTED")
    if name=="genuine_pregame_lines":
        if not item.get("all_snapshots_pre_tipoff") is True:
            problems.append("PREGAME_LINE_TIMESTAMPS_NOT_VERIFIED")
    return sorted(set(problems))
def evaluate(evidence):
    gates={}
    for name in REQUIRED:
        problems=check_receipt(name,evidence.get(name))
        gates[name]={"status":"PASS" if not problems else "BLOCKED","reasons":problems}
    complete=all(x["status"]=="PASS" for x in gates.values())
    return {"status":"ELIGIBLE_FOR_INDEPENDENT_CERTIFICATION_REVIEW" if complete else "NOT_CERTIFIED",
            "ticket_authority":"NO_TICKET",
            "note":"Even all green evidence gates require external sign-off and cannot automatically issue betting tickets.",
            "gates":gates,"passed":sum(x["status"]=="PASS" for x in gates.values()),
            "required":len(gates)}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--evidence",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    raw=json.loads(Path(args.evidence).read_text())
    result=evaluate(raw)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return 0 if result["status"]=="ELIGIBLE_FOR_INDEPENDENT_CERTIFICATION_REVIEW" else 2
if __name__=="__main__":
    raise SystemExit(main())
