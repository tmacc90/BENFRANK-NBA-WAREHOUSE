"""Collect 2026-27 completed NBA box scores before a fixed prediction date.

Sources are ESPN secondary; original past-season official warehouse stays
untouched. A game's own or any later box score NEVER enters its forecast.
All source failures and non-reconciled values remain visible in the receipt.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from espn_live_stage import fetch_staged

COLUMNS=("player","date","season","team","opponent","home","starter","minutes",
         "pts","reb","ast","stl","blk","tov","fg3m","fgm","fga","fg3a","ftm","fta",
         "source_game_id","source_body_sha","retrieved_at")
STAT_COLS=("minutes","pts","reb","ast","stl","blk","tov","fg3m","fgm","fga","fg3a","ftm","fta")

def connect(path):
    c=sqlite3.connect(path)
    c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS current_games(
      player TEXT NOT NULL,date TEXT NOT NULL,season TEXT NOT NULL,
      team TEXT NOT NULL,opponent TEXT NOT NULL,home INTEGER NOT NULL,
      starter INTEGER,minutes REAL NOT NULL,pts REAL NOT NULL,reb REAL NOT NULL,
      ast REAL NOT NULL,stl REAL NOT NULL,blk REAL NOT NULL,tov REAL NOT NULL,
      fg3m REAL NOT NULL,fgm REAL NOT NULL,fga REAL NOT NULL,
      fg3a REAL NOT NULL,ftm REAL NOT NULL,fta REAL NOT NULL,
      source_game_id TEXT NOT NULL,source_body_sha TEXT NOT NULL,
      retrieved_at TEXT NOT NULL,
      PRIMARY KEY(player,date,team))""")
    c.commit()
    return c

def validate_row(r,target):
    if not r["date"]<target:
        raise ValueError("TARGET_DAY_OR_LATER_SCOREBOARD_LOOKAHEAD")
    if r.get("season")!="2026-27":
        raise ValueError("NOT_2026_27_SEASON")
    if any(r.get(k) is None for k in COLUMNS if k!="starter"):
        raise ValueError("UNOBSERVED_REQUIRED_SOURCE_FIELD")
    if not r.get("source_body_sha") or len(r["source_body_sha"])!=64:
        raise ValueError("UNHASHED_SOURCE_GAME")
    for k in STAT_COLS:
        v=r[k]
        if not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
            raise ValueError("NONFINITE_OR_NEGATIVE_STAT:"+k)
    if not 0<r["minutes"]<=70:raise ValueError("NO_PLAYED_MINUTES")
    if r["fgm"]>r["fga"] or r["fg3m"]>r["fg3a"] or r["fg3a"]>r["fga"]:
        raise ValueError("INVALID_SHOOTING_ATTEMPTS")
    if r["fg3m"]>r["fgm"] or r["ftm"]>r["fta"]:
        raise ValueError("INVALID_SHOOTING_MAKES")
    if abs(2*r["fgm"]+r["fg3m"]+r["ftm"]-r["pts"])>0.0001:
        raise ValueError("SHOOTING_COMPONENTS_DONT_MATCH_POINTS")
    if r["team"]==r["opponent"] or r["home"] not in (0,1):
        raise ValueError("INVALID_MATCHUP")

def collect(target,days=14,fetcher=fetch_staged):
    cutoff=dt.date.fromisoformat(target)
    if not dt.date(2026,10,20)<=cutoff<=dt.date(2027,6,30):
        raise ValueError("RESEARCH_TARGET_DATE_OUTSIDE_2026_27_SEASON")
    if not 1<=days<=35:
        raise ValueError("LOOKBACK_DAYS_OUTSIDE_ALLOWED_RANGE")
    accepted={}
    failures=[]
    dates=[]
    for delta in range(days,0,-1):
        day=(cutoff-dt.timedelta(days=delta)).isoformat()
        receipt=fetcher(day,max_events=20)
        rows=receipt.pop("staged_rows",[])
        statuses=[(str(e.get("event_id")),e.get("status")) for e in receipt.get("events",[])]
        dates.append({"date":day,"scoreboard_status":receipt.get("status"),
                      "event_statuses":statuses,"player_rows":len(rows),
                      "scoreboard_sha256":(receipt.get("scoreboard_receipt") or {}).get("sha256")})
        if receipt.get("status") not in ("NO_COMPLETED_REGULAR_GAMES","PARSED_UNVERIFIED"):
            failures.append({"date":day,"reason":"SOURCE_FETCH_OR_PARTIAL_COMPLETION",
                             "detail":receipt.get("error"),"status":receipt.get("status")})
        for row in rows:
            try:
                validate_row(row,target)
                key=(row["player"],row["date"],row["team"])
                if key in accepted:
                    if any(accepted[key][k]!=row[k] for k in COLUMNS):
                        raise ValueError("CONTRADICTORY_DUPLICATE_BOX_SCORE")
                    continue
                accepted[key]={k:row.get(k) for k in COLUMNS}
            except (KeyError,TypeError,ValueError) as exc:
                if len(failures)<250:
                    failures.append({"date":day,"player":row.get("player"),
                                     "reason":str(exc)[:160]})
    return list(accepted.values()),{
       "status":"ESPN_SECONDARY_OBSERVED_PARTIAL" if failures else "ESPN_SECONDARY_OBSERVED_COMPLETE_DAYS",
       "target_game_date":target,"strict_history_through":(cutoff-dt.timedelta(days=1)).isoformat(),
       "scope":"2026_27_REGULAR_SEASON_COMPLETED_GAMES_BEFORE_TARGET_ONLY",
       "source":"ESPN_SECONDARY_NOT_INDEPENDENT_OFFICIAL_CERTIFICATION",
       "snapshot_date_range":dates,"player_game_rows":len(accepted),
       "retrieval_issues":failures,"official_verified":False,
       "lineups_confirmed":False,"current_injuries_applied":False,
       "ticket_authority":"NO_TICKET",
       "prediction_certification":"NOT_CERTIFIED"
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-date",default=dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat())
    p.add_argument("--days",type=int,default=14)
    p.add_argument("--out-dir",required=True)
    args=p.parse_args()
    root=Path(args.out_dir);root.mkdir(parents=True,exist_ok=True)
    rows,receipt=collect(args.target_date,args.days)
    db=connect(root/"current_2026_27.sqlite")
    try:
        for r in rows:
            db.execute("INSERT INTO current_games VALUES ("+",".join("?" for _ in COLUMNS)+")",
                       [r[k] for k in COLUMNS])
        db.commit()
        receipt["sqlite_integrity"]=db.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        db.close()
    receipt["rows_sha256"]=hashlib.sha256(json.dumps(
        rows,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()
    (root/"current_source_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps({"status":receipt["status"],"rows":len(rows),
                      "issues":len(receipt["retrieval_issues"]),
                      "target":args.target_date},indent=2),flush=True)
    if not rows or receipt["sqlite_integrity"]!="ok":
        raise SystemExit(2)
if __name__=="__main__":
    main()
