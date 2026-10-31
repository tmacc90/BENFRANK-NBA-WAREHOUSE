"""Official NBA CDN previous-day evidence: final box scores and play-by-play.

Never uses target-day games as pregame features. A scheduled game, a live
box score, or a partial game is NOT an official final box score. All NBA raw
source bytes and source hashes remain preserved in the artifact.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from benfrank_v51_multisource_capture import SOURCES, capture

UTC=dt.timezone.utc
ET=ZoneInfo("America/New_York")
NBA="https://cdn.nba.com/static/json/liveData/"
FIELDS=("game_id","person_id","player","game_date","team","opponent","home","starter",
        "minutes","pts","reb","ast","stl","blk","tov","fg3m",
        "fgm","fga","fg3a","ftm","fta","oreb","dreb","box_sha256","captured_at")
SCHEMA="""CREATE TABLE IF NOT EXISTS nba_official_completed (
 game_id TEXT NOT NULL,person_id TEXT NOT NULL,player TEXT NOT NULL,
 game_date TEXT NOT NULL,team TEXT NOT NULL,opponent TEXT NOT NULL,
 home INTEGER NOT NULL,starter INTEGER,minutes REAL NOT NULL,
 pts INTEGER NOT NULL,reb INTEGER NOT NULL,ast INTEGER NOT NULL,
 stl INTEGER NOT NULL,blk INTEGER NOT NULL,tov INTEGER NOT NULL,
 fg3m INTEGER NOT NULL,fgm INTEGER NOT NULL,fga INTEGER NOT NULL,
 fg3a INTEGER NOT NULL,ftm INTEGER NOT NULL,fta INTEGER NOT NULL,
 oreb INTEGER NOT NULL,dreb INTEGER NOT NULL,
 box_sha256 TEXT NOT NULL,captured_at TEXT NOT NULL,
 PRIMARY KEY(game_id,person_id))"""
def parse_timestamp(game):
    stamp=game.get("gameDateTimeUTC")
    if isinstance(stamp,str):
        try:
            result=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
            if result.tzinfo:
                return result.astimezone(ET).date().isoformat()
        except ValueError:pass
    # NBA publishes an Eastern Time gameDate, but this must be a strict date.
    value=game.get("gameDate")
    if isinstance(value,str):
        text=value[:10]
        for fmt in ("%Y-%m-%d","%m/%d/%Y"):
            try:return dt.datetime.strptime(text,fmt).date().isoformat()
            except ValueError:continue
    raise ValueError("GAME_DATE_NOT_SUPPORTED")
def games_before(schedule,target_date,days=3,limit=20):
    target=dt.date.fromisoformat(target_date)
    if not 1<=days<=35 or not 1<=limit<=60:
        raise ValueError("GAME_SCOPE_OUTSIDE_POLICY")
    entries=(schedule.get("leagueSchedule") or {}).get("gameDates") or []
    if not isinstance(entries,list) or not entries:
        raise ValueError("NO_LEAGUE_SCHEDULE_GAMEDATES")
    results=[]
    seen=set()
    for day in entries:
        if not isinstance(day,dict):continue
        for game in day.get("games") or []:
            if not isinstance(game,dict):continue
            gid=str(game.get("gameId",""))
            if not re.fullmatch(r"\d{10}",gid) or not gid.startswith("002"):
                continue
            if gid in seen:raise ValueError("DUPLICATE_NBA_GAME_ID_IN_SCHEDULE")
            seen.add(gid)
            date=parse_timestamp(game)
            date_obj=dt.date.fromisoformat(date)
            if not target-dt.timedelta(days=days)<=date_obj<target:continue
            if str(game.get("gameStatus"))!="3":continue
            home=(game.get("homeTeam") or {}).get("teamTricode")
            away=(game.get("awayTeam") or {}).get("teamTricode")
            if not home or not away or home==away:
                raise ValueError("SOURCE_SCHEDULE_MISSING_TEAM")
            results.append({"game_id":gid,"game_date":date,"home":home,"away":away})
    results.sort(key=lambda g:(g["game_date"],g["game_id"]))
    return results[:limit],len(results)
def minutes(value):
    if not isinstance(value,str):raise ValueError("MISSING_MINUTES_FORMAT")
    pattern=re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?",value)
    if not pattern:raise ValueError("NBA_MINUTES_ISO_DURATION_UNSUPPORTED")
    hours,mins,secs=pattern.groups()
    result=60*int(hours or 0)+int(mins or 0)+float(secs or 0)/60
    if not 0<=result<=70:raise ValueError("MINUTES_OUT_OF_RANGE")
    return result
def integer(value,name):
    if isinstance(value,bool):raise ValueError("BOOLEAN_BOX_SCORE_STAT_"+name)
    if isinstance(value,float) and not value.is_integer():raise ValueError("FRACTIONAL_BOX_SCORE_STAT_"+name)
    try:x=int(value)
    except (TypeError,ValueError):raise ValueError("MISSING_BOX_SCORE_STAT_"+name) from None
    if x<0 or x>200:raise ValueError("OUT_OF_RANGE_BOX_SCORE_STAT_"+name)
    return x
def parsed_game(original,expected,boxhash,observed):
    game=original.get("game") if isinstance(original,dict) else None
    if not isinstance(game,dict):raise ValueError("NBA_BOX_GAME_MISSING")
    if str(game.get("gameId"))!=expected["game_id"]:
        raise ValueError("NBA_GAME_ID_CONFLICT")
    if str(game.get("gameStatus"))!="3":
        raise ValueError("NBA_GAME_NOT_FINAL")
    h=game.get("homeTeam") or {};a=game.get("awayTeam") or {}
    if h.get("teamTricode")!=expected["home"] or a.get("teamTricode")!=expected["away"]:
        raise ValueError("NBA_GAME_TEAM_CONFLICT")
    rows=[]
    excluded=[]
    for team,opp,home,data in ((expected["home"],expected["away"],1,h),
                               (expected["away"],expected["home"],0,a)):
        players=data.get("players") or []
        if not isinstance(players,list) or len(players)<7:
            raise ValueError("FINAL_NBA_TEAM_PLAYERS_NOT_COMPLETE:"+team)
        for player in players:
            s=player.get("statistics") or {}
            played=player.get("played") in ("1",1,True,"true","True")
            if not played:
                excluded.append({"team":team,"person_id":str(player.get("personId")),
                                 "reason":"NBA_OFFICIAL_DNP"})
                continue
            try:
                person_id=str(player["personId"])
                if not person_id.isdigit():raise ValueError("INVALID_PERSON_ID")
                name=player.get("name") or ((player.get("firstName") or "")+" "+(player.get("familyName") or "")).strip()
                if not name:raise ValueError("MISSING_NBA_PLAYER_NAME")
                mp=minutes(s.get("minutes"))
                if mp<=0:
                    excluded.append({"team":team,"person_id":person_id,"reason":"NBA_OFFICIAL_ZERO_MINUTE"})
                    continue
                ns={k:integer(s.get(src),src) for k,src in (
                    ("pts","points"),("reb","reboundsTotal"),("ast","assists"),
                    ("stl","steals"),("blk","blocks"),("tov","turnovers"),
                    ("fg3m","threePointersMade"),("fgm","fieldGoalsMade"),
                    ("fga","fieldGoalsAttempted"),("fg3a","threePointersAttempted"),
                    ("ftm","freeThrowsMade"),("fta","freeThrowsAttempted"),
                    ("oreb","reboundsOffensive"),("dreb","reboundsDefensive"))}
                if (ns["fgm"]>ns["fga"] or ns["fg3m"]>ns["fg3a"] or
                    ns["fg3m"]>ns["fgm"] or ns["fg3a"]>ns["fga"] or
                    ns["oreb"]+ns["dreb"]!=ns["reb"]):
                    raise ValueError("NBA_SHOOTING_OR_REBOUND_CONTRADICTION")
                ft_attempted=integer(s.get("freeThrowsAttempted"),"freeThrowsAttempted")
                if ns["ftm"]>ft_attempted or 2*ns["fgm"]+ns["fg3m"]+ns["ftm"]!=ns["pts"]:
                    raise ValueError("NBA_POINT_ACCOUNTING_CONTRADICTION")
                row={"game_id":expected["game_id"],"person_id":person_id,"player":name,
                     "game_date":expected["game_date"],"team":team,"opponent":opp,
                     "home":home,"starter":1 if player.get("starter") is True else
                     0 if player.get("starter") is False else None,
                     "minutes":mp,**ns,"box_sha256":boxhash,"captured_at":observed}
                rows.append(row)
            except (TypeError,KeyError,ValueError) as exc:
                excluded.append({"team":team,"person_id":str(player.get("personId")),
                                 "reason":str(exc)[:120]})
    if len(rows)<12:
        raise ValueError("INSUFFICIENT_FINAL_OFFICIAL_PLAYED_ROWS")
    return rows,excluded
def source_get(url,limit=6_000_000,fetch=None):
    if not url.startswith(NBA):
        raise ValueError("NON_NBA_CDN_SOURCE")
    if fetch is not None:
        status,mimetype,raw=fetch(url,limit)
    else:
        req=urllib.request.Request(url,headers={"User-Agent":"BENFRANK-NBA-Official-Research/5.1",
                                                "Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=14) as res:
            status,mimetype=res.status,res.headers.get("Content-Type","")
            if not res.geturl().startswith(NBA):raise ValueError("UNEXPECTED_NBA_REDIRECT")
            raw=res.read(limit+1)
    if status!=200 or "json" not in mimetype.lower() or not raw or len(raw)>limit:
        raise ValueError("UNAVAILABLE_NBA_CDN_JSON")
    parsed=json.loads(raw)
    if not isinstance(parsed,dict):raise ValueError("NON_OBJECT_NBA_CDN_JSON")
    return parsed,raw
def collect(target_day,root,days=3,max_games=20,fetch=None,raw_schedule=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if raw_schedule is None:
        srec=capture("nba_cdn_schedule",target_day,root)
        if srec["status"]!="CAPTURED_UNVERIFIED":
            return {"status":"BLOCKED_NBA_SCHEDULE_UNAVAILABLE","schedule_receipt":srec,
                    "games":[],"rows":0,"ticket_authority":"NO_TICKET"}
        raw_schedule=json.loads((root/srec["raw_file"]).read_bytes())
    else:srec={"status":"SUPPLIED_CACHED_NBA_SCHEDULE_FOR_TEST","certified":False}
    eligible,all_eligible=games_before(raw_schedule,target_day,days,max_games)
    c=sqlite3.connect(root/"nba_official_2026_27.sqlite")
    c.execute(SCHEMA)
    completed=[];errors=[];nrows=0;playbyplay=0
    for item in eligible:
        gid=item["game_id"]
        try:
            body,raw=source_get(NBA+"boxscore/boxscore_"+gid+".json",fetch=fetch)
            sha=hashlib.sha256(raw).hexdigest()
            stamp=dt.datetime.now(UTC).isoformat()
            rows,exclusions=parsed_game(body,item,sha,stamp)
            for r in rows:
                c.execute("INSERT INTO nba_official_completed VALUES ("+
                          ",".join("?" for _ in FIELDS)+")",
                          [r[field] for field in FIELDS])
            nrows+=len(rows)
            (root/("official_boxscore_"+gid+".json")).write_bytes(raw)
            entry={"game_id":gid,"game_date":item["game_date"],
                   "box_sha256":sha,"status":"FINAL_OFFICIAL_BOX_PARSED",
                   "players":len(rows),"excluded_players":exclusions}
            try:
                plays,rawplays=source_get(NBA+"playbyplay/playbyplay_"+gid+".json",fetch=fetch)
                acts=(plays.get("game") or {}).get("actions") or []
                if (str((plays.get("game") or {}).get("gameId"))!=gid or
                        not isinstance(acts,list) or len(acts)<30):
                    raise ValueError("NBA_PBP_GAME_ID_OR_ACTION_COUNT_INVALID")
                playbyplay+=1
                pb_sha=hashlib.sha256(rawplays).hexdigest()
                (root/("official_pbp_"+gid+".json")).write_bytes(rawplays)
                entry["pbp"]={"status":"CAPTURED_OFFICIAL_ACTION_SEQUENCE",
                              "actions":len(acts),"sha256":pb_sha}
            except (OSError,ValueError,urllib.error.URLError,TimeoutError) as exc:
                entry["pbp"]={"status":"BLOCKED_MISSING_OFFICIAL_PBP",
                              "reason":type(exc).__name__+":"+str(exc)[:150]}
            completed.append(entry)
        except (OSError,ValueError,TypeError,KeyError,urllib.error.URLError,TimeoutError) as exc:
            errors.append({"game_id":gid,"game_date":item["game_date"],
                           "reason":type(exc).__name__+":"+str(exc)[:180]})
    c.commit()
    integrity=c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    receipt={"status":"OFFICIAL_FINAL_BOX_SCORES_COLLECTED" if completed else
                    "BLOCKED_NO_FINAL_OFFICIAL_BOX",
             "source":"NBA_CDN_OFFICIAL", "target_date":target_day,
             "cutoff_policy":"STRICTLY_EARLIER_COMPLETED_NBA_GAMES_ONLY",
             "eligible_games_in_schedule":all_eligible,"games_attempted":len(eligible),
             "final_boxes":len(completed),"official_player_game_rows":nrows,
             "official_pbp_games":playbyplay,"games":completed,"errors":errors,
             "schedule_receipt":srec,"sqlite_integrity":integrity,
             "pregame_lineup_confirmation":False,
             "pregame_prop_line_authentication":False,
             "model_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    (root/"nba-official-game-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target-date",required=True)
    p.add_argument("--days",type=int,default=3)
    p.add_argument("--max-games",type=int,default=20)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    r=collect(a.target_date,a.output,a.days,a.max_games)
    print(json.dumps({k:r.get(k) for k in
       ("status","target_date","games_attempted","final_boxes","official_player_game_rows",
        "official_pbp_games","sqlite_integrity")},indent=2))
    return 0 if r["status"]=="OFFICIAL_FINAL_BOX_SCORES_COLLECTED" else 2
if __name__=="__main__":
    raise SystemExit(main())
