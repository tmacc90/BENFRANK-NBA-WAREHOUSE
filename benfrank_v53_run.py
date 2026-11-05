"""Run existing v5.2 physical forecasts, then append source-gated v5.3 DNA reports.

No replacement of v5.2 receipts or prediction ledger. Immutable v5.3 companion
files are written only for successfully completed v5.2 predictions.
"""
import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from benfrank_v53_core import report
from acquire_history import name_key

ALIASES={"pts":"points","reb":"rebounds","ast":"assists","3pm":"threes",
         "points_rebounds_assists":"pra","rebounds_plus_assists":"rebounds_assists",
         "pr":"points_rebounds","pa":"points_assists","ra":"rebounds_assists"}
COLUMNS={"points":("points","pts"),"rebounds":("rebounds","reb"),"assists":("assists","ast"),
         "three_pm":("three_pm","fg3m","threes_made"),"steals":("steals","stl"),
         "blocks":("blocks","blk"),"turnovers":("turnovers","tov")}
def pick(row,*keys):
 for k in keys:
  if k in row and row[k] is not None:return row[k]
 return None
def load_games(db,player,cutoff):
 conn=sqlite3.connect("file:"+str(Path(db).resolve())+"?mode=ro",uri=True)
 try:
  conn.row_factory=sqlite3.Row
  columns={r[1] for r in conn.execute("PRAGMA table_info(games)")}
  if not {"player","date"}.issubset(columns):raise ValueError("WAREHOUSE_GAMES_SCHEMA_MISSING_PLAYER_OR_DATE")
  data=[dict(r) for r in conn.execute("SELECT * FROM games WHERE date < ? ORDER BY date",(cutoff,))]
 finally:conn.close()
 output=[]
 for r in data:
  if name_key(str(r["player"]))!=name_key(player):continue
  game={"date":r["date"],"game_id":pick(r,"game_id","id"),"season":r.get("season"),
        "opponent":pick(r,"opponent","opp"),"source":pick(r,"source","source_url"),
        "played":bool((pick(r,"minutes","min") or 0)>0)}
  for target,aliases in COLUMNS.items():game[target]=pick(r,*aliases)
  for f in ("minutes","usage","pace","rebound_chances","potential_assists","opponent_positional_allowance",
            "opponent_def_rating","fga","three_pa","fta","touches"):
   if f in r:game[f]=r[f]
  if game["played"] and not game.get("game_id"):
   game["game_id"]=str(r["date"])+"|"+str(r.get("team",""))+"|"+str(r["player"])
  output.append(game)
 return output

def run(config,output):
 root=Path(output)
 if root.exists():raise FileExistsError("IMMUTABLE_RUN_DIRECTORY_EXISTS")
 root.mkdir(parents=True)
 original=subprocess.run([sys.executable,str(Path(__file__).with_name("benfrank_v52_pipeline.py")),
                           "--config",str(config),"--output",str(root/"v52")],check=False)
 config_data=json.loads(Path(config).read_text())
 board=json.loads(Path(config_data["board"]).read_text())
 out=root/"v53";out.mkdir()
 summary=[]
 for prop in board:
  snapshot=prop["snapshot_id"];source=root/"v52"/"results"/(snapshot+".json")
  if not source.exists():
   summary.append({"snapshot_id":snapshot,"status":"BLOCKED_V52","reason":"NO_V52_RECEIPT"});continue
  try:
   frozen=json.loads(source.read_text())
   market=ALIASES.get(prop["market"],prop["market"])
   historical=load_games(config_data["history_db"],prop["player"],prop["game_date"])
   context={"prop":{"player":prop["player"],"opponent":prop["opponent"],"market":market,
                    "line":prop["line"],"cutoff":prop["game_date"],"snapshot_id":snapshot,
                    "analysis_cutoff_utc":frozen.get("analysis_cutoff_utc")},
            "historical_games":historical,"upcoming_features":{},
            "model_outputs":{"primary_side":frozen["direction"],
                             "primary_mean":frozen["main_simulation"].get("mean"),
                             "primary_raw_p_over":frozen["main_simulation"].get("p_over_raw"),
                             "blind_projection":frozen["blind_model"].get("projection"),
                             "blind_side":frozen.get("blind_direction"),
                             "scenario_reversal":frozen.get("scenario_side_flip"),
                             "trials_executed":frozen["main_simulation"].get("trials_executed")}}
   result=report(context)
   result["source_v52_receipt"]=str(source)
   result["missing_evidence"]=["UPCOMING_POSITIONAL_TRACKING_AND_PEER_ANALOGUES_NOT_YET_CONNECTED",
      "NO_ASOF_OPPORTUNITY_TRACKING_IN_LEGACY_GAMES_TABLE"]
   path=out/(snapshot+".json")
   with path.open("x") as handle:json.dump(result,handle,indent=2)
   summary.append({"snapshot_id":snapshot,"status":"V53_COMPANION_CREATED",
                   "direction":frozen["direction"],"historical_n":len(historical),
                   "dna_tests":len(result["dna_100_test_results"]),
                   "peer_analogues":"NOT_CONNECTED"})
  except Exception as e:summary.append({"snapshot_id":snapshot,"status":"V53_BLOCKED","exact_blocker":type(e).__name__+": "+str(e)})
 with (out/"comparison.json").open("x") as handle:json.dump({"v52_exit_code":original.returncode,"results":summary},handle,indent=2)
 return 0 if original.returncode==0 and all(x["status"]=="V53_COMPANION_CREATED" for x in summary) else 2

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--output",required=True)
 a=p.parse_args();raise SystemExit(run(a.config,a.output))
