#!/usr/bin/env python3
"""BENFRANK additive exact-line historical coverage reporter. Stdlib only.
Input CSV columns: date,player,season,opponent,points,rebounds,assists,blocks,steals,three_pointers_made
Optional: game_id, competition, minutes, role. Input must be verified before use.
Usage: python tools/exact_line_coverage.py --csv logs.csv --player "Tyrese Maxey" --market points --line 24.5 --current-season 2026-27 --last-season 2025-26 --out report.json
"""
import argparse,csv,datetime,json,pathlib,hashlib,collections
MARKETS={"points":("points",),"rebounds":("rebounds",),"assists":("assists",),"pra":("points","rebounds","assists"),"points_rebounds":("points","rebounds"),"blocks_steals":("blocks","steals"),"3ptm":("three_pointers_made",)}
def run(args):
    raw=pathlib.Path(args.csv).read_bytes()
    rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    games=[];seen=set();excluded=[]
    for r in rows:
        if r.get("player","").strip().casefold()!=args.player.casefold():continue
        if r.get("competition","NBA").strip().upper()!="NBA":
            excluded.append({"date":r.get("date"),"reason":"non-NBA competition"});continue
        try:
            day=datetime.date.fromisoformat(r["date"])
            if day>=datetime.date.fromisoformat(args.cutoff):continue
            value=sum(float(r[k]) for k in MARKETS[args.market])
            key=(r.get("game_id") or (r["date"]+"|"+r.get("opponent","")),r["player"])
            if key in seen:raise ValueError("duplicate player-game")
            seen.add(key)
            games.append({"date":day.isoformat(),"season":r["season"],"opponent":r.get("opponent",""),"value":value,"side":"OVER" if value>args.line else "UNDER" if value<args.line else "PUSH","game_id":r.get("game_id","")})
        except (KeyError,ValueError,TypeError) as e:
            excluded.append({"date":r.get("date"),"reason":str(e)})
    games.sort(key=lambda x:x["date"],reverse=True)
    def summary(items):
        c=collections.Counter(g["side"] for g in items);n=len(items)
        return {"games":n,"over":c["OVER"],"under":c["UNDER"],"push":c["PUSH"],"over_rate":round(c["OVER"]/n,4) if n else None,"under_rate":round(c["UNDER"]/n,4) if n else None,"status":"verified_input_required" if n else "no_games"}
    windows={("L"+str(n)):summary(games[:n]) for n in (5,10,15,20,25,52)}
    windows["current_season"]=summary([g for g in games if g["season"]==args.current_season])
    windows["last_season"]=summary([g for g in games if g["season"]==args.last_season])
    windows["career_available"]=summary(games)
    return {"framework":"BENFRANK additive exact-line coverage","player":args.player,"market":args.market,"line":args.line,"cutoff_exclusive":args.cutoff,"source_csv_sha256":hashlib.sha256(raw).hexdigest(),"source_status":"unverified_user_supplied_csv","windows":windows,"games":games,"excluded":excluded,"warning":"Career reflects available input, not guaranteed complete career. This report is descriptive history, not a forecast or simulation."}
def main():
    p=argparse.ArgumentParser();p.add_argument("--csv",required=True);p.add_argument("--player",required=True);p.add_argument("--market",choices=sorted(MARKETS),required=True);p.add_argument("--line",type=float,required=True);p.add_argument("--current-season",required=True);p.add_argument("--last-season",required=True);p.add_argument("--cutoff",required=True,help="YYYY-MM-DD; exclude this day and later");p.add_argument("--out",required=True)
    a=p.parse_args();result=run(a);pathlib.Path(a.out).write_text(json.dumps(result,indent=2)+"\n");print(json.dumps({"out":a.out,"games":len(result["games"]),"excluded":len(result["excluded"]),"windows":result["windows"]},indent=2))
if __name__=="__main__":main()
