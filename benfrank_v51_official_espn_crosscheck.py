"""Source-independent verification: NBA CDN FINAL player stats vs ESPN FINAL.

This verifies past-game observations, not future roles, pregame lineups,
PrizePicks board authenticity, or calibrated forecasting accuracy.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path

FIELDS=("pts","reb","ast","stl","blk","tov","fg3m","fgm","fga","fg3a","ftm","fta")
ALIAS={"GS":"GSW","NY":"NYK","SA":"SAS","NO":"NOP","PHO":"PHX","WSH":"WAS","BRK":"BKN","UTAH":"UTA"}
def norm(value):
    decomposed=unicodedata.normalize("NFKD",str(value)).casefold()
    return "".join(c for c in decomposed if c.isalnum() and not unicodedata.combining(c))
def tokens(value):
    vals=[norm(x) for x in str(value).split()]
    return tuple(sorted(vals)) if len(vals)>=2 and all(vals) else None
def roster_key(row):
    team=ALIAS.get(row["team"],row["team"])
    date=row.get("game_date") if "game_date" in row else row["date"]
    return date,team
def match(official,espn):
    exact=collections.defaultdict(list)
    reordered=collections.defaultdict(list)
    for row in espn:
        key=roster_key(row)
        exact[key+(norm(row["player"]),)].append(row)
        tok=tokens(row["player"])
        if tok:reordered[key+(tok,)].append(row)
    matched=[];failures=[];seen=set()
    for raw in official:
        k=roster_key(raw)
        candidates=exact.get(k+(norm(raw["player"]),),[])
        method="EXACT_ACCENT_PUNCTUATION"
        if not candidates:
            tok=tokens(raw["player"])
            candidates=reordered.get(k+(tok,),[]) if tok else []
            method="UNIQUE_EXACT_NAME_TOKEN_ORDER"
        if len(candidates)!=1:
            failures.append({"nba_game_id":raw["game_id"],
                             "nba_person_id":raw["person_id"],
                             "player":raw["player"],"reason":"ESPN_IDENTITY_MISSING_OR_AMBIGUOUS"})
            continue
        candidate=candidates[0]
        identity=(candidate["player"],candidate["date"],candidate["team"])
        if identity in seen:
            failures.append({"nba_game_id":raw["game_id"],
                             "nba_person_id":raw["person_id"],
                             "reason":"ESPN_ROW_ALREADY_CONSUMED"})
            continue
        disagreements=[col for col in FIELDS if raw[col]!=candidate[col]]
        if (abs(float(raw["minutes"])-float(candidate["minutes"]))>1.05
                or raw["opponent"] != ALIAS.get(candidate["opponent"],candidate["opponent"])):
            disagreements.append("MINUTES_OR_OPPONENT")
        if disagreements:
            failures.append({"nba_game_id":raw["game_id"],
                             "nba_person_id":raw["person_id"],"player":raw["player"],
                             "reason":"COUNTING_STATS_DIFFER",
                             "fields":disagreements})
            continue
        seen.add(identity)
        matched.append({"nba_game_id":raw["game_id"],"nba_person_id":raw["person_id"],
                        "player":raw["player"],"game_date":raw["game_date"],
                        "team":raw["team"],"espn_event_id":candidate["source_game_id"],
                        "nba_box_sha256":raw["box_sha256"],
                        "espn_box_sha256":candidate["source_body_sha"],
                        "identity_method":method})
    return matched,failures
def inspect(nba_db,espn_db,out):
    nba_path=Path(nba_db).resolve();espn_path=Path(espn_db).resolve()
    with sqlite3.connect("file:"+str(nba_path)+"?mode=ro",uri=True) as nc:
        nc.row_factory=sqlite3.Row
        if nc.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("NBA_SOURCE_INTEGRITY_FAILURE")
        official=[dict(x) for x in nc.execute("SELECT * FROM nba_official_completed")]
    with sqlite3.connect("file:"+str(espn_path)+"?mode=ro",uri=True) as ec:
        ec.row_factory=sqlite3.Row
        if ec.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("ESPN_SOURCE_INTEGRITY_FAILURE")
        secondary=[dict(x) for x in ec.execute("SELECT * FROM current_games")]
    matched,failed=match(official,secondary)
    counts=collections.Counter(x["reason"] for x in failed)
    evidence={"status":"TWO_SOURCE_FINAL_GAME_RECONCILIATION" if matched else "BLOCKED_NO_FINAL_CROSS_SOURCE_MATCHES",
              "official_nba_player_games":len(official),"espn_player_games":len(secondary),
              "independently_crosschecked_player_games":len(matched),
              "discrepancy_counts":dict(counts),"discrepancy_examples":failed[:75],
              "matches":matched,
              "nba_db_sha256":hashlib.sha256(nba_path.read_bytes()).hexdigest(),
              "espn_db_sha256":hashlib.sha256(espn_path.read_bytes()).hexdigest(),
              "scope":"ALREADY_FINISHED_NBA_PLAYER_GAME_BOXES_ONLY",
              "pregame_lineups_verified":False,
              "historical_prop_lines_native_verified":False,
              "simulation_calibrated":False,
              "prediction_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    p=Path(out);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(evidence,indent=2)+"\n")
    return evidence
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--nba-db",required=True)
    p.add_argument("--espn-db",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    r=inspect(args.nba_db,args.espn_db,args.out)
    print(json.dumps({k:r[k] for k in
       ("status","official_nba_player_games","espn_player_games",
        "independently_crosschecked_player_games","discrepancy_counts")},indent=2))
    return 0 if r["independently_crosschecked_player_games"]>0 else 2
if __name__=="__main__":
    raise SystemExit(main())
