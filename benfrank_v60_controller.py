"""BENFRANK v6 additive execution auditor: no fabricated stage completions."""
import hashlib
import json
from datetime import datetime

STAGES = ("validate_prop","acquire_history","reconcile_sources","rolling_windows","career_dna","exact_line","player_dna","workload","rotations","teammates","opponent_dna","matchup","game_script","opportunities","market_forecasts","line_sensitivity","sequential_25000","blind_independent","adversarial","stress_tests","model_reconciliation","calibration","probabilities","payout","prediction","pregame_receipt")
POSTGAME = ("postgame_settlement","postgame_learning")

def execute(prop_id, cutoff_utc, executors, mode="pregame"):
    if mode not in ("pregame","postgame"):
        raise ValueError("mode must be pregame or postgame")
    cutoff = datetime.fromisoformat(cutoff_utc.replace("Z","+00:00"))
    if cutoff.tzinfo is None:
        raise ValueError("cutoff requires timezone")
    stages = STAGES if mode == "pregame" else POSTGAME
    context = {"prop_id":prop_id,"cutoff_utc":cutoff_utc}
    receipts = []
    for stage in stages:
        fn = executors.get(stage)
        if fn is None:
            receipts.append({"stage":stage,"status":"BLOCKED","reason":"executor_not_connected"})
            continue
        try:
            result = fn(dict(context))
            if not isinstance(result,dict) or result.get("verified") is not True or not result.get("evidence"):
                raise ValueError("missing_verified_evidence")
            asof = result.get("source_asof_utc")
            if asof and mode == "pregame":
                dt = datetime.fromisoformat(asof.replace("Z","+00:00"))
                if dt.tzinfo is None or dt > cutoff:
                    raise ValueError("post_cutoff_source")
            evidence = result["evidence"]
            digest = hashlib.sha256(json.dumps(evidence,sort_keys=True,default=str).encode()).hexdigest()
            context[stage] = evidence
            receipts.append({"stage":stage,"status":"VERIFIED","sha256":digest})
        except Exception as exc:
            receipts.append({"stage":stage,"status":"BLOCKED","reason":str(exc)[:120]})
    complete = all(r["status"] == "VERIFIED" for r in receipts)
    candidate = context.get("prediction",{})
    side = candidate.get("side") if isinstance(candidate,dict) else None
    return {"prop_id":prop_id,"cutoff_utc":cutoff_utc,"mode":mode,
            "status":"FULLY_EXECUTED" if complete else "INCOMPLETE",
            "certified":False,
            "side":side if complete and side in ("OVER","UNDER") else None,
            "receipts":receipts}
