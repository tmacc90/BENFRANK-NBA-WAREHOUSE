"""BENFRANK v4.4 full 5-on-5 possession sequencing prototype.

Runs ACTUAL sequential 5-on-5 possession trials with rotations, scoring,
shots, shooting fouls, rebounds, assists, steals, blocks, turnovers and optional
overtime. Requires sourced, complete two-team player and matchup profiles.
This is a SOURCE-GATED UNCALIBRATED simulator, not a certified NBA Digital Twon.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

MARKETS={"points","rebounds","assists","steals","blocks","turnovers","threes",
         "pra","pr","pa","ra","fantasy_score"}
COUNTS=("points","rebounds","assists","steals","blocks","turnovers","threes")
PROFILE_RATES=("fg2a_per36","fg3a_per36","fta_per36","ast_per36","reb_per36",
               "stl_per36","blk_per36","tov_per36")
PCTS=("fg2_pct","fg3_pct","ft_pct")
TEAM_RATES=("off_reb_probability","assist_probability",
            "block_on_missed_fg_probability","shooting_foul_probability")

def validate(context):
    if not isinstance(context,dict):
        raise ValueError("Context must be JSON object")
    required=("game_date","tipoff_utc","home","away","pace_per_team",
              "pace_source","pace_asof","rosters","team_rates")
    for field in required:
        if field not in context:
            raise ValueError("Missing context field "+field)
    dt.date.fromisoformat(context["game_date"])
    tipoff=dt.datetime.fromisoformat(str(context["tipoff_utc"]).replace("Z","+00:00"))
    if tipoff.tzinfo is None:
        raise ValueError("Tipoff must be timezone-aware")
    home,away=context["home"],context["away"]
    if not isinstance(home,str) or not isinstance(away,str) or home==away:
        raise ValueError("Two distinct teams are required")
    pace=context["pace_per_team"]
    if isinstance(pace,bool) or not isinstance(pace,(int,float)) or not 75<=pace<=125:
        raise ValueError("Expected pace must be 75..125 possessions/team")
    names=set()
    for team in (home,away):
        roster=context["rosters"].get(team)
        if not isinstance(roster,list) or not 7<=len(roster)<=15:
            raise ValueError("Need full 7-15 player rotation for "+team)
        minutes=[]
        for p in roster:
            name=p.get("player")
            if not isinstance(name,str) or not name.strip() or name in names:
                raise ValueError("Every player needs a unique name")
            names.add(name)
            if not p.get("source") or not p.get("asof"):
                raise ValueError("Player rate provenance required for "+name)
            observed=dt.datetime.fromisoformat(str(p["asof"]).replace("Z","+00:00"))
            if observed.tzinfo is None or observed>tipoff:
                raise ValueError("Player rate source must be pregame: "+name)
            m=p.get("minutes_target")
            if isinstance(m,bool) or not isinstance(m,int) or not 0<=m<=48:
                raise ValueError("Whole-minute 0..48 forecast required for "+name)
            minutes.append(m)
            for rate in PROFILE_RATES:
                v=p.get(rate)
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=50:
                    raise ValueError("Finite 0..50 rate required: "+name+" "+rate)
            for rate in PCTS:
                v=p.get(rate)
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1:
                    raise ValueError("Probability 0..1 required: "+name+" "+rate)
        if sum(minutes)!=240:
            raise ValueError(team+" projected regulation minutes must total exactly 240")
        rates=context["team_rates"].get(team)
        if not isinstance(rates,dict) or not rates.get("source") or not rates.get("asof"):
            raise ValueError("Team probabilities and provenance required: "+team)
        checked=dt.datetime.fromisoformat(str(rates["asof"]).replace("Z","+00:00"))
        if checked.tzinfo is None or checked>tipoff:
            raise ValueError("Team rate source must precede tipoff")
        for rate in TEAM_RATES:
            value=rates.get(rate)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
                raise ValueError("Team rate out of range: "+rate)
    if not context["pace_source"] or not context["pace_asof"]:
        raise ValueError("Pace must include provenance")
    checked=dt.datetime.fromisoformat(str(context["pace_asof"]).replace("Z","+00:00"))
    if checked.tzinfo is None or checked>tipoff:
        raise ValueError("Pace source must precede tipoff")
    return (home,away)

def schedule(roster):
    """Greedy feasible 48-minute, five-on-floor projection; all minute targets exact."""
    left={p["player"]:p["minutes_target"] for p in roster}
    out=[]
    for minute in range(48):
        slots=48-minute
        order=sorted(roster,key=lambda p:(left[p["player"]],p["minutes_target"]),reverse=True)
        selected=[p for p in order if left[p["player"]]>0][:5]
        if len(selected)!=5 or any(left[p["player"]]>slots for p in roster):
            raise ValueError("Projected minute schedule infeasible")
        out.append(tuple(p["player"] for p in selected))
        for p in selected:
            left[p["player"]]-=1
    if any(left.values()):
        raise ValueError("Projected minute schedule failed conservation")
    return out

def choose(rng,players,weight):
    weights=[max(0.0,weight(p)) for p in players]
    total=sum(weights)
    if total<=0:
        return rng.choice(players)
    needle=rng.random()*total
    for player,w in zip(players,weights):
        needle-=w
        if needle<0:
            return player
    return players[-1]

def starter_game_stats(context):
    return {p["player"]:{s:0 for s in COUNTS} | {"fouls":0,"minutes":0}
            for team in (context["home"],context["away"])
            for p in context["rosters"][team]}

def market_value(s,market):
    if market in COUNTS:
        return s[market]
    if market=="pra":
        return s["points"]+s["rebounds"]+s["assists"]
    if market=="pr":
        return s["points"]+s["rebounds"]
    if market=="pa":
        return s["points"]+s["assists"]
    if market=="ra":
        return s["rebounds"]+s["assists"]
    if market=="fantasy_score":
        return s["points"]+1.2*s["rebounds"]+1.5*s["assists"]+3*(s["steals"]+s["blocks"])-s["turnovers"]
    raise ValueError("Unsupported market "+str(market))

def simulate_game(context,seed,precomputed=None):
    home,away=validate(context) if precomputed is None else (context["home"],context["away"])
    rng=random.Random(seed)
    rosters={t:{p["player"]:p for p in context["rosters"][t]} for t in (home,away)}
    lineups=precomputed or {t:schedule(context["rosters"][t]) for t in (home,away)}
    stats=starter_game_stats(context)
    score={home:0,away:0}
    fouled_out=set()
    regulation_minute_totals={home:0,away:0}
    # Possession and playing time are explicitly conserved in regulation.
    total_possessions=2*round(context["pace_per_team"])
    observed_minutes=set()

    def players_on(team,minute,ot=False):
        # Foul-outs trigger a legal substitution without violating 5 players on court.
        planned=list(lineups[team][min(minute,47)]) if not ot else [
            p["player"] for p in sorted(context["rosters"][team],
                     key=lambda p:p["minutes_target"],reverse=True)[:5]]
        available=[p for p in planned if p not in fouled_out]
        if len(available)<5:
            extras=[p["player"] for p in sorted(context["rosters"][team],
                        key=lambda p:p["minutes_target"],reverse=True)
                    if p["player"] not in available and p["player"] not in fouled_out]
            available.extend(extras[:5-len(available)])
        if len(available)!=5:
            raise ValueError("Foul-out makes five-man lineup impossible")
        return [rosters[team][p] for p in available]

    def possession(off,defense,minute,ot=False):
        lineup_off=players_on(off,minute,ot)
        lineup_def=players_on(defense,minute,ot)
        # Historical expected team TOs divided by expected team possessions.
        expected_tov=sum(p["tov_per36"]*p["minutes_target"]/36 for p in context["rosters"][off])
        turnover_chance=min(0.35,expected_tov/context["pace_per_team"])
        if rng.random()<turnover_chance:
            ball=choose(rng,lineup_off,lambda p:p["tov_per36"])
            stats[ball["player"]]["turnovers"]+=1
            def_steals=sum(p["stl_per36"]*p["minutes_target"]/36 for p in context["rosters"][defense])
            conditional=min(0.95,(def_steals/context["pace_per_team"])/max(turnover_chance,0.01))
            if rng.random()<conditional:
                thief=choose(rng,lineup_def,lambda p:p["stl_per36"])
                stats[thief["player"]]["steals"]+=1
            return
        off_rates=context["team_rates"][off]
        def_rates=context["team_rates"][defense]
        # Maximum two shooting sequences with an offensive rebound continuation.
        for shot_number in range(2):
            shooter=choose(rng,lineup_off,lambda p:p["fg2a_per36"]+p["fg3a_per36"]+0.44*p["fta_per36"])
            shooter_name=shooter["player"]
            attempts=shooter["fg2a_per36"]+shooter["fg3a_per36"]
            three=bool(attempts and rng.random()<shooter["fg3a_per36"]/attempts)
            points=3 if three else 2
            if rng.random()<off_rates["shooting_foul_probability"]:
                # Shooting foul counts for player and team; sixth foul causes immediate substitution.
                defender=choose(rng,lineup_def,lambda p:1)
                stats[defender["player"]]["fouls"]+=1
                if stats[defender["player"]]["fouls"]>=6:
                    fouled_out.add(defender["player"])
                for _ in range(points):
                    if rng.random()<shooter["ft_pct"]:
                        stats[shooter_name]["points"]+=1
                        score[off]+=1
                return
            p_make=shooter["fg3_pct"] if three else shooter["fg2_pct"]
            if rng.random()<p_make:
                stats[shooter_name]["points"]+=points
                if three:
                    stats[shooter_name]["threes"]+=1
                score[off]+=points
                if rng.random()<off_rates["assist_probability"]:
                    teammates=[p for p in lineup_off if p["player"]!=shooter_name]
                    assister=choose(rng,teammates,lambda p:p["ast_per36"])
                    stats[assister["player"]]["assists"]+=1
                return
            if rng.random()<def_rates["block_on_missed_fg_probability"]:
                blocker=choose(rng,lineup_def,lambda p:p["blk_per36"])
                stats[blocker["player"]]["blocks"]+=1
            offensive_board=(rng.random()<off_rates["off_reb_probability"])
            board_team=lineup_off if offensive_board else lineup_def
            boarder=choose(rng,board_team,lambda p:p["reb_per36"])
            stats[boarder["player"]]["rebounds"]+=1
            if not offensive_board or shot_number==1:
                return

    def apply_minute(team,minute,ot=False):
        chosen=players_on(team,minute,ot)
        for p in chosen:
            stats[p["player"]]["minutes"]+=1
        if not ot:
            regulation_minute_totals[team]+=5

    # Attribute playing time in chronological order so foul-out substitutions
    # affect subsequent actual minutes, not just the possession lineup.
    last_minute=-1
    for i in range(total_possessions):
        minute=min(47,int(48*i/total_possessions))
        for elapsed in range(last_minute+1,minute+1):
            for team in (home,away):
                apply_minute(team,elapsed)
        last_minute=minute
        off,defense=(home,away) if i%2==0 else (away,home)
        possession(off,defense,minute)
    for elapsed in range(last_minute+1,48):
        for team in (home,away):
            apply_minute(team,elapsed)
    overtime_periods=0
    while score[home]==score[away] and overtime_periods<2:
        overtime_periods+=1
        for _ in range(5):
            for team in (home,away):
                apply_minute(team,47,ot=True)
        ot_possessions=2*max(6,round(context["pace_per_team"]*5/48))
        for i in range(ot_possessions):
            off,defense=(home,away) if i%2==0 else (away,home)
            possession(off,defense,47,ot=True)
    assert regulation_minute_totals=={home:240,away:240}
    return {"score":score,"stats":stats,"regulation_team_minutes":regulation_minute_totals,
            "possession_count_regulation":total_possessions,
            "overtime_periods":overtime_periods,
            "score_tied_after_max_2OT":score[home]==score[away]}

def trial_run(context,player,market,line,trials=25000,seed=42):
    validate(context)
    if not isinstance(player,str) or player not in {p["player"] for team in (context["home"],context["away"]) for p in context["rosters"][team]}:
        raise ValueError("Target player absent from full roster")
    if market not in MARKETS:
        raise ValueError("Unsupported market")
    if not isinstance(line,(float,int)) or isinstance(line,bool) or not math.isfinite(line):
        raise ValueError("Exact line must be finite")
    if not isinstance(trials,int) or not 1<=trials<=50000:
        raise ValueError("Trials must be 1..50000")
    lineups={t:schedule(context["rosters"][t]) for t in (context["home"],context["away"])}
    values=[]
    overtime=0
    for i in range(trials):
        result=simulate_game(context,seed+i*7919,precomputed=lineups)
        values.append(market_value(result["stats"][player],market))
        overtime+=bool(result["overtime_periods"])
    over=sum(x>line for x in values)
    under=sum(x<line for x in values)
    push=trials-over-under
    prob=over/trials
    margin=1.96*math.sqrt(prob*(1-prob)/trials)
    return {"method":"SOURCE_GATED_SEQUENTIAL_5_ON_5_UNCALIBRATED",
            "status":"EXECUTED_POSSESSION_TRIALS" if trials>=25000 else "EXECUTED_BELOW_25K",
            "game_date":context["game_date"],"player":player,"market":market,"exact_line":line,
            "trials_executed":trials,"seed":seed,
            "context_sha256":hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest(),
            "over_count":over,"under_count":under,"push_count":push,
            "mean":round(statistics.mean(values),4),
            "over_frequency_uncalibrated":round(prob,6),
            "under_frequency_uncalibrated":round(under/trials,6),
            "push_frequency_uncalibrated":round(push/trials,6),
            "over_monte_carlo_95pct_interval":[round(max(0,prob-margin),5),round(min(1,prob+margin),5)],
            "overtime_trial_count":overtime,
            "regulation_team_minutes":{context["home"]:240,context["away"]:240},
            "certification":"NOT_CERTIFIED",
            "ticket_authority":"NO_TICKET",
            "missing_validation":["Official roster / lineup provenance independent crosscheck",
                                  "Historical shot-attempt and foul calibration",
                                  "Defensive matchup / teammate substitution calibration",
                                  "Real possession play-by-play calibration and out-of-sample tests",
                                  "Independent model agreement and game-result settlement"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--context",required=True)
    p.add_argument("--player",required=True)
    p.add_argument("--market",required=True,choices=sorted(MARKETS))
    p.add_argument("--line",type=float,required=True)
    p.add_argument("--trials",type=int,default=25000)
    p.add_argument("--seed",type=int,default=42)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    context=json.loads(Path(a.context).read_text())
    result=trial_run(context,a.player,a.market,a.line,a.trials,a.seed)
    Path(a.output).write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    main()
