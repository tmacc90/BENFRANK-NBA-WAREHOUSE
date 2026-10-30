"""Non-destructive diagnostics for incomplete NBA historical acquisition.

Reads retained import receipts and failure records. Never mutates historical
data, never promotes a secondary row to verified, and never claims FULL.
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

def classify(error):
    code=str(error.get("code","UNKNOWN"))
    if code=="VERIFICATION_REJECTED":
        detail=str(error.get("detail",""))
        if "ESPN_IDENTITY_MATCH_COUNT_0" in detail:
            return "ESPN_IDENTITY_MISSING"
        if "ESPN_IDENTITY_MATCH_COUNT_" in detail:
            return "ESPN_IDENTITY_AMBIGUOUS"
        if "starting five incomplete" in detail:
            return "STARTER_INCONSISTENCY"
        if "schedule" in detail.lower():
            return "SCHEDULE_INCONSISTENCY"
        return "OTHER_VERIFICATION_REJECTED"
    if code=="CROSS_SOURCE_CONFLICT":
        return "CROSS_SOURCE_CONFLICT"
    return code

def audit(folder):
    folder=Path(folder)
    receipt_path=folder/"import_receipt.json"
    if not receipt_path.is_file():
        return {"status":"MISSING_IMPORT_RECEIPT","reason":str(receipt_path),
                "prediction_certification":"NOT_CERTIFIED"}
    receipt=json.loads(receipt_path.read_text())
    seasons=[]
    for item in receipt.get("seasons",[]):
        season=item.get("season")
        year=int(season[:4])+1 if season else None
        failure_file=folder/f"failures_{year}.json"
        if not failure_file.exists():
            seasons.append({"season":season,"status":"FAIL_MISSING_FAILURE_DETAIL",
                            "declared_failures":item.get("failure_count")})
            continue
        errors=json.loads(failure_file.read_text())
        groups=collections.Counter(classify(e) for e in errors)
        official=collections.Counter(classify(e) for e in errors
                                     if e.get("source")=="nba_stats_mirror")
        seasons.append({"season":season,"declared_failures":item.get("failure_count"),
                        "actual_failures":len(errors),"categories":dict(groups),
                        "official_rejections":dict(official),
                        "verified_player_games":item.get("crosschecked_player_games"),
                        "declared_failure_count_matches":item.get("failure_count")==len(errors),
                        "sample_failure_ids":[
                            {"code":e.get("code"),"nba_game_id":e.get("nba_game_id"),
                             "nba_player_id":e.get("nba_player_id"),
                             "detail":str(e.get("detail",""))[:150]}
                            for e in errors[:12]]})
    db=folder/"nba_warehouse.sqlite"
    db_report={"available":db.exists()}
    if db.exists():
        c=sqlite3.connect(f"file:{db.resolve()}?mode=ro",uri=True)
        try:
            db_report["integrity"]=c.execute("PRAGMA integrity_check").fetchone()[0]
            db_report["game_rows"]=c.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            db_report["season_counts"]=[dict(zip(("season","count"),row)) for row in
                                        c.execute("SELECT season,COUNT(*) FROM games GROUP BY season")]
        finally:
            c.close()
    consistent=bool(seasons) and all(
        s.get("declared_failure_count_matches") for s in seasons)
    expected_rows=sum(int(s.get("verified_player_games") or 0) for s in seasons)
    complete=(consistent and receipt.get("status")=="PASS"
              and db_report.get("integrity")=="ok"
              and db_report.get("game_rows")==expected_rows and expected_rows>0
              and all(s.get("actual_failures")==0 for s in seasons)
              and all(not item.get("official_games_without_any_crosschecked_player")
                      for item in receipt.get("seasons",[])))
    return {"status":"PASS_RECONCILED" if complete else
            "INCOMPLETE_RECONCILIATION" if consistent else "INVALID_OR_MISSING_FAILURE_EVIDENCE",
            "import_status":receipt.get("status"),"seasons":seasons,
            "database":db_report,"historical_certification":complete,
            "prediction_certification":"NOT_CERTIFIED",
            "recommended_next_action":"Resolve categorized discrepancies using original pinned official source evidence; do not silently drop conflicting rows."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    result=audit(a.input)
    out=Path(a.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"seasons":result.get("seasons"),
                      "database":result.get("database")},indent=2))
    return 0 if result["status"]=="PASS_RECONCILED" else 2

if __name__=="__main__":
    raise SystemExit(main())
