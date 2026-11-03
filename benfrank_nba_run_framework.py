"""BENFRANK NBA MLB-MIRROR report layer. Real sourced game logs only.
Run: python benfrank_nba_run_framework.py --input props.json --output report.json
Input: {"cutoff_utc":"...Z","props":[{"player":"...","market":"points",
"line":20.5,"current_season":"2026-27","previous_season":"2025-26",
"games":[{"sport":"NBA","player":"...","market":"points","stat":22,
"game_utc":"...Z","game_id":"...","source":"https://...","season":"2026-27"}]}]}
No simulations, calibrated probabilities or opponent effects are invented.
"""
import argparse
import json
from pathlib import Path
from benfrank_exact_line_evidence import analyze_exact_line

def analyze(board):
    cutoff=board["cutoff_utc"]
    out=[]
    for prop in board["props"]:
        player,market,line=prop["player"],prop["market"],prop["line"]
        evidence=analyze_exact_line(sport="NBA",player=player,market=market,
            line=line,games=prop["games"],cutoff_utc=cutoff,
            current_season=prop["current_season"],previous_season=prop["previous_season"],
            current_features=prop.get("current_features"))
        w=evidence["windows"]
        recent=w["L10"]
        over,under=recent["over"],recent["under"]
        side="OVER" if over>=under else "UNDER"
        if over==under:
            career=w["career"]
            side="OVER" if career["over"]>=career["under"] else "UNDER"
        if recent["n"]==0:
            side=None
        ladder=[]
        for offset in (-1.0,-0.5,0,0.5,1.0):
            test_line=line+offset
            stats=[g["stat"] for g in evidence["game_evidence"][:20]]
            ladder.append({"line":round(test_line,3),"n":len(stats),
                "over":sum(s>test_line for s in stats),
                "under":sum(s<test_line for s in stats),
                "push":sum(s==test_line for s in stats)})
        risks=[]
        if recent["n"]<10: risks.append("THIN_L10_HISTORY")
        if not prop.get("projected_minutes_source"): risks.append("MINUTES_NOT_VERIFIED")
        if not prop.get("injury_source"): risks.append("INJURY_STATUS_NOT_VERIFIED")
        if not prop.get("matchup_source"): risks.append("MATCHUP_NOT_VERIFIED")
        out.append({"player":player,"market":market,"line":line,"side":side,
            "classification":"HISTORICAL_LEAN_ONLY","cutoff_utc":cutoff,
            "windows":w,"sensitivity":ladder,"analogs":evidence["matched_analogs"],
            "game_evidence":evidence["game_evidence"],"risks":risks,
            "blind_ai":"NOT_EXECUTED","sequential_simulations":"NOT_EXECUTED",
            "calibrated_probability":None,"certified":False})
    return {"framework":"BENFRANK_NBA_MLB_MIRROR_BETA_1","results":out,
        "warning":"Historical coverage is not a prediction probability. Sides are provisional and not certified."}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    board=json.loads(Path(args.input).read_text())
    report=analyze(board)
    target=Path(args.output)
    if target.exists(): raise FileExistsError("IMMUTABLE_REPORT_EXISTS")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2)+"\n")
    for p in report["results"]:
        print(f"📊 {p['player']} | {p['market']} {p['line']} | {p['side'] or 'INSUFFICIENT DATA'}")
        for key in ("L5","L10","L15","L20","current_season","previous_season","career"):
            w=p["windows"][key]
            print(f"  {key}: OVER {w['over']} / UNDER {w['under']} / PUSH {w['push']} (n={w['n']})")
        print("  ⚠️",", ".join(p["risks"]) or "No listed context gaps")
    return 0

if __name__=="__main__": raise SystemExit(main())
