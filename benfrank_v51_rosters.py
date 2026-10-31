"""ESPN NBA roster index + all team rosters, source-hashed with no starter inference.

A team roster is NOT an official pregame starting lineup or medical clearance.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

BASE="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/"
def list_teams(document):
    seen={}
    for sport in document.get("sports",[]) or []:
        for league in sport.get("leagues",[]) or []:
            for wrapper in league.get("teams",[]) or []:
                t=wrapper.get("team") or wrapper
                teamid=str(t.get("id",""))
                code=t.get("abbreviation")
                if not re.fullmatch(r"\d{1,3}",teamid) or not re.fullmatch(r"[A-Za-z]{2,4}",str(code)):
                    continue
                if teamid in seen and seen[teamid] != code.upper():
                    raise ValueError("CONFLICTING_ESPN_TEAM_ID")
                seen[teamid]=code.upper()
    if len(seen)<25:raise ValueError("INCOMPLETE_ESPN_NBA_TEAM_INDEX")
    return seen
def fetch_roster(teamid,team,fetch=None):
    if not re.fullmatch(r"\d{1,3}",str(teamid)):
        raise ValueError("INVALID_ESPN_TEAM_ID")
    url=BASE+teamid+"/roster"
    if fetch is None:
        req=urllib.request.Request(url,headers={"User-Agent":"BENFRANK-NBA-Roster-Evidence/5.1",
                                                "Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=13) as response:
            if response.status!=200 or not response.geturl().startswith(BASE):
                raise ValueError("ESPN_ROSTER_SOURCE_REDIRECT_OR_HTTP_ERROR")
            raw=response.read(2_000_001)
    else:raw=fetch(url)
    if not raw or len(raw)>2_000_000:raise ValueError("INVALID_OR_OVERSIZED_ROSTER")
    data=json.loads(raw)
    athletes=data.get("athletes",[])
    if not isinstance(athletes,list):raise ValueError("UNSUPPORTED_ESPN_ROSTER_SCHEMA")
    if athletes and isinstance(athletes[0],dict) and "items" in athletes[0]:
        athletes=[player for group in athletes for player in group.get("items",[])]
    players={}
    for item in athletes:
        player=item.get("athlete") or item
        pid=str(player.get("id",""))
        name=player.get("displayName") or player.get("fullName")
        if not pid.isdigit() or not isinstance(name,str) or not name.strip():
            continue
        if pid in players and players[pid]!=name:
            raise ValueError("ESPN_ROSTER_DUPLICATE_PLAYER_ID")
        players[pid]=name
    if len(players)<7:raise ValueError("ESPN_TEAM_ROSTER_TOO_SHORT")
    return {"team_id":teamid,"team_code":team,"players":players,
            "sha256":hashlib.sha256(raw).hexdigest(),"raw":raw}
def collect(index_file,output,fetch=None,workers=5):
    index_path=Path(index_file)
    teams=list_teams(json.loads(index_path.read_bytes()))
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    results=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(fetch_roster,teamid,code,fetch): (teamid,code)
                 for teamid,code in teams.items()}
        for future in concurrent.futures.as_completed(futures):
            teamid,code=futures[future]
            try:
                result=future.result()
                path=root/("team_"+teamid+"_"+result["sha256"][:12]+".json")
                path.write_bytes(result.pop("raw"))
                result["raw_file"]=path.name
                results.append(result)
            except (urllib.error.URLError,ValueError,OSError,TypeError,KeyError,
                    json.JSONDecodeError,TimeoutError) as exc:
                errors.append({"team_id":teamid,"team_code":code,
                               "reason":type(exc).__name__+":"+str(exc)[:160]})
    receipt={"status":"ESPN_ROSTERS_CAPTURED" if len(results)==len(teams)
                         else "PARTIAL_ESPN_ROSTERS",
             "capture_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
             "authority":"ESPN_SECONDARY_ROSTER_NOT_PREGAME_STARTER",
             "roster_teams_found":len(teams),"roster_teams_collected":len(results),
             "player_roster_entries":sum(len(r["players"]) for r in results),
             "rosters":sorted(results,key=lambda r:r["team_code"]),
             "failures":errors,
             "starter_confirmation":False,"minutes_restrictions_verified":False,
             "injury_clearance_inferred":False,
             "model_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    (root/"rosters-evidence-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--teams-index",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    result=collect(args.teams_index,args.output)
    print(json.dumps({key:result[key] for key in (
       "status","roster_teams_found","roster_teams_collected",
       "player_roster_entries","starter_confirmation")},indent=2))
    return 0 if result["roster_teams_collected"]>=25 else 2
if __name__=="__main__":
    raise SystemExit(main())
