"""BENFRANK free NBA lineup/WOWY acquisition and reconstruction layer.

Preferred: NBA aggregate lineup/on-off endpoints.
Fallback: NBA PlayByPlayV3 + BoxScoreTraditionalV3, reconstructed into stints.
Every raw response is cached once. Failed validation never becomes FULL evidence.
"""
from __future__ import annotations
import argparse, hashlib, json, re, time
from collections import defaultdict
from pathlib import Path
import requests

NBA="https://stats.nba.com/stats"
HEADERS={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36",
"Referer":"https://www.nba.com/","Origin":"https://www.nba.com","x-nba-stats-origin":"stats","x-nba-stats-token":"true",
"Accept":"application/json, text/plain, */*"}
SUB={"substitution","sub"}
CLOCK=re.compile(r"PT(?:(\d+)M)?([0-9.]+)S")

def sha(b): return hashlib.sha256(b).hexdigest()
def sec(clock):
    m=CLOCK.fullmatch(str(clock))
    if not m: raise ValueError("BAD_CLOCK:"+str(clock))
    return int(m.group(1) or 0)*60+float(m.group(2))
def elapsed(period,clock):
    q=720 if period<=4 else 300
    before=min(period-1,4)*720+max(period-5,0)*300
    return before+(q-sec(clock))
def fetch(url,params,cache,timeout=25):
    cache=Path(cache); cache.parent.mkdir(parents=True,exist_ok=True)
    if cache.exists(): return json.loads(cache.read_text()),"CACHE"
    e=None
    for i in range(3):
        try:
            r=requests.get(url,params=params,headers=HEADERS,timeout=timeout)
            r.raise_for_status(); raw=r.content
            data=r.json(); cache.write_bytes(raw)
            cache.with_suffix(cache.suffix+".meta.json").write_text(json.dumps(
                {"url":r.url,"sha256":sha(raw),"retrieved_unix":time.time(),"status":r.status_code},indent=2))
            return data,"NETWORK"
        except Exception as x:
            e=x; time.sleep(1.5*(i+1))
    raise RuntimeError("SOURCE_FETCH_FAILED:"+type(e).__name__+":"+str(e))

def result_rows(data,name=None):
    sets=data.get("resultSets") or data.get("resultSet") or []
    if isinstance(sets,dict): sets=[sets]
    for s in sets:
        if name is None or str(s.get("name","")).lower()==name.lower():
            h=s.get("headers",[]); return [dict(zip(h,r)) for r in s.get("rowSet",[])]
    return []

def pbp_actions(data):
    if isinstance(data.get("game"),dict): return data["game"].get("actions",[])
    rows=result_rows(data,"PlayByPlay")
    return rows

def box_players(data):
    # V3 nested response
    out=[]
    for side in ("homeTeam","awayTeam"):
        team=data.get("game",{}).get(side,{})
        tid=team.get("teamId")
        for p in team.get("players",[]):
            out.append({"team_id":tid,"player_id":p.get("personId"),"name":p.get("name"),
                        "starter":bool(p.get("starter")),"minutes":p.get("statistics",{}).get("minutes")})
    if out:return out
    rows=result_rows(data)
    for r in rows:
        if r.get("PLAYER_ID") is not None:
            out.append({"team_id":r.get("TEAM_ID"),"player_id":r.get("PLAYER_ID"),"name":r.get("PLAYER_NAME"),
                        "starter":str(r.get("START_POSITION","")).strip()!="","minutes":r.get("MIN")})
    return out

def period_starters(actions,players,period):
    # Infer first five distinct participants per team before substitutions; starters from box for Q1.
    teams=defaultdict(list)
    if period==1:
        for p in players:
            if p["starter"] and p["player_id"] is not None: teams[p["team_id"]].append(p["player_id"])
    for a in actions:
        if int(a.get("period",a.get("PERIOD",0)) or 0)!=period: continue
        typ=str(a.get("actionType",a.get("EVENTMSGTYPE",""))).lower()
        if typ in SUB or typ=="8": break
        tid=a.get("teamId") or a.get("PLAYER1_TEAM_ID")
        ids=[a.get("personId"),a.get("PLAYER1_ID"),a.get("PLAYER2_ID"),a.get("PLAYER3_ID")]
        for pid in ids:
            if tid and pid and pid not in teams[tid] and len(teams[tid])<5: teams[tid].append(pid)
    return {k:v for k,v in teams.items() if len(v)==5}

