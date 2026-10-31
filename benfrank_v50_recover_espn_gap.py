"""Recover ESPN scoreboard outage dates from individually finalized game summaries.

Only scans gaps BOUNDED by verified event IDs on adjacent observed dates.
Never invents player stats or dates: each individual summary must self-attest
completed status, ET local game date, event identity and participating teams.
Source remains ESPN SECONDARY, not official NBA certified. Input SQLite untouched.
"""
import argparse, datetime as dt, hashlib, json, shutil, sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from benfrank_v50_current_asof import connect,COLUMNS,validate_row
from espn_live_stage import fetch_json, rows_from_summary, SUMMARY

def checked_summary(event_id, target_date, requested_dates, fetch=fetch_json):
    body,meta=fetch(SUMMARY+str(event_id))
    comp=(body.get("header") or {}).get("competitions") or []
    if len(comp)!=1:raise ValueError("MISSING_UNIQUE_SUMMARY_COMPETITION")
    game=comp[0]
    eid=str(game.get("id") or (body.get("header") or {}).get("id") or "")
    if eid and eid!=str(event_id):raise ValueError("SUMMARY_EVENT_ID_CONFLICT")
    final=((game.get("status") or {}).get("type") or {}).get("completed")
    if final is not True:raise ValueError("NOT_COMPLETED_FINAL")
    stamp=game.get("date")
    if not stamp:raise ValueError("GAME_DATE_SOURCE_MISSING")
    tipoff=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
    if tipoff.tzinfo is None:raise ValueError("GAME_DATE_TZ_MISSING")
    local=tipoff.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    if local not in requested_dates or local>=target_date:raise ValueError("DATE_NOT_EXPLICITLY_ALLOWED_OR_TARGET_LEAK")
    competitors=game.get("competitors") or []
    if len(competitors)!=2:raise ValueError("NO_UNIQUE_SOURCE_OPPONENTS")
    teams={x.get("homeAway"):(x.get("team") or {}).get("abbreviation") for x in competitors}
    home,away=teams.get("home"),teams.get("away")
    if not home or not away or home==away:raise ValueError("NO_VERIFIED_BOTH_TEAMS")
    rows=rows_from_summary(str(event_id),local,home,away,body)
    accepted=[]
    for r in rows:
        r["source_body_sha"]=meta["sha256"]
        r["retrieved_at"]=meta["retrieved_at"]
        validate_row(r,target_date)
        accepted.append(r)
    if len(accepted)<12:raise ValueError("GAME_BOX_SCORE_PLAYER_COVERAGE_TOO_LOW")
    return accepted,{"game_id":str(event_id),"date":local,"home":home,"away":away,
                     "players":len(accepted),"sha256":meta["sha256"],
                     "source":"ESPN_COMPLETED_SUMMARY_DATE_VERIFIED"}

def recover(existing_db, out_db, out_receipt, start_id, end_id, target_date, allowed_dates):
    if not start_id<end_id or end_id-start_id>40:
        raise ValueError("UNSAFE_OR_OVERSIZED_ID_SCAN")
    if not allowed_dates or any(d>=target_date for d in allowed_dates):
        raise ValueError("INVALID_SOURCE_DATE_SCOPE")
    existing=Path(existing_db)
    if not existing.is_file():raise FileNotFoundError(existing)
    out=Path(out_db);out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():raise FileExistsError("RECEIPTS_ARE_IMMUTABLE_NO_OVERWRITE")
    shutil.copyfile(existing,out)
    conn=connect(out)
    errors=[];events=[];recovered=[]
    try:
        prior=conn.execute("SELECT COUNT(*) FROM current_games").fetchone()[0]
        for eid in range(start_id,end_id+1):
            try:
                rows,meta=checked_summary(eid,target_date,allowed_dates)
                for r in rows:
                    key=(r["player"],r["date"],r["team"])
                    prior_row=conn.execute("SELECT * FROM current_games WHERE player=? AND date=? AND team=?",key).fetchone()
                    if prior_row:
                        if any(prior_row[c]!=r.get(c) for c in COLUMNS
                               if c not in ("retrieved_at",)):
                            raise ValueError("CONFLICT_WITH_STAGED_ESPN_SOURCE")
                        continue
                    conn.execute("INSERT INTO current_games VALUES ("+",".join("?" for _ in COLUMNS)+")",
                                 [r.get(k) for k in COLUMNS])
                    recovered.append(key)
                events.append(meta)
            except (KeyError,TypeError,ValueError,IndexError,OSError,TimeoutError,json.JSONDecodeError) as exc:
                errors.append({"event_id":eid,"reason":type(exc).__name__+": "+str(exc)[:160]})
        conn.commit()
        integrity=conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok" or conn.execute("SELECT COUNT(*) FROM current_games WHERE date>=?",(target_date,)).fetchone()[0]:
            raise ValueError("SQLITE_INTEGRITY_OR_LEAKAGE_FAILURE")
        count=conn.execute("SELECT COUNT(*) FROM current_games").fetchone()[0]
    finally:
        conn.close()
    report={"status":"RECOVERED_FINAL_SOURCE_SUMMARIES" if not errors else "PARTIAL_ESPN_GAP_RECOVERY",
            "target_date":target_date,"allowed_missing_dates":allowed_dates,"scanned_ids":[start_id,end_id],
            "before_rows":prior,"new_rows":len(recovered),"after_rows":count,
            "recovered_games":events,"errors":errors,"official_verified":False,
            "source_tier":"ESPN_SECONDARY_FINAL_SUMMARIES_WITH_DATE_AND_TEAM_CHECKS",
            "source_input_sha256":hashlib.sha256(existing.read_bytes()).hexdigest(),
            "output_db_sha256":hashlib.sha256(out.read_bytes()).hexdigest(),
            "ticket_authority":"NO_TICKET","prediction_certification":"NOT_CERTIFIED"}
    p=Path(out_receipt);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","before_rows","new_rows","after_rows","errors")},indent=2))
    return report
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-db",required=True)
    p.add_argument("--output-db",required=True)
    p.add_argument("--output-receipt",required=True)
    p.add_argument("--first-id",type=int,default=401909868)
    p.add_argument("--last-id",type=int,default=401909880)
    p.add_argument("--target-date",default="2026-10-30")
    p.add_argument("--dates",nargs="+",default=["2026-10-26","2026-10-27"])
    args=p.parse_args()
    r=recover(args.input_db,args.output_db,args.output_receipt,args.first_id,args.last_id,args.target_date,args.dates)
    return 0 if r["new_rows"]>0 else 2
if __name__=="__main__":
    raise SystemExit(main())
