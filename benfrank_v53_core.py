"""BENFRANK v5.3 additive core evidence report (research only).

Usage: python benfrank_v53_core.py --input source_backed_context.json --output report.json
Does not replace or alter the v5.2 simulator, Blind worker or frozen ledger.
"""
import argparse
import json
import math
import statistics
from pathlib import Path
from benfrank_v53_dna import coverage, conditional_dna, matchup_similarity

MARKET_DRIVERS = {
 "points":["minutes","fga","three_pa","fta","usage","shot_quality"],
 "rebounds":["minutes","rebound_chances","rebound_conversion","opponent_misses","center_absent"],
 "assists":["minutes","potential_assists","potential_conversion","touches","lead_guard_absent"],
 "threes":["minutes","three_pa","three_pct","shot_quality"],
 "steals":["minutes","opponent_possessions","steal_chances","steal_conversion"],
 "blocks":["minutes","opponent_rim_attempts","block_chances","block_conversion"],
 "pra":["minutes","fga","rebound_chances","potential_assists","usage"],
 "rebounds_assists":["minutes","rebound_chances","potential_assists"],
}
def finite(x):
 return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def report(context):
 board=context["prop"]; rows=context["historical_games"]; upcoming=context.get("upcoming_features",{})
 market=board["market"]; line=board["line"]; cutoff=board["cutoff"]
 if not finite(line): raise ValueError("INVALID_EXACT_LINE")
 if not board.get("player") or not board.get("opponent"): raise ValueError("PLAYER_OPPONENT_REQUIRED")
 # Active runner uses the same season hierarchy as the numerical engine.
 # Legacy coverage() remains available for archived report replay.
 from benfrank_dna_history import historical_windows
 translated=[dict(r,pts=r.get('points'),reb=r.get('rebounds'),ast=r.get('assists'),
                   stl=r.get('steals'),blk=r.get('blocks'),tov=r.get('turnovers'),fg3m=r.get('three_pm'))
             for r in rows if r.get('played') is True]
 names={'points_rebounds':'pr','points_assists':'pa','rebounds_assists':'ra'}
 cov=dict(windows=historical_windows(translated,names.get(market,market),line,cutoff,board['opponent']),
          career_coverage_note='AVAILABLE_ARCHIVE_ONLY')
 dna=conditional_dna(rows,market,line,cutoff,upcoming)
 analogues=matchup_similarity(rows,market,line,cutoff,upcoming)
 drivers={f:{"upcoming":upcoming.get(f),"status":"OBSERVED_INPUT" if finite(upcoming.get(f)) else "UNKNOWN"} for f in MARKET_DRIVERS.get(market,[])}
 scenario=[]
 for item in context.get("scenarios",[]):
  prob=item.get("prob_over");weight=item.get("weight")
  scenario.append({"name":item.get("name"),"prob_over":prob if finite(prob) and 0<=prob<=1 else None,
                   "weight":weight if finite(weight) and 0<=weight<=1 else None,
                   "weight_source":item.get("weight_source","ASSUMPTION"),
                   "minutes":item.get("minutes"),"opportunities":item.get("opportunities"),
                   "conversion":item.get("conversion")})
 model_outputs=context.get("model_outputs",{})
 return {"version":"BENFRANK_V53_CHALLENGER","status":"RESEARCH_ONLY_UNVALIDATED",
         "prop":board,"exact_line_coverage":cov,"dna_100_test_results":dna,
         "matchup_opportunity_drivers":drivers,"same_player_analogues":analogues,
         "peer_role_analogues":{"status":"NOT_CONNECTED","games":[]},
         "scenarios":scenario,"model_comparison":model_outputs,
         "opportunity_conversion_path":{"status":"NOT_ESTIMATED_UNLESS_SOURCE_BACKED"},
         "decision":{"side":model_outputs.get("primary_side"),"ticket":"NO_TICKET",
                     "reason":"NO_NEW_CERTIFICATION_OR_CALIBRATION_FROM_THIS_REPORT"},
         "integrity":{"historical_games_supplied":len(rows),"future_game_leakage_policy":"EXCLUDE_DATE_AT_OR_AFTER_CUTOFF",
                      "historical_lines_vs_today_threshold":"TODAYS_THRESHOLD_REPLAY_ONLY",
                      "source_note":"Historical rows and scenario inputs must be supplied from verified as-of sources"}}

def main():
 p=argparse.ArgumentParser();p.add_argument("--input",required=True);p.add_argument("--output",required=True)
 a=p.parse_args();context=json.loads(Path(a.input).read_text())
 result=report(context);out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
 if out.exists():raise FileExistsError("IMMUTABLE_REPORT_PATH_EXISTS")
 out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
if __name__=="__main__":main()
