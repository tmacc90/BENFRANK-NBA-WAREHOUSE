"""Additive evidence gates: multi-season L52, role snapshots and isolated blind regression."""
import hashlib, json, math, statistics
def merge_l52(season_games):
    seen={}
    for games in season_games:
        for g in games:
            if not g.get("event_id") or not g.get("date"): continue
            seen[g["event_id"]]=g
    return sorted(seen.values(),key=lambda g:g["date"],reverse=True)[:52]
def extract(g,market):
    if market=="pra": return g["points"]+g["rebounds"]+g["assists"]
    if market=="ra": return g["rebounds"]+g["assists"]
    return g[market]
def independent_blind(games,market):
    """Line-free expanding-window ridge trend fit. Training excludes latest five games."""
    vals=[extract(g,market) for g in reversed(games)]
    if len(vals)<15: return {"status":"INSUFFICIENT_TRAINING","count":len(vals)}
    train=vals[:-5]; n=len(train)
    xs=list(range(n)); mx=statistics.mean(xs); my=statistics.mean(train)
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,train))/(sum((x-mx)**2 for x in xs)+100.0)
    pred=max(0.0,my+slope*(n-mx))
    errors=[]
    for t in range(10,n):
        history=train[:t]; baseline=statistics.mean(history)
        errors.append(abs(baseline-train[t]))
    return {"status":"RESEARCH_BASELINE","method":"line_free_regularized_trend","prediction":pred,"holdout_last5_mae":statistics.mean(abs(pred-y) for y in vals[-5:]),"training_n":n,"training_only_mae":statistics.mean(errors) if errors else None,"independent_from_primary_simulation":True,"trained_ml_certified":False}
def opponent_evidence(prop):
    """Only accepts timestamped source-backed defensive facts; never synthesize a ranking."""
    ev=prop.get("opponent_evidence",{})
    required=("source_url","as_of_utc","metric","value","opponent")
    if not isinstance(ev,dict) or any(ev.get(k) is None for k in required):
        return {"status":"MISSING_VERIFIED_OPPONENT_DATA"}
    return {"status":"USER_SUPPLIED_NOT_CROSS_VERIFIED","facts":ev}
def role_evidence(prop):
    ev=prop.get("role_evidence",{})
    required=("source_url","as_of_utc","availability","projected_minutes")
    if not isinstance(ev,dict) or any(ev.get(k) is None for k in required):
        return {"status":"MISSING_VERIFIED_ROLE_DATA"}
    return {"status":"USER_SUPPLIED_NOT_CROSS_VERIFIED","facts":ev}
def windows(games,market,line):
    result={}
    for n in (5,10,15,20,25,32,52):
        v=[extract(g,market) for g in games[:n]]
        result["L"+str(n)]={"count":len(v),"over":sum(x>line for x in v),"under":sum(x<line for x in v),"push":sum(x==line for x in v),"mean":statistics.mean(v) if v else None}
    return result
