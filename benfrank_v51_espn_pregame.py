"""Evidence-only ESPN.com pregame game schedule and provisional listed starters.

No bookmaker lines; an ESPN pregame listed starter is NOT NBA official final
starting five or confirmed playing minutes. Capture must truly precede tipoff,
using current retrieval time (never user-supplied backdating).
"""
import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from benfrank_v51_espn_game_details import BASE,fetch_json,et_date

ET=ZoneInfo("America/New_York")
UTC=dt.timezone.utc
def current_utc():
    return dt.datetime.now(UTC)
def upcoming_events(board,game_date,observed_at):
    items=board.get("events")
    if not isinstance(items,list):
        raise ValueError("ESPN_SCOREBOARD_NO_EVENTS")
    result=[]
    for event in items:
        try:
            eid=str(event["id"])
            if not re.fullmatch(r"\d{6,15}",eid):continue
            stamp=dt.datetime.fromisoformat(event["date"].replace("Z","+00:00"))
            if stamp.tzinfo is None or stamp.astimezone(UTC)<=observed_at:
                continue
            if et_date(event["date"])!=game_date:continue
            typ=(event.get("status") or {}).get("type") or {}
            if typ.get("completed") is True or typ.get("state") not in ("pre",None):
                continue
            comp=event.get("competitions") or []
            if len(comp)!=1:continue
            teams={x.get("homeAway"):(x.get("team") or {}).get("abbreviation")
                   for x in comp[0].get("competitors") or []}
            if not teams.get("home") or not teams.get("away"):continue
            result.append({"event_id":eid,"game_date":game_date,"tipoff_utc":stamp.astimezone(UTC).isoformat(),
                           "home":teams["home"],"away":teams["away"],
                           "status":"PRE_GAME_UNCONFIRMED","espn_expected_starters":[]})
        except (KeyError,TypeError,ValueError):continue
    return result

def candidates(summary,upcoming):
    header=summary.get("header") or {}
    comps=header.get("competitions") or []
    if len(comps)!=1:return [],"UNSUPPORTED_ESPN_PREGAME_SUMMARY"
    comp=comps[0]
    if str(comp.get("id") or header.get("id") or "") not in ("",upcoming["event_id"]):
        raise ValueError("ESPN_PREGAME_SUMMARY_EVENT_ID_CONFLICT")
    if ((comp.get("status") or {}).get("type") or {}).get("completed") is True:
        raise ValueError("ACTUAL_GAME_ALREADY_COMPLETED_NOT_PREGAME_EVIDENCE")
    body=(summary.get("boxscore") or {}).get("players") or []
    players=[]
    for roster in body:
        team=(roster.get("team") or {}).get("abbreviation")
        if team not in (upcoming["home"],upcoming["away"]):continue
        for stat_group in roster.get("statistics") or []:
            for athlete in stat_group.get("athletes") or []:
                # We accept only an EXPLICIT boolean starter field.
                # A blank/unlisted player is not treated as available.
                if athlete.get("starter") is not True:continue
                player=(athlete.get("athlete") or {})
                name=player.get("displayName");pid=player.get("id")
                if name and pid is not None:
                    players.append({"player":name,"espn_player_id":str(pid),"team":team,
                                    "evidence":"ESPN_PREGAME_LISTED_STARTER_NOT_OFFICIAL"})
    unique={(v["team"],v["espn_player_id"]):v for v in players}
    return list(unique.values()),"ESPN_TENTATIVE_LISTED_STARTERS" if unique else "NO_EXPLICIT_ESPN_PREGAME_STARTER_FIELDS"

def collect(game_date,output,fetch=fetch_json,clock=current_utc):
    dt.date.fromisoformat(game_date)
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    observed=clock()
    if observed.tzinfo is None:
        raise ValueError("UNCERTAIN_COLLECTOR_CLOCK")
    if (dt.date.fromisoformat(game_date)-observed.astimezone(ET).date()).days not in (0,1,2):
        raise ValueError("PREGAME_SNAPSHOT_DATE_NOT_CONTEMPORANEOUS")
    board,raw=fetch(BASE+"scoreboard?dates="+game_date.replace("-",""))
    board_sha=hashlib.sha256(raw).hexdigest()
    (root/("pregame_scoreboard_"+board_sha[:12]+".json")).write_bytes(raw)
    games=upcoming_events(board,game_date,observed)
    errors=[]
    for game in games:
        try:
            summary,body=fetch(BASE+"summary?event="+game["event_id"])
            # Critical: source captured again before tipoff, not only earlier
            # scoreboard capture. A late response is never backdated.
            acquired=clock()
            tipoff=dt.datetime.fromisoformat(game["tipoff_utc"])
            if acquired.tzinfo is None or acquired.astimezone(UTC)>=tipoff:
                raise ValueError("PREGAME_SUMMARY_CAPTURE_AFTER_TIPOFF")
            listed,status=candidates(summary,game)
            digest=hashlib.sha256(body).hexdigest()
            (root/("pregame_summary_"+game["event_id"]+"_"+digest[:12]+".json")).write_bytes(body)
            game.update(espn_expected_starters=listed,starter_source_status=status,
                        summary_sha256=digest,summary_captured_utc=acquired.astimezone(UTC).isoformat())
        except (ValueError,KeyError,TypeError,OSError,TimeoutError) as exc:
            errors.append({"event_id":game["event_id"],"reason":type(exc).__name__+":"+str(exc)[:160]})
            game["starter_source_status"]="UNAVAILABLE_OR_UNVERIFIABLE"
    receipt={"status":"ESPN_PREGAME_CAPTURED" if games else "NO_UPCOMING_ESPN_GAMES",
             "source":"ESPN_SECONDARY_NOT_NBA_FINAL_AUTHORITY",
             "game_date":game_date,"actual_collector_start_utc":observed.astimezone(UTC).isoformat(),
             "scoreboard_sha256":board_sha,"games":games,"issues":errors,
             "listed_pregame_starters":sum(len(x["espn_expected_starters"]) for x in games),
             "final_official_starters_confirmed":0,
             "player_minute_restrictions_verified":False,
             "native_prizepicks_lines_authenticated":False,
             "prediction_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    (root/"espn-pregame-observations.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game-date",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    report=collect(args.game_date,args.output)
    print(json.dumps({k:report[k] for k in
        ("status","listed_pregame_starters","final_official_starters_confirmed",
         "player_minute_restrictions_verified")},indent=2))
    return 0 if report["status"]=="ESPN_PREGAME_CAPTURED" else 2
if __name__=="__main__":
    raise SystemExit(main())
