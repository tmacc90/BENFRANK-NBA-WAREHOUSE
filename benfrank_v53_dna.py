"""BENFRANK v5.3 source-gated exact-line DNA and matchup similarity challenger.

Pure analysis layer: never edits frozen predictions or asserts betting calibration.
Rows are chronological real-game dictionaries with explicit stats and provenance.
"""
from __future__ import annotations
import math
import statistics
from collections import defaultdict

WINDOWS = (5, 10, 15, 20, 25, 32, 52)
FAMILIES = {
 "minutes_availability": ("minutes", "started", "rest_days", "fouls", "blowout", "injury_return", "rotation_role", "minutes_trend", "minutes_variance", "back_to_back"),
 "usage_role": ("usage", "touches", "possessions", "on_ball", "starter_usage", "bench_usage", "first_option", "second_unit", "star_absent", "usage_trend"),
 "shooting": ("fga", "fg_pct", "three_pa", "three_pct", "fta", "rim_fga", "midrange_fga", "paint_touches", "shot_quality", "self_created"),
 "rebounds": ("rebound_chances", "rebound_conversion", "contested_rebounds", "uncontested_rebounds", "oreb", "dreb", "opponent_misses", "rebound_share", "boxouts", "center_absent"),
 "assists": ("potential_assists", "potential_conversion", "passes", "touches", "secondary_assists", "drive_kicks", "teammate_fg", "potential_per_minute", "pick_roll", "lead_guard_absent"),
 "defense": ("opponent_positional_allowance", "opponent_def_rating", "opponent_pace", "rim_protection", "perimeter_coverage", "switch_rate", "opponent_rebound_rate", "opponent_assist_rate", "turnover_pressure", "opponent_foul_rate"),
 "lineup": ("top_scorer_active", "top_scorer_absent", "center_active", "center_absent", "lead_guard_active", "lead_guard_absent", "two_big", "small_ball", "starting_five", "teammate_on_off"),
 "environment": ("home", "favorite", "close_game", "blowout", "high_total", "low_total", "high_pace", "low_pace", "rest_days", "travel"),
 "exact_line": ("last5", "last10", "last15", "last20", "season", "previous_season", "career", "median", "tail", "streak"),
 "reliability": ("projection_error", "minutes_error", "usage_error", "opportunity_error", "conversion_error", "similar_matchup", "role_shift", "opposite_case", "blind_disagreement", "stress_reversal"),
}
assert sum(map(len, FAMILIES.values())) == 100

def value(row, market):
    parts = {"points": ("points",), "rebounds": ("rebounds",), "assists": ("assists",),
             "pra": ("points", "rebounds", "assists"), "rebounds_assists": ("rebounds", "assists"),
             "points_rebounds": ("points", "rebounds"), "points_assists": ("points", "assists"),
             "threes": ("three_pm",), "steals": ("steals",), "blocks": ("blocks",),
             "turnovers": ("turnovers",), "fantasy_score": ("points","rebounds","assists","steals","blocks","turnovers") }
    if market not in parts: raise ValueError("UNSUPPORTED_MARKET: " + market)
    if any(row.get(k) is None for k in parts[market]): return None
    if market=="fantasy_score":
        return (float(row["points"])+1.2*float(row["rebounds"])+1.5*float(row["assists"])+3*(float(row["steals"])+float(row["blocks"]))-float(row["turnovers"]))
    return sum(float(row[k]) for k in parts[market])

def coverage(rows, market, line, cutoff):
    """Exclude same-day and future outcomes; count only actual played games."""
    if not math.isfinite(float(line)): raise ValueError("INVALID_LINE")
    eligible = sorted((r for r in rows if r.get("date") and r["date"] < cutoff
                       and r.get("played") is True and value(r, market) is not None),
                      key=lambda r:(r["date"],str(r.get("game_id",""))))
    def summarize(group):
        vals = [value(r,market) for r in group]
        over=sum(v>line for v in vals); under=sum(v<line for v in vals); pushes=len(vals)-over-under
        return {"n":len(vals),"over":over,"under":under,"push":pushes,
                "over_rate_nonpush":over/(over+under) if over+under else None,
                "mean":statistics.mean(vals) if vals else None,
                "median":statistics.median(vals) if vals else None,
                "game_ids":[r.get("game_id") for r in group]}
    result={"line":line,"market":market,"cutoff":cutoff,"windows":{}}
    for n in WINDOWS: result["windows"]["L"+str(n)]=summarize(eligible[-n:])
    season=max((r.get("season","") for r in eligible),default="")
    previous=sorted(set(r.get("season","") for r in eligible if r.get("season")))[-2:-1]
    result["windows"]["current_season"]=summarize([r for r in eligible if season is not None and r.get("season")==season])
    result["windows"]["previous_season"]=summarize([r for r in eligible if r.get("season") in previous])
    result["windows"]["available_career"]=summarize(eligible)
    result["career_coverage_note"]="AVAILABLE_ARCHIVE_ONLY; full career not asserted"
    return result

