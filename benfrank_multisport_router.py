"""Strict sport routing: a selector must never execute a different sport engine."""
import json
from pathlib import Path

CATALOG=Path(__file__).resolve().parent/"architecture"/"benfrank_multisport_catalog.json"

def resolve_sport(sport, *, catalog_path=CATALOG):
    data=json.loads(Path(catalog_path).read_text())
    key=str(sport).strip().upper()
    matches=[item for item in data["sports"] if item["id"]==key]
    if len(matches)!=1: raise ValueError("UNKNOWN_SPORT_NO_FALLBACK")
    item=matches[0]
    if item["status"]!="OPERATIONAL":
        return {"sport":key,"status":"NOT_READY","reason":"INDEPENDENT_FRAMEWORK_NOT_VERIFIED",
                "repository":item["repository"],"may_predict":False}
    return {"sport":key,"status":"ROUTE_READY","repository":item["repository"],
            "model_id":item["model_id"],"ledger_id":item["ledger_id"],
            "may_predict":True}

def verify_prediction_route(requested_sport, receipt_sport, model_id, ledger_id, *, catalog_path=CATALOG):
    item=next((s for s in json.loads(Path(catalog_path).read_text())["sports"]
               if s["id"]==str(requested_sport).upper()),None)
    if item is None: raise ValueError("UNKNOWN_SPORT_NO_FALLBACK")
    if str(receipt_sport).upper()!=item["id"] or model_id!=item["model_id"] or ledger_id!=item["ledger_id"]:
        raise ValueError("CROSS_SPORT_DATA_OR_MODEL_MISMATCH")
    return True
