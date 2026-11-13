"""BENFRANK exact-line evidence engine. Sport-neutral mechanics; sport-specific features stay isolated.
Inputs must be verified pre-cutoff game logs. This is descriptive evidence, not a calibrated forecast.
"""
from datetime import datetime, timezone
from math import exp
from statistics import mean, median, stdev
from math import isfinite

WINDOWS=(5,10,15,20)
FEATURES=("workload","opportunities","conversion","defense","matchup","role","pace","foul_risk","double_team","recent_form")

def _utc(value):
    if not isinstance(value,str): raise ValueError("MISSING_TIMESTAMP")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None: raise ValueError("NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)

def _rate(games,line):
    over=sum(g["stat"]>line for g in games)
    under=sum(g["stat"]<line for g in games)
    push=len(games)-over-under
    return {"n":len(games),"over":over,"under":under,"push":push,
            "over_rate":over/len(games) if games else None,
            "under_rate":under/len(games) if games else None,
            "mean":mean(g["stat"] for g in games) if games else None,
            "median":median(g["stat"] for g in games) if games else None,
            "stdev":stdev(g["stat"] for g in games) if len(games)>1 else None}

def analyze_exact_line(*, sport, player, market, line, games, cutoff_utc,
                       current_season, previous_season, current_features=None,
                       sport_feature_weights=None, analog_limit=8, opponent=None):
    if not sport or not player or not market: raise ValueError("MISSING_PROP_IDENTITY")
    if not isinstance(line,(int,float)) or isinstance(line,bool) or not isfinite(line): raise ValueError("INVALID_LINE")
    cutoff=_utc(cutoff_utc)
    valid=[]
    for g in games:
        if g.get("sport")!=sport or g.get("player")!=player or g.get("market")!=market:
            raise ValueError("CROSS_SPORT_OR_PROP_LOG")
        ts=_utc(g["game_utc"])
        if ts>=cutoff: raise ValueError("POST_CUTOFF_GAME_LEAKAGE")
        if not isinstance(g.get("stat"),(int,float)) or isinstance(g["stat"],bool) or not isfinite(g['stat']):
            raise ValueError("UNVERIFIED_GAME_STAT")
        if not g.get("source") or not g.get("game_id"): raise ValueError("MISSING_SOURCE_RECEIPT")
        valid.append(dict(g))
    valid.sort(key=lambda g:_utc(g["game_utc"]),reverse=True)
    current=[g for g in valid if g.get('season')==current_season]
    windows={"L"+str(n):_rate((current if sport=='NBA' else valid)[:n],line) for n in ((5,10,15) if sport=='NBA' else WINDOWS)}
    if sport=='NBA':
        for n in (5,10,15):
            if len(current)<n:
                windows['L'+str(n)]=dict(_rate([],line),availability='UNAVAILABLE',available_current_season_n=len(current))
    windows["current_season"]=_rate([g for g in valid if g.get("season")==current_season],line)
    windows["previous_season"]=_rate([g for g in valid if g.get("season")==previous_season],line)
    windows["career"]=_rate(valid,line)
    if sport=='NBA':
        for key,season in [('current_season_h2h',current_season),('previous_season_h2h',previous_season)]:
            windows[key]=_rate([g for g in valid if g.get('season')==season and opponent and g.get('opponent')==opponent],line)
    current_features=current_features or {}
    weights=sport_feature_weights or {}
    analogs=[]
    for g in valid:
        factors=g.get("features") or {}
        shared=[k for k in FEATURES if k in factors and k in current_features
                and isinstance(factors[k],(int,float)) and isinstance(current_features[k],(int,float))]
        if not shared: continue
        distance=sum(max(0.0,float(weights.get(k,1.0)))*abs(factors[k]-current_features[k])
                     for k in shared)/max(1.0,sum(max(0.0,float(weights.get(k,1.0))) for k in shared))
        analogs.append({"game_id":g["game_id"],"game_utc":g["game_utc"],
                        "stat":g["stat"],"side":"OVER" if g["stat"]>line else "UNDER" if g["stat"]<line else "PUSH",
                        "distance":round(distance,5),"matched_features":shared,"source":g["source"],
                        "explanation_factors":g.get("explanation_factors",{}),
                        "context_missing":[k for k in FEATURES if k not in factors]})
    analogs.sort(key=lambda x:(x["distance"],x["game_utc"]))
    chosen=analogs[:analog_limit]
    return {"sport":sport,"player":player,"market":market,"line":line,"cutoff_utc":cutoff_utc,
            "windows":windows,"game_evidence":[{"game_id":g["game_id"],"stat":g["stat"],
                "side":"OVER" if g["stat"]>line else "UNDER" if g["stat"]<line else "PUSH",
                "source":g["source"],"explanation_factors":g.get("explanation_factors",{}),
                "explanation_status":"DOCUMENTED" if g.get("explanation_factors") else "NOT_VERIFIED"}
                for g in valid],
            "matched_analogs":chosen,
            "analog_sides":{s:sum(a["side"]==s for a in chosen) for s in ("OVER","UNDER","PUSH")},
            "warning":"Historical rates and analog similarity are not calibrated probabilities; missing context must not be inferred."}

def rank_scanned_props(props, top_n=6):
    """Require independent, validated, calibrated estimates and explicit payout threshold."""
    if top_n not in (2,6): raise ValueError("TOP_N_MUST_BE_2_OR_6")
    ranked=[]
    for p in props:
        if not p.get("calibration_verified") or not p.get("source_verified"): continue
        prob=p.get("calibrated_win_probability")
        break_even=p.get("break_even_probability")
        if not all(isinstance(x,(float,int)) and not isinstance(x,bool) and 0<=x<=1 for x in (prob,break_even)): continue
        if prob<=break_even: continue
        ranked.append(dict(p,edge=round(prob-break_even,6)))
    return sorted(ranked,key=lambda p:(-p["edge"],-p["calibrated_win_probability"]))[:top_n]