def conditional_dna(rows, market, line, cutoff, upcoming, min_support=5):
    """100 predeclared tests; never invent a condition or a favorable result."""
    eligible=[r for r in rows if r.get("date","") < cutoff and r.get("played") is True and value(r,market) is not None]
    output=[]
    for family,features in FAMILIES.items():
        for feature in features:
            # A numeric/bool feature is testable only when observed in both past and upcoming.
            target=upcoming.get(feature)
            observed=[r for r in eligible if isinstance(r.get(feature),(int,float,bool)) and not isinstance(r.get(feature),str)]
            if not isinstance(target,(int,float,bool)) or len(observed)<min_support:
                output.append({"family":family,"test":feature,"status":"UNAVAILABLE","support":len(observed)})
                continue
            median=statistics.median(float(r[feature]) for r in observed)
            # Compare matched historical regime; do not infer causality.
            matching=[r for r in observed if (float(r[feature])>=median)==(float(target)>=median)]
            o=sum(value(r,market)>line for r in matching);u=sum(value(r,market)<line for r in matching)
            support=o+u
            direction="INSUFFICIENT" if support<min_support else ("OVER" if o>u else "UNDER" if u>o else "MIXED")
            output.append({"family":family,"test":feature,"status":direction,"support":support,
                           "over":o,"under":u,"threshold":median,"upcoming":target,
                           "game_ids":[r.get("game_id") for r in matching],
                           "caveat":"DESCRIPTIVE_ASSOCIATION_NOT_CAUSAL_OR_CALIBRATED"})
    return output

def matchup_similarity(rows, market, line, cutoff, upcoming, features=None, min_common=2, top_k=10):
    """Weighted nearest analogues with missing-feature exclusion and traceable games."""
    features=features or {"minutes":2.0,"usage":1.0,"pace":1.0,"opponent_positional_allowance":2.0,
                         "rebound_chances":1.5,"potential_assists":1.5,"opponent_def_rating":1.0}
    historical=[r for r in rows if r.get("date","")<cutoff and r.get("played") is True and value(r,market) is not None]
    spreads={}
    for f in features:
        vals=[float(r[f]) for r in historical if isinstance(r.get(f),(int,float))]
        spreads[f]=statistics.pstdev(vals) if len(vals)>1 else 0
    ranked=[]
    for r in historical:
        common=[f for f in features if isinstance(upcoming.get(f),(int,float)) and isinstance(r.get(f),(int,float)) and spreads[f]>0]
        if len(common)<min_common: continue
        distance=sum(features[f]*abs(float(upcoming[f])-float(r[f]))/spreads[f] for f in common)/sum(features[f] for f in common)
        ranked.append({"game_id":r.get("game_id"),"date":r.get("date"),"opponent":r.get("opponent"),
                       "stat":value(r,market),"side":"OVER" if value(r,market)>line else "UNDER" if value(r,market)<line else "PUSH",
                       "distance":round(distance,5),"features_used":common,"source":r.get("source")})
    ranked.sort(key=lambda x:(x["distance"],x["date"],str(x["game_id"])))
    selected=ranked[:top_k]
    return {"analogues":selected,"available":len(ranked),"over":sum(r["side"]=="OVER" for r in selected),
            "under":sum(r["side"]=="UNDER" for r in selected),"push":sum(r["side"]=="PUSH" for r in selected),
            "warning":"DESCRIPTIVE_SIMILARITY_ONLY; same-player and peer cohorts must be separated; no inferred probability"}
