"""Reproducible BENFRANK v4.8 certification readiness from pinned v4.7 research.

No claims of current NBA verification or of independently attested sportsbook
lines are made by this research-status adapter. It does not modify model data.
"""
import argparse
import hashlib
import json
from pathlib import Path

from benfrank_v48_certification_gate import evaluate

V47_SUMMARY="diagnostics/v47-model-repair-validation-20261030.json"
V47_CALIBRATION="models/v47_prizepicks_points_25_30_calibration.json"
V47_PROTOCOL="configs/v47_validation_protocol.json"
V47_ENGINE="benfrank_v47_model.py"
V47_BLIND="benfrank_v44_blind_worker.py"

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(root,path):
    return json.loads((root/path).read_text())

def generate(root):
    root=Path(root)
    summary=read(root,V47_SUMMARY)
    calibration=read(root,V47_CALIBRATION)
    protocol=read(root,V47_PROTOCOL)
    if summary["total_formal_validation_trials"] != summary["development_trials"]+summary["new_test_trials"]:
        raise ValueError("V47_RESEARCH_TRIAL_COUNT_CONFLICT")
    new=summary["new_test_evaluation"]
    games=int(new["new_test_games"])
    if new["adjusted_brier_log_loss"]["n"]!=games or new["baseline_brier_log_loss"]["n"]!=games:
        raise ValueError("V47_HOLDOUT_SIZE_CONFLICT")
    fit=set(calibration["parameter_fit_games"])
    conformal=set(calibration["conformal_calibration_games"])
    if fit & conformal or len(fit)!=len(calibration["parameter_fit_games"]) or len(conformal)!=len(calibration["conformal_calibration_games"]):
        raise ValueError("V47_CALIBRATION_SPLIT_OVERLAP")
    if len(fit)!=42 or len(conformal)!=28:
        raise ValueError("V47_CALIBRATION_FROZEN_COUNTS_MISMATCH")
    if calibration.get("certification")!="NOT_CERTIFIED" or summary.get("certification")!="NOT_CERTIFIED":
        raise ValueError("UNEXPECTED_SOURCE_RESEARCH_CERTIFICATION")
    if protocol.get("automatic_full_promotion") is not False:
        raise ValueError("SOURCE_PROTOCOL_ALLOWS_UNVERIFIED_RELEASE")
    measured_ci=new["brier_delta_vs_baseline"]["percentile_95pct"]
    # Only 32 tests in an ESPN secondary labeled, retrospectively reconstructed
    # cohort. Do not rewrite this as an independently verified prospective test.
    candidate={
        "historical_coverage":{
            "source_receipt":"docs/V47_HISTORICAL_RECOVERY_VALIDATION.md",
            "covered_seasons":["2024-25","2025-26"],"verified_rows":52957,
            "verified":False,
            "block_reason":"Complete original archive verified offline, but protected production warehouse restoration not deployed in GitHub Actions"},
        "current_game_feed":{
            "source_receipt":"espn_live_stage.py",
            "as_of_utc":"2026-10-30T00:00:00Z","completed_game_ids":[],
            "verified":False,
            "block_reason":"Secondary game logs are staged, not independently reconciled as current official outcomes"},
        "injury_lineup_feed":{
            "source_receipt":"benfrank_v47_availability.py",
            "as_of_utc":"2026-10-30T00:00:00Z","team_ids":[],
            "verified":False,
            "block_reason":"Original dated injury reports exist, but final as-of starting five and projected-minute confirmation is not certified"},
        "genuine_pregame_lines":{
            "source_receipt":"benfrank_v46_public_lines.py","line_snapshots":13117,
            "as_of_utc":"2026-04-12T00:00:00Z",
            "all_snapshots_pre_tipoff":False,"verified":False,
            "block_reason":"Secondary public collector timestamps are not native sportsbook attestations"},
        "possession_simulator":{
            "execution_receipt":V47_SUMMARY,
            "real_game_trials":25000,
            "engine_sha256":digest(root/V47_ENGINE),
            "simulation_granularity":"possession_with_rotations",
            "evidence_kind":"retrospective",
            "verified":False,
            "block_reason":"2,575,000 simulation trials on reconstructed real NBA examples, but not certified on prospective official game data"},
        "independent_blind_model":{
            "execution_receipt":"benfrank_v47_experiment.py",
            "model_sha256":digest(root/V47_BLIND),
            "independent_feature_manifest_sha256":digest(root/V47_PROTOCOL),
            "trained_independently":True,
            "verified":False,
            "block_reason":"Process-isolated blind ML challenger only; no independent prospective release qualification"},
        "walk_forward_calibration":{
            "evaluation_receipt":V47_SUMMARY,
            "n_out_of_sample":games,
            "baseline_brier":new["baseline_brier_log_loss"]["brier"],
            "model_brier":new["adjusted_brier_log_loss"]["brier"],
            "bootstrap_ci_upper":measured_ci[1],
            "chronological_holdout":True,
            "verified":False,
            "block_reason":"Small reconstructed 32-game test; bootstrap Brier-delta interval includes zero"},
        "market_adapters":{
            "execution_receipt":"benfrank_v44_batch.py",
            "supported_market_ids":["points"],
            "scoring_contract_sha256":digest(root/V47_PROTOCOL),
            "verified":False,
            "block_reason":"No independent real-data validation across required markets, platforms, line bands and fantasy scoring contracts"},
        "governing_stage_audit":{
            "execution_receipt":"benfrank_v44_governance.py",
            "executed_stage_ids":[],
            "required_stage_ids":list(range(1,67)),
            "verified":False,
            "block_reason":"A 66-stage checklist is not 66 evidence-backed executed stage receipts"},
    }
    report=evaluate(candidate)
    report.update({
        "framework":"BENFRANK NBA v4.8 research-to-certification gate",
        "measured_v47":{
            "source_summary":V47_SUMMARY,
            "new_test_games":games,
            "development_trials":summary["development_trials"],
            "new_test_trials":summary["new_test_trials"],
            "total_trials":summary["total_formal_validation_trials"],
            "adjusted_brier":new["adjusted_brier_log_loss"]["brier"],
            "baseline_brier":new["baseline_brier_log_loss"]["brier"],
            "brier_delta_bootstrap_95pct":measured_ci,
            "all_new_test_labels_are_espn_secondary":new["source_tiers"]=={
                "ESPN_SECONDARY_WITH_OFFICIAL_SCHEDULE_IDENTITY":games},
            "unknown_material_availability_cases":new["unknown_material_availability_cases"],
            "calibration_parameter_games":len(fit),
            "calibration_conformal_games":len(conformal),
            "independent_test_certified":False},
        "source_hashes":{name:digest(root/name) for name in
             (V47_SUMMARY,V47_CALIBRATION,V47_PROTOCOL,V47_ENGINE,V47_BLIND)},
        "gate_evidence":candidate,
        "protected_archive_not_modified":True,
        "source_research_not_reclassified":True,
    })
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root",default=".")
    p.add_argument("--output",required=True)
    p.add_argument("--require-certifiable",action="store_true")
    args=p.parse_args()
    result=generate(args.repo_root)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:result[k] for k in ("status","ticket_authority","passed","required","measured_v47")},indent=2))
    if args.require_certifiable and result["status"]!="ELIGIBLE_FOR_INDEPENDENT_CERTIFICATION_REVIEW":
        raise SystemExit(2)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
