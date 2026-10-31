"""ESPN.com direct completed-game box score + play-by-play evidence.

Only completed regular-season games dated STRICTLY before as-of game day are
eligible. ESPN is secondary evidence, not official NBA.com verification.
Missing play-by-play or invalid shooting fields remain explicit NULL/gaps.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from espn_live_stage import rows_from_summary
from benfrank_v50_current_asof import connect,COLUMNS,validate_row

ET=ZoneInfo("America/New_York")
BASE="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
MAX_BYTES=8_000_000
PLAY_SCHEMA="""CREATE TABLE IF NOT EXISTS espn_completed_plays(
 source_game_id TEXT NOT NULL,
 game_date TEXT NOT NULL,
 play_index INTEGER NOT NULL,
 play_id TEXT,
 period_number INTEGER,
 clock_display TEXT,
 source_sha256 TEXT NOT NULL,
 play_json TEXT NOT NULL,
 PRIMARY KEY(source_game_id,play_index))"""
def fetch_json(url,fetch=None):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!="https" or parsed.hostname!="site.api.espn.com" or not url.startswith(BASE):
        raise ValueError("UNAPPROVED_ESPN_SOURCE")
    if fetch is None:
        req=urllib.request.Request(url,headers={
            "Accept":"application/json",
            "User-Agent":"BENFRANK-NBA-ESPN-GameEvidence/5.1"})
        with urllib.request.urlopen(req,timeout=17) as resp:
            if resp.status!=200 or not resp.geturl().startswith(BASE):
                raise ValueError("ESPN_SOURCE_HTTP_OR_REDIRECT")
            raw=resp.read(MAX_BYTES+1)
    else: raw=fetch(url)
    if not isinstance(raw,bytes) or not raw or len(raw)>MAX_BYTES:
        raise ValueError("ESPN_SOURCE_EMPTY_OR_OVERSIZED")
    value=json.loads(raw)
    if not isinstance(value,dict):
        raise ValueError("ESPN_SOURCE_NOT_JSON_OBJECT")
    return value,raw

def et_date(value):
    if not isinstance(value,str):
        raise ValueError("ESPN_EVENT_TIME_MISSING")
    t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("ESPN_EVENT_TIME_NOT_AWARE")
    return t.astimezone(ET).date().isoformat()

def completed_scoreboard_events(board,day):
    result=[]
    events=board.get("events")
    if not isinstance(events,list):
        raise ValueError("ESPN_SCOREBOARD_EVENTS_NOT_PRESENT")
    for event in events:
        status=((event.get("status") or {}).get("type") or {}).get("completed")
        if status is not True:continue
        season_type=(event.get("season") or {}).get("type")
        if season_type is not None and str(season_type)!="2":continue
        event_id=str(event.get("id",""))
        if not re.fullmatch(r"\d{6,15}",event_id):
            continue
        if et_date(event.get("date"))!=day:
            continue
        comps=event.get("competitions") or []
        if len(comps)!=1:continue
        comp=comps[0]
        competitors=comp.get("competitors") or []
        teams={x.get("homeAway"):(x.get("team") or {}).get("abbreviation")
               for x in competitors}
        if not teams.get("home") or not teams.get("away") or teams["home"]==teams["away"]:
            continue
        result.append({"event_id":event_id,"date":day,
                       "home":teams["home"],"away":teams["away"]})
    return result

def verify_completed_summary(summary,event):
    header=summary.get("header") or {}
    comps=header.get("competitions") or []
    if len(comps)!=1:
        raise ValueError("NO_ESPN_SUMMARY_UNIQUE_COMPETITION")
    game=comps[0]
    id_in_summary=str(game.get("id") or header.get("id") or "")
    if id_in_summary and id_in_summary!=event["event_id"]:
        raise ValueError("ESPN_SUMMARY_EVENT_ID_CONFLICT")
    if ((game.get("status") or {}).get("type") or {}).get("completed") is not True:
        raise ValueError("ESPN_SUMMARY_NOT_FINAL")
    if et_date(game.get("date"))!=event["date"]:
        raise ValueError("ESPN_SUMMARY_DATE_CONFLICT")
    teams={x.get("homeAway"):(x.get("team") or {}).get("abbreviation")
           for x in game.get("competitors") or []}
    if teams.get("home")!=event["home"] or teams.get("away")!=event["away"]:
        raise ValueError("ESPN_SUMMARY_OPPONENT_CONFLICT")
    return True

def extract_plays(summary):
    """Preserve an explicit ESPN action sequence; do not invent possessions."""
    plays=summary.get("plays")
    if isinstance(plays,dict):plays=plays.get("plays")
    if not isinstance(plays,list):
        return [],"NO_EXPLICIT_ESPN_PLAY_BY_PLAY"
    valid=[]
    for index,play in enumerate(plays):
        if not isinstance(play,dict):continue
        pnum=(play.get("period") or {}).get("number")
        if pnum is not None:
            try:pnum=int(pnum)
            except (ValueError,TypeError):pnum=None
        clk=(play.get("clock") or {}).get("displayValue")
        valid.append((index,str(play.get("id","")) or None,pnum,clk,
                      json.dumps(play,sort_keys=True,ensure_ascii=False)))
    if len(valid)<30:return [],"INSUFFICIENT_ESPN_ACTION_COVERAGE"
    return valid,"ESPN_ACTION_SEQUENCE_CAPTURED"

def collect(target_date,out_dir,days=3,max_events=20,fetch=None):
    target=dt.date.fromisoformat(target_date)
    if not 1<=days<=35 or not 1<=max_events<=100:
        raise ValueError("UNSAFE_SOURCE_SCAN_RANGE")
    root=Path(out_dir);root.mkdir(parents=True,exist_ok=True)
    db=connect(root/"espn_completed_evidence.sqlite")
    db.execute(PLAY_SCHEMA)
    events=[];problems=[];player_rows=0;play_games=0
    for delta in range(days,0,-1):
        date=(target-dt.timedelta(days=delta)).isoformat()
        url=BASE+"scoreboard?dates="+date.replace("-","")
        try:
            board,raw=fetch_json(url,fetch)
            sha=hashlib.sha256(raw).hexdigest()
            (root/("scoreboard_"+date+"_"+sha[:12]+".json")).write_bytes(raw)
            eligible=completed_scoreboard_events(board,date)
        except (OSError,ValueError,TypeError,urllib.error.URLError,TimeoutError,
                json.JSONDecodeError) as exc:
            problems.append({"date":date,"reason":type(exc).__name__+":"+str(exc)[:140]})
            continue
        for event in eligible:
            if len(events)>=max_events:break
            eid=event["event_id"]
            try:
                summary,rawsummary=fetch_json(BASE+"summary?event="+eid,fetch)
                verify_completed_summary(summary,event)
                sha=hashlib.sha256(rawsummary).hexdigest()
                stamp=dt.datetime.now(dt.timezone.utc).isoformat()
                rows=rows_from_summary(eid,date,event["home"],event["away"],summary)
                played=[];excluded=[]
                for r in rows:
                    r["source_body_sha"]=sha;r["retrieved_at"]=stamp
                    try:
                        validate_row(r,target_date)
                        played.append(r)
                    except (KeyError,TypeError,ValueError) as ex:
                        excluded.append({"player":r.get("player"),
                                         "reason":str(ex)[:130]})
                if len(played)<12:
                    raise ValueError("ESPN_COMPLETED_BOX_UNDER_12_PLAYER_ROWS")
                actions,status=extract_plays(summary)
                db.execute("SAVEPOINT game")
                try:
                    for r in played:
                        db.execute("INSERT INTO current_games VALUES ("+
                                   ",".join("?" for _ in COLUMNS)+")",
                                   [r.get(field) for field in COLUMNS])
                    if actions:
                        db.executemany("""INSERT INTO espn_completed_plays
                          VALUES (?,?,?,?,?,?,?)""",
                          [(eid,date,idx,pid,pnum,clk,sha,payload)
                            for idx,pid,pnum,clk,payload in actions])
                    db.execute("RELEASE SAVEPOINT game")
                except (ValueError,sqlite3.Error):
                    db.execute("ROLLBACK TO SAVEPOINT game")
                    db.execute("RELEASE SAVEPOINT game")
                    raise
                player_rows+=len(played)
                play_games+=int(bool(actions))
                (root/("summary_"+eid+"_"+sha[:12]+".json")).write_bytes(rawsummary)
                events.append({**event,"status":"ESPN_FINAL_BOX_CAPTURED",
                               "box_sha256":sha,"players":len(played),
                               "excluded_player_rows":excluded,
                               "play_by_play_status":status,"play_events":len(actions)})
            except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,
                    urllib.error.URLError,TimeoutError,json.JSONDecodeError) as exc:
                problems.append({"event_id":eid,"date":date,
                                 "reason":type(exc).__name__+":"+str(exc)[:140]})
        if len(events)>=max_events:break
    db.commit()
    if db.execute("SELECT count(*) FROM current_games WHERE date>=?",(target_date,)).fetchone()[0]:
        raise ValueError("LOOKAHEAD_IN_COMPLETED_ESPN_SOURCE")
    integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
    db.close()
    receipt={"status":"ESPN_COMPLETED_GAME_DETAILS" if events else "BLOCKED_ESPN_DETAILS_UNAVAILABLE",
             "target_game_date":target_date,
             "strict_feature_date_before":target_date,
             "source":"ESPN_DIRECT_SECONDARY",
             "completed_games":len(events),"played_player_rows":player_rows,
             "game_play_sequences":play_games,
             "games":events,"issues":problems,
             "sqlite_integrity":integrity,
             "action_sequences_are_certified_possessions":False,
             "confirmed_pregame_starters":False,
             "official_game_certification":False,
             "prediction_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    (root/"espn-completed-game-receipt.json").write_text(
        json.dumps(receipt,indent=2)+"\n")
    return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-date",required=True)
    parser.add_argument("--days",type=int,default=3)
    parser.add_argument("--max-events",type=int,default=20)
    parser.add_argument("--output",required=True)
    a=parser.parse_args()
    receipt=collect(a.target_date,a.output,a.days,a.max_events)
    print(json.dumps({k:receipt[k] for k in
          ("status","completed_games","played_player_rows","game_play_sequences",
           "sqlite_integrity")},indent=2))
    return 0 if receipt["completed_games"] else 2
if __name__=="__main__":
    raise SystemExit(main())
