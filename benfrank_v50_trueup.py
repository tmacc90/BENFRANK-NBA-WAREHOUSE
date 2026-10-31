"""Evidence-labelled NBA prop true-up using only previous completed games.

No source row dated on/after the target game is eligible, including when this
script runs after tipoff. Historical game database is read-only. The compact
model below is an empirical-Bayes challenger, NOT calibrated ticket authority.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import sqlite3
import statistics
import unicodedata
from pathlib import Path

from benfrank_v49_market_warehouse import stat as market_stat, MARKETS

def norm(name):
    txt=unicodedata.normalize("NFKD",str(name)).casefold()
    return "".join(x for x in txt if x.isalnum() and not unicodedata.combining(x))
def open_ro(path):
    p=Path(path).resolve()
    if not p.is_file():raise FileNotFoundError(p)
    conn=sqlite3.connect("file:"+str(p)+"?mode=ro",uri=True)
    conn.row_factory=sqlite3.Row
    return conn
def load_history(conn, cut):
    has_extra=bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_boxscores'").fetchone())
    extra=",b.fgm,b.fga,b.fg3a,b.ftm,b.fta,b.oreb,b.dreb" if has_extra else ""
    join=" LEFT JOIN market_boxscores b ON g.player=b.player AND g.date=b.date AND g.team=b.team" if has_extra else ""
    q="SELECT g.*"+extra+" FROM games g"+join+" WHERE g.date<? ORDER BY g.date"
    return [dict(row) for row in conn.execute(q,(cut,))]
def load_current(conn, cut):
    # Explicit cutoff enforced even if downloaded source itself contains later games.
    return [dict(r) for r in conn.execute("SELECT * FROM current_games WHERE date<? ORDER BY date",(cut,))]
def mean(values):
    return statistics.mean(values) if values else None
def opponent_modifier(current,opponent,market):
    if market in ("rebounds","assists","rebounds_assists","offensive_rebounds","defensive_rebounds"):
        return 1.0,0
    grouped=collections.defaultdict(list)
    for r in current:
        grouped[(r["source_game_id"],r["team"])].append(r)
    per_team={}
    for (game_id,team),values in grouped.items():
        # Exclude partial team summaries. 240 full regulation player minutes,
        # less for sparse/missing source data; overtime may exceed 240.
        minutes_total=sum(r["minutes"] for r in values)
        if minutes_total<235 or minutes_total>300 or len(values)<7:
            continue
        per_team[(game_id,team)]={"points":sum(r["pts"] for r in values),
                                "opponent":values[0]["opponent"]}
    league=[x["points"] for x in per_team.values()]
    if len(league)<20:return 1.0,0
    allowed=[]
    for (gid,tm),value in per_team.items():
        if tm==opponent:
            other=per_team.get((gid,value["opponent"]))
            if other:allowed.append(other["points"])
    if len(allowed)<2:return 1.0,len(allowed)
    league_mean=mean(league)
    if league_mean is None or league_mean<=0:return 1.0,len(allowed)
    relative=mean(allowed)/league_mean-1
    # Source small-sample and strong selection effects => heavily shrunk,
    # capped at 5% even when the original sample is extreme.
    signal=max(-0.15,min(0.15,relative))
    adjusted=max(-0.05,min(0.05,signal*len(allowed)/(len(allowed)+7)))
    return 1+adjusted,len(allowed)
def select_player(rows,name,market,limit=25):
    vals=[]
    for r in reversed(rows):
        if norm(r["player"])!=norm(name):continue
        if not r["minutes"] or r["minutes"]<3:continue
        value=market_stat(r,market)
        if value is None or not math.isfinite(float(value)):continue
        vals.append((r,float(value)))
        if len(vals)==limit:break
    return vals
def trueup(board,historical,current,target_date):
    dt.date.fromisoformat(target_date)
    if any(r["date"]>=target_date for r in historical):
        raise ValueError("HISTORICAL_ROW_AFTER_ASOF_CUTOFF")
    if any(r["date"]>=target_date for r in current):
        raise ValueError("CURRENT_ROW_AFTER_ASOF_CUTOFF")
    result=[]
    for entry in board:
        player=entry["player"];market=entry["market"];line=float(entry["line"])
        old=entry.get("now") or {}
        prior_prediction=old.get("projection")
        old_side=old.get("direction")
        h=select_player(historical,player,market,25)
        c=select_player(current,player,market,12)
        item={"id":entry.get("id"),"player":player,"market":market,
              "line":line,"opponent":entry["opponent"],
              "prior_projection":prior_prediction,"prior_direction":old_side,
              "historical_games_eligible":len(h),"current_2026_27_games_eligible":len(c),
              "new_projection":None,"new_direction":None,
              "ticket_authority":"NO_TICKET","model_certification":"NOT_CERTIFIED",
              "method":"EMPIRICAL_BAYES_RATE_PLUS_MINUTES_WITH_LIMITED_OPPONENT_CONTEXT",
              "game_cutoff_exclusive":target_date}
        if prior_prediction is None:
            item["status"]="BLOCKED_MISSING_PREVIOUS_BASELINE"
        elif not h:
            item["status"]="HISTORICAL_BASELINE_ONLY_NO_MATCHED_GAME_RATES"
            item["new_projection"]=prior_prediction
        elif not c:
            item["status"]="NO_NEW_SEASON_PLAYER_HISTORY_KEEP_BASELINE"
            item["new_projection"]=prior_prediction
        else:
            h_minutes=sum(r["minutes"] for r,_ in h)
            h_rate=sum(x for _,x in h)/h_minutes
            recent=c[:8]
            c_minutes=sum(r["minutes"] for r,_ in recent)
            c_rate=(sum(x for _,x in recent)/c_minutes) if c_minutes else 0
            h_mins_recent=mean([r["minutes"] for r,_ in h[:10]]) or 0
            c_mins_recent=mean([r["minutes"] for r,_ in recent[:5]]) or 0
            n=len(recent)
            # A roughly six-game exposure prior prevents a single current game
            # from replacing 2024-26 ability, while recent minutes get extra weight.
            prior_minutes=6*max(1,h_mins_recent)
            blended_rate=(h_rate*prior_minutes+sum(v for _,v in recent))/(prior_minutes+c_minutes)
            projected_minutes=(h_mins_recent*4+n*c_mins_recent)/(4+n)
            projected_minutes=max(0,min(42,projected_minutes))
            # Center on previous valid exact-line independent baseline, then
            # adjust rate and current role. Neither player line nor outcome used.
            rate_ratio=(blended_rate/h_rate) if h_rate>0 else 1.0
            role_ratio=(projected_minutes/h_mins_recent) if h_mins_recent>0 else 1.0
            m,ngames=opponent_modifier(current,entry["opponent"],market)
            proposal=float(prior_prediction)*max(0.5,min(1.7,rate_ratio))*max(0.5,min(1.6,role_ratio))*m
            item.update(new_projection=round(max(0,proposal),3),
                        historical_minutes_per_game=round(h_mins_recent,2),
                        current_minutes_per_game=round(c_mins_recent,2),
                        implied_minutes=round(projected_minutes,2),
                        current_stat_per_minute=round(c_rate,4),
                        historical_stat_per_minute=round(h_rate,4),
                        blended_stat_per_minute=round(blended_rate,4),
                        opponent_factor=round(m,4),
                        opponent_validated_games=ngames,
                        status="EXECUTED_CURRENT_SEASON_SHRUNK_RATE_AND_ROLE_TRUEUP")
        if item["new_projection"] is not None:
            value=float(item["new_projection"])
            item["new_direction"]="OVER" if value>line else "UNDER" if value<line else "AT_LINE"
            item["delta_vs_prior"]=round(value-float(prior_prediction),3)
            item["direction_changed"]=item["new_direction"]!=item["prior_direction"]
        else:
            item["direction_changed"]=False
        result.append(item)
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--board",required=True)
    p.add_argument("--historical-db",required=True)
    p.add_argument("--current-db",required=True)
    p.add_argument("--target-date",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    raw=json.loads(Path(a.board).read_text())
    board=raw.get("props") if isinstance(raw,dict) else raw
    if not isinstance(board,list) or not board:
        raise ValueError("NONEMPTY_BOARD_REQUIRED")
    with __import__('contextlib').closing(open_ro(a.historical_db)) as h:
        history=load_history(h,a.target_date)
    with __import__('contextlib').closing(open_ro(a.current_db)) as c:
        latest=load_current(c,a.target_date)
    rows=trueup(board,history,latest,a.target_date)
    report={"framework":"BENFRANK NBA v5.0 source-backed as-of true-up",
      "source_game_cutoff_exclusive":a.target_date,
      "forecast_provenance":"RETROSPECTIVE_ASOF_RECONSTRUCTION_NOT_ISSUED_PREGAME",
      "current_source":"ESPN_SECONDARY_NOT_OFFICIAL_CERTIFIED",
      "model_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET",
      "current_player_game_rows":len(latest),
      "matched_current_props":sum(r["current_2026_27_games_eligible"]>0 for r in rows),
      "changed_directions":sum(r.get("direction_changed") is True for r in rows),
      "n_props":len(rows),
      "historical_db_sha256":hashlib.sha256(Path(a.historical_db).read_bytes()).hexdigest(),
      "current_db_sha256":hashlib.sha256(Path(a.current_db).read_bytes()).hexdigest(),
      "props":rows}
    out=Path(a.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:report[k] for k in
       ("n_props","matched_current_props","changed_directions","current_player_game_rows")},indent=2))
if __name__=="__main__":
    main()
