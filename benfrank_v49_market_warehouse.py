"""Additive NBA box-score market extension; original games and archives unchanged.

Imports source-attributed market statistics (e.g. ESPN box scores or official
NBA reports) via CSV. Missing values remain NULL; no synthetic substitutions.
"""
import argparse
import csv
import datetime
import json
import math
import sqlite3

EXTRA=("fgm","fga","fg3a","ftm","fta","oreb","dreb")
MARKETS={
 "points":("pts",),"rebounds":("reb",),"assists":("ast",),
 "steals":("stl",),"blocks":("blk",),"turnovers":("tov",),
 "three_pointers_made":("fg3m",),"pra":("pts","reb","ast"),
 "rebounds_assists":("reb","ast"),"points_rebounds":("pts","reb"),
 "points_assists":("pts","ast"),"field_goals_made":("fgm",),
 "field_goals_attempted":("fga",),"three_pointers_attempted":("fg3a",),
 "two_pointers_made":("fgm","fg3m"),
 "two_pointers_attempted":("fga","fg3a"),
 "two_point_attempts":("fga","fg3a"),
 "two_point_made":("fgm","fg3m"),
 "free_throws_made":("ftm",),"free_throws_attempted":("fta",),
 "offensive_rebounds":("oreb",),"defensive_rebounds":("dreb",),
 "double_double":("pts","reb","ast","stl","blk"),
 "fantasy_score":("pts","reb","ast","stl","blk","tov")
}
DDL="""CREATE TABLE IF NOT EXISTS market_boxscores (
 player TEXT NOT NULL, date TEXT NOT NULL, team TEXT NOT NULL,
 fgm REAL, fga REAL, fg3a REAL, ftm REAL, fta REAL, oreb REAL, dreb REAL,
 source TEXT NOT NULL, source_event_id TEXT NOT NULL,
 captured_at_utc TEXT NOT NULL, PRIMARY KEY(player,date,team))"""
def init(c):
    c.execute(DDL)
    c.commit()
def stat(row,market):
    if market not in MARKETS:
        return None
    def v(k):
        try: return row[k]
        except (KeyError, IndexError): return None
    if any(v(k) is None for k in MARKETS[market]):
        return None
    if market=="fantasy_score":
        return v("pts")+1.2*v("reb")+1.5*v("ast")+3*(v("stl")+v("blk"))-v("tov")
    if market=="double_double":
        return int(sum(v(k)>=10 for k in ("pts","reb","ast","stl","blk"))>=2)
    if market in ("two_pointers_made","two_pointers_attempted","two_point_attempts","two_point_made"):
        a,b=MARKETS[market]
        return v(a)-v(b) if v(a)>=v(b) else None
    return sum(v(k) for k in MARKETS[market])
def import_csv(c,path):
    init(c)
    count=0
    with open(path,newline="",encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for k in ("player","date","team","source","source_event_id","captured_at_utc"):
                if not row.get(k):
                    raise ValueError("Missing provenance or identity: "+k)
            datetime.date.fromisoformat(row["date"])
            if not row["source"].startswith(("ESPN:","NBA_OFFICIAL:","VERIFIED:")):
                raise ValueError("Untrusted provenance")
            vals={k:(float(row[k]) if row.get(k) not in (None,"") else None) for k in EXTRA}
            if all(x is None for x in vals.values()):
                raise ValueError("No market stats supplied")
            if any(x is not None and (not math.isfinite(x) or x<0 or x>200) for x in vals.values()):
                raise ValueError("Invalid box score")
            for a,b in (("fgm","fga"),("fg3a","fga"),("ftm","fta")):
                if vals[a] is not None and vals[b] is not None and vals[a]>vals[b]:
                    raise ValueError("Stat attempts contradiction: "+a)
            key=(row["player"],row["date"],row["team"])
            c.row_factory=sqlite3.Row
            old=c.execute("SELECT * FROM market_boxscores WHERE player=? AND date=? AND team=?",key).fetchone()
            if old:
                for k in EXTRA:
                    if old[k] is not None and vals[k] is not None and abs(old[k]-vals[k])>1e-8:
                        raise ValueError("Conflicting evidence for "+str(key)+" "+k)
                    if vals[k] is None:
                        vals[k]=old[k]
            c.execute("INSERT OR REPLACE INTO market_boxscores VALUES ("+",".join("?" for _ in range(13))+")",
                      (*key,*(vals[k] for k in EXTRA),row["source"],row["source_event_id"],row["captured_at_utc"]))
            count+=1
    c.commit()
    return count
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--csv",required=True)
    args=p.parse_args()
    c=sqlite3.connect(args.db)
    print(json.dumps({"imported":import_csv(c,args.csv)}))
if __name__=="__main__":
    main()
