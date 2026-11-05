"""Preflight a real BENFRANK v6.0 run without inventing source data.

Usage: python benfrank_v60_preflight.py --config config.json --output preflight.json
Exit 0 only when the four required inputs are present and structurally usable.
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REQUIRED=("board","contexts","history_db","ledger")

def _utc(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("NAIVE_TIMESTAMP")
    return d.astimezone(timezone.utc)

def preflight(config, *, cutoff_utc=None):
    cfg=json.loads(Path(config).read_text(encoding="utf-8"))
    base=Path(config).resolve().parent
    report={"status":"BLOCKED","checks":{},"missing":[],"input_sha256":{},"props":0}
    for key in REQUIRED:
        value=cfg.get(key)
        if not isinstance(value,str) or not value.strip():
            report["missing"].append("MISSING_CONFIG:"+key);continue
        path=Path(value)
        if not path.is_absolute():path=base/path
        if key=="ledger":
            if not path.parent.exists():
                report["missing"].append("LEDGER_PARENT_NOT_FOUND")
            else:report["checks"]["ledger_parent"]=True
            continue
        if not path.is_file():
            report["missing"].append("FILE_NOT_FOUND:"+key);continue
        if path.stat().st_size==0:
            report["missing"].append("EMPTY_FILE:"+key);continue
        report["input_sha256"][key]=hashlib.sha256(path.read_bytes()).hexdigest()
        if key=="history_db":
            try:
                db=sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True)
                try:
                    ok=db.execute("PRAGMA quick_check").fetchone()[0]=="ok"
                    tables=[x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                finally:db.close()
                if not ok or not tables:report["missing"].append("INVALID_HISTORY_DATABASE")
                else:report["checks"]["history_tables"]=tables
            except sqlite3.Error:report["missing"].append("UNREADABLE_HISTORY_DATABASE")
        else:
            try:
                data=json.loads(path.read_text(encoding="utf-8"))
                if key=="board":
                    if not isinstance(data,list) or not data:
                        report["missing"].append("EMPTY_OR_INVALID_BOARD");continue
                    report["props"]=len(data)
                    for i,p in enumerate(data):
                        if not isinstance(p,dict) or not all(p.get(k) is not None for k in
                            ("snapshot_id","player","market","line","team","opponent","game_date","tipoff_utc")):
                            report["missing"].append("INVALID_PROP:"+str(i));continue
                        if not isinstance(p["line"],(int,float)) or isinstance(p["line"],bool):
                            report["missing"].append("INVALID_LINE:"+str(i))
                        if cutoff_utc and _utc(p["tipoff_utc"])<=_utc(cutoff_utc):
                            report["missing"].append("NOT_PREGAME:"+str(i))
                    report["checks"]["board_count"]=len(data)
                elif key=="contexts":
                    if not isinstance(data,(dict,list)) or not data:
                        report["missing"].append("EMPTY_OR_INVALID_CONTEXTS")
                    else:report["checks"]["contexts_type"]=type(data).__name__
            except (ValueError,TypeError,KeyError):
                report["missing"].append("INVALID_JSON_OR_TIMESTAMP:"+key)
    report["status"]="INPUTS_PRESENT_NOT_SOURCE_CERTIFIED" if not report["missing"] else "BLOCKED"
    report["source_certified"]=False
    report["full_execution_verified"]=False
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--cutoff-utc")
    a=p.parse_args()
    result=preflight(a.config,cutoff_utc=a.cutoff_utc)
    dest=Path(a.output)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"missing":result["missing"],"props":result["props"]}))
    return 0 if not result["missing"] else 2

if __name__=="__main__":raise SystemExit(main())
