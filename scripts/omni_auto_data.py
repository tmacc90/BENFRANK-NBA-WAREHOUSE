"""Additive BENFRANK NBA public-feed execution; no warehouse mutations."""
import argparse, datetime as dt, hashlib, json, os, pathlib, random, statistics, urllib.request
from collections import defaultdict
from omni_evidence import merge_l52, independent_blind, opponent_evidence, role_evidence, windows

BASE="https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"BENFRANK-research/1.0","Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=25) as response: return json.load(response)
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,default=str))
def num(x):
    try: return float(x)
    except (ValueError,TypeError): return None
def get_games(player_id,season,limit=52):
    # ESPN core athlete game log; preserve raw response and fail closed on schema drift.
    url=f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog?season={season}"
    raw=fetch(url)
    events=raw.get("events",{})
    labels=raw.get("labels",[])
    categories=raw.get("seasonTypes",[])
    entries=[]
    for st in categories:
        for cat in st.get("categories",[]):
            for e in cat.get("events",[]):
                event=events.get(str(e.get("eventId")),{})
                if event.get("completed") is False: continue
                stats=e.get("stats",[])
                if not isinstance(stats,list): continue
                vals=dict(zip(labels,stats))
                pts=num(vals.get("PTS")); reb=num(vals.get("REB")); ast=num(vals.get("AST"))
                if None in (pts,reb,ast): continue
                entries.append({"event_id":str(e.get("eventId")),"date":event.get("gameDate"),"points":pts,"rebounds":reb,"assists":ast,"source":url})
    dedup={x["event_id"]:x for x in entries if x["event_id"]!="None"}
    return sorted(dedup.values(),key=lambda x:x["date"] or "",reverse=True)[:limit],raw
def model(games,market,line,seed,trials):
    key={"points":"points","rebounds":"rebounds","assists":"assists"}
    def val(g):
        if market=="pra": return g["points"]+g["rebounds"]+g["assists"]
        if market=="ra": return g["rebounds"]+g["assists"]
        return g[key[market]]
    values=[val(g) for g in games]
    if len(values)<5: raise ValueError("Insufficient verified games (minimum 5)")
    rng=random.Random(seed)
    # Empirical bootstrap: genuine recorded trials, NOT opponent-adjusted possessions.
    draws=[values[rng.randrange(len(values))] for _ in range(trials)]
    blind=sum(values[:min(10,len(values))])/min(10,len(values))
    return {"observations":len(values),"observed_over":sum(x>line for x in values),"observed_under":sum(x<line for x in values),"observed_push":sum(x==line for x in values),"mean":statistics.mean(values),"blind_line_free_recent_mean":blind,"blind_is_independent_ml":False,"simulations":{"method":"empirical_bootstrap_not_possession_model","seed":seed,"trials":trials,"over_fraction":sum(x>line for x in draws)/trials,"under_fraction":sum(x<line for x in draws)/trials,"push_fraction":sum(x==line for x in draws)/trials,"trial_sha256":hashlib.sha256(json.dumps(draws).encode()).hexdigest(),"outcomes":draws},"direction":"OVER" if sum(x>line for x in draws)>sum(x<line for x in draws) else "UNDER","certified":False,"missing":["opponent_defensive_dna","verified_projected_roles","independent_trained_blind_model","walk_forward_calibration"]}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--props",required=True,help="JSON list: player_id, player, market, line, season")
    p.add_argument("--out",default="artifacts/omni")
    p.add_argument("--trials",type=int,default=25000)
    a=p.parse_args()
    if a.trials!=25000: p.error("Certification research contract requires exactly 25000 trials")
    out=pathlib.Path(a.out); props=json.loads(pathlib.Path(a.props).read_text())
    if not isinstance(props,list) or not props:
        save(out/"execution_receipt.json",{"full_certification":False,"status":"BLOCKED","reason":"NO_PROPS_SUPPLIED"})
        raise SystemExit(2)
    reports=[]; failures=[]
    for i,prop in enumerate(props):
        try:
            if prop["market"] not in ("points","rebounds","assists","pra","ra"): raise ValueError("Unsupported market")
            seasons=[int(prop["season"])-1,int(prop["season"])]
            batches=[]
            for season in seasons:
                season_games,raw=get_games(str(prop["player_id"]),season)
                save(out/f"raw_{i}_{season}.json",raw)
                batches.append(season_games)
            games=merge_l52(batches)
            result=model(games,prop["market"],float(prop["line"]),20261105+i,a.trials)
            result["prop"]=prop;result["games"]=games
            result["historical_windows"]=windows(games,prop["market"],float(prop["line"]))
            result["l52_coverage"]={"actual_games":len(games),"complete":len(games)==52}
            result["blind_model"]=independent_blind(games,prop["market"])
            result["opponent_defense"]=opponent_evidence(prop)
            result["projected_role"]=role_evidence(prop)
            result["certified"]=False
            result["status"]="RESEARCH_ONLY_UNCERTIFIED"
            result["data_quality"]={"l52_complete":len(games)==52,"opponent_verified":False,"role_verified":False,"blind_ml_certified":False}
            save(out/f"report_{i}.json",result);reports.append({"prop":prop,"direction":result["direction"],"certified":False})
        except Exception as exc:
            failures.append({"prop":prop,"error":str(exc)})
    save(out/"execution_receipt.json",{"generated_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"reports":reports,"failures":failures,"full_certification":False})
    if failures: raise SystemExit(2)
if __name__=="__main__": main()