def reconstruct(actions,players):
    periods=sorted({int(a.get("period",a.get("PERIOD",0)) or 0) for a in actions if int(a.get("period",a.get("PERIOD",0)) or 0)>0})
    stints=[]; current={}; start_t=None; start_score=(0,0)
    for period in periods:
        starters=period_starters(actions,players,period)
        if len(starters)!=2: raise ValueError("PERIOD_STARTERS_UNRESOLVED:"+str(period))
        current={k:list(v) for k,v in starters.items()}
        qlen=720 if period<=4 else 300
        start_t=elapsed(period,f"PT{qlen//60}M00.00S")
        period_actions=[a for a in actions if int(a.get("period",a.get("PERIOD",0)) or 0)==period]
        for a in period_actions:
            typ=str(a.get("actionType",a.get("EVENTMSGTYPE",""))).lower()
            if typ not in SUB and typ!="8": continue
            t=elapsed(period,a.get("clock",a.get("PCTIMESTRING")))
            if t>start_t:
                stints.append({"period":period,"start":start_t,"end":t,
                    "lineups":{str(k):sorted(v) for k,v in current.items()}})
            # V3 description normally identifies incoming/outgoing; personId is incoming in modern feed.
            desc=str(a.get("description") or a.get("HOMEDESCRIPTION") or a.get("VISITORDESCRIPTION") or "")
            incoming=a.get("personId") or a.get("PLAYER1_ID")
            outgoing=a.get("PLAYER2_ID")
            tid=a.get("teamId") or a.get("PLAYER1_TEAM_ID")
            if outgoing is None:
                # resolve outgoing name from "SUB: X FOR Y"
                m=re.search(r"SUB:\s*(.+?)\s+FOR\s+(.+)$",desc,re.I)
                if m:
                    names={str(p["name"]).lower():p["player_id"] for p in players if p["team_id"]==tid}
                    incoming=names.get(m.group(1).strip().lower(),incoming)
                    outgoing=names.get(m.group(2).strip().lower())
            if tid not in current or not incoming or not outgoing or outgoing not in current[tid]:
                raise ValueError("SUBSTITUTION_UNRESOLVED:"+desc)
            current[tid].remove(outgoing); current[tid].append(incoming)
            if len(set(current[tid]))!=5: raise ValueError("LINEUP_NOT_FIVE")
            start_t=t
        end=elapsed(period,"PT0M00.00S")
        if end>start_t: stints.append({"period":period,"start":start_t,"end":end,
            "lineups":{str(k):sorted(v) for k,v in current.items()}})
    return stints

def summarize(stints,players):
    mins=defaultdict(float); lineups=defaultdict(float); close=defaultdict(lambda:[0.0,0.0])
    for s in stints:
        dur=(s["end"]-s["start"])/60
        for tid,ids in s["lineups"].items():
            key=tid+":"+"_".join(map(str,ids)); lineups[key]+=dur
            for pid in ids: mins[int(pid)]+=dur
            # Q4 final six minutes proxy; exact score-margin filter is added when score state is present.
            if s["period"]==4 and s["end"]>=2520:
                for p in players:
                    if str(p["team_id"])==tid: close[p["player_id"]][1]+=dur
                for pid in ids: close[int(pid)][0]+=dur
    return {"player_minutes":dict(mins),"lineup_minutes":dict(lineups),
            "closing_share":{str(k):(v[0]/v[1] if v[1] else None) for k,v in close.items()}}

def acquire_game(game_id,out):
    if not re.fullmatch(r"\d{10}",game_id): raise ValueError("GAME_ID_MUST_BE_10_DIGITS")
    root=Path(out)/game_id; raw=root/"raw"
    pbp,pbp_route=fetch(NBA+"/playbyplayv3",{"GameID":game_id,"StartPeriod":0,"EndPeriod":0},raw/"playbyplayv3.json")
    box,box_route=fetch(NBA+"/boxscoretraditionalv3",{"GameID":game_id,"StartPeriod":0,"EndPeriod":0,"StartRange":0,"EndRange":0,"RangeType":0},raw/"boxscoretraditionalv3.json")
    actions=pbp_actions(pbp); players=box_players(box)
    if not actions or len(players)<10: raise ValueError("RAW_GAME_INPUT_INCOMPLETE")
    stints=reconstruct(actions,players); summary=summarize(stints,players)
    root.mkdir(parents=True,exist_ok=True)
    (root/"stints.json").write_text(json.dumps(stints,indent=2))
    (root/"summary.json").write_text(json.dumps(summary,indent=2))
    receipt={"game_id":game_id,"pbp_route":pbp_route,"box_route":box_route,"events":len(actions),
             "players":len(players),"stints":len(stints),"five_man_units":len(summary["lineup_minutes"]),
             "status":"FULL_RECONSTRUCTION","limitations":["closing_share currently uses Q4 final-six-minute time window; competitive score-margin filtering requires score-state stint enrichment"]}
    (root/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt

def main():
    p=argparse.ArgumentParser(); p.add_argument("--game-id",action="append",required=True); p.add_argument("--output",default="lineup_cache")
    a=p.parse_args(); results=[]
    for gid in a.game_id:
        try: results.append(acquire_game(gid,a.output))
        except Exception as e: results.append({"game_id":gid,"status":"FAILED","reason":type(e).__name__+":"+str(e)})
    print(json.dumps(results,indent=2))
    raise SystemExit(0 if all(x["status"]!="FAILED" for x in results) else 2)
if __name__=="__main__": main()
