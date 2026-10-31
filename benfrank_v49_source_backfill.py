"""Backfill observed NBA shooting and rebound components from pinned ESPN boxscores.

This never changes the original games table. Every accepted secondary row must
agree with ALL seven original counting-stat fields and both shooting equations.
Unmatched or conflicting records remain NULL; no inferred stats are allowed.
"""
import argparse, collections, csv, datetime, hashlib, json, math, sqlite3, unicodedata
from pathlib import Path

from benfrank_v49_market_warehouse import init, EXTRA

TEAM={"GS":"GSW","NY":"NYK","SA":"SAS","NO":"NOP","UTAH":"UTA",
      "WSH":"WAS","PHO":"PHX","BRK":"BKN"}
EXTRA_SOURCE={"fgm":"field_goals_made","fga":"field_goals_attempted",
              "fg3a":"three_point_field_goals_attempted","ftm":"free_throws_made",
              "fta":"free_throws_attempted","oreb":"offensive_rebounds",
              "dreb":"defensive_rebounds"}
ORIGINAL={"pts":"points","reb":"rebounds","ast":"assists","stl":"steals",
          "blk":"blocks","tov":"turnovers","fg3m":"three_point_field_goals_made"}

def name_key(value):
    value=unicodedata.normalize("NFKD",str(value)).casefold()
    return "".join(x for x in value if x.isalnum() and not unicodedata.combining(x))

def name_tokens(value):
    tokens=[name_key(x) for x in str(value).split()]
    return tuple(sorted(tokens)) if len(tokens)>=2 and all(tokens) else ()

def team_key(value):
    value=str(value).upper()
    return TEAM.get(value,value)

def number(value):
    v=float(value)
    if not math.isfinite(v) or not 0<=v<=500:
        raise ValueError("INVALID_NUMERIC_SOURCE")
    return v

def source_index(spec):
    path=Path(spec["path"])
    raw_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    if raw_hash!=spec["sha256"]:
        raise ValueError("PINNED_ESPN_CSV_HASH_MISMATCH:"+path.name)
    exact=collections.defaultdict(list)
    permuted=collections.defaultdict(list)
    with path.open(newline="",encoding="utf-8-sig") as f:
        for number_row,row in enumerate(csv.DictReader(f),2):
            if (row["season"]!=str(spec["year"]) or row["season_type"]!="2"
                    or row["did_not_play"].lower()=="true"):
                continue
            date=datetime.date.fromisoformat(row["game_date"]).isoformat()
            base=(date,team_key(row["team_abbreviation"]))
            entry=(spec,number_row,row)
            exact[base+(name_key(row["athlete_display_name"]),)].append(entry)
            permuted[base+(name_tokens(row["athlete_display_name"]),)].append(entry)
    return exact,permuted

def backfill(conn,sources):
    conn.row_factory=sqlite3.Row
    init(conn)
    if conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
        raise ValueError("SOURCE_WAREHOUSE_SQLITE_INTEGRITY_FAILED")
    baseline=conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    source_exact=collections.defaultdict(list)
    source_permuted=collections.defaultdict(list)
    for spec in sources:
        exact,permuted=source_index(spec)
        for key,items in exact.items():source_exact[key].extend(items)
        for key,items in permuted.items():source_permuted[key].extend(items)
    tally=collections.Counter()
    samples=[]
    consumed=set()
    byseason=collections.defaultdict(collections.Counter)
    rows=conn.execute("SELECT * FROM games ORDER BY date,player,team").fetchall()
    for raw_game in rows:
        g=dict(raw_game)
        base=(g["date"],team_key(g["team"]))
        candidates=source_exact.get(base+(name_key(g["player"]),),[])
        method="EXACT"
        if not candidates:
            candidate_token=name_tokens(g["player"])
            candidates=source_permuted.get(base+(candidate_token,),[]) if candidate_token else []
            method="UNIQUE_NAME_TOKEN_PERMUTATION"
        if len(candidates)!=1:
            reason="MISSING_OR_AMBIGUOUS_PLAYER_IDENTITY"
            tally[reason]+=1;byseason[g["season"]][reason]+=1
            if len(samples)<60:samples.append({"player":g["player"],"date":g["date"],"reason":reason})
            continue
        spec,rownum,src=candidates[0]
        identity=(spec["sha256"],rownum)
        if identity in consumed:
            tally["DUPLICATE_ESPN_ROW"]+=1
            byseason[g["season"]]["DUPLICATE_ESPN_ROW"]+=1
            continue
        try:
            for field,espn_field in ORIGINAL.items():
                if abs(float(g[field])-number(src[espn_field]))>1e-8:
                    raise ValueError("ORIGINAL_OFFICIAL_VS_ESPN_"+field)
            values={field:number(src[remote]) for field,remote in EXTRA_SOURCE.items()}
            if (values["fgm"]>values["fga"] or values["fg3a"]>values["fga"]
                    or values["fgm"]<g["fg3m"] or values["fg3a"]<g["fg3m"]
                    or values["ftm"]>values["fta"]):
                raise ValueError("ATTEMPTS_LESS_THAN_MAKES")
            if abs(2*values["fgm"]+g["fg3m"]+values["ftm"]-g["pts"])>0.0001:
                raise ValueError("SHOOTING_COMPONENTS_DO_NOT_EQUAL_OFFICIAL_POINTS")
            if abs(values["oreb"]+values["dreb"]-g["reb"])>0.0001:
                raise ValueError("OFFENSIVE_PLUS_DEFENSIVE_REBOUNDS_MISMATCH")
            if not g["minutes"] or g["minutes"]<=0:
                raise ValueError("ZERO_MINUTE_GAME_UNVERIFIED")
        except (KeyError,TypeError,ValueError) as exc:
            reason="SOURCE_STAT_CONFLICT"
            tally[reason]+=1;byseason[g["season"]][reason]+=1
            if len(samples)<60:
                samples.append({"player":g["player"],"date":g["date"],"reason":str(exc)})
            continue
        k=(g["player"],g["date"],g["team"])
        earlier=conn.execute("SELECT * FROM market_boxscores WHERE player=? AND date=? AND team=?",k).fetchone()
        if earlier and any(earlier[field] is not None and earlier[field]!=values[field] for field in EXTRA):
            raise ValueError("REFUSING_TO_REPLACE_CONFLICTING_PRIOR_SHOOTING_EVIDENCE")
        conn.execute("INSERT OR REPLACE INTO market_boxscores VALUES ("+",".join("?" for _ in range(13))+")",
             (*k,*(values[field] for field in EXTRA),
              "ESPN:SportsDataverse:sha256:"+spec["sha256"],
              str(src["game_id"])+":"+str(src["athlete_id"]),spec["updated_at"]))
        consumed.add(identity)
        tally["SHOOTING_BOX_SCORES_CROSSCHECKED"]+=1
        byseason[g["season"]]["SHOOTING_BOX_SCORES_CROSSCHECKED"]+=1
        if method!="EXACT":tally["UNIQUE_REVERSED_NAME_MATCHES"]+=1
    conn.commit()
    if (conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok"
            or conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]!=baseline):
        raise ValueError("ORIGINAL_GAMES_INTEGRITY_OR_COUNT_CHANGED")
    return {"status":"ADD_ONLY_CROSS_SOURCE_SHOOTING_BACKFILL",
            "original_warehouse_game_rows":baseline,
            "expanded_shooting_rows":tally["SHOOTING_BOX_SCORES_CROSSCHECKED"],
            "unmatched_or_conflicted":baseline-tally["SHOOTING_BOX_SCORES_CROSSCHECKED"],
            "counts":dict(tally),"by_season":{s:dict(v) for s,v in byseason.items()},
            "source_hashes":[{"year":s["year"],"sha256":s["sha256"]} for s in sources],
            "original_games_unchanged":True,"prediction_certification":"NOT_CERTIFIED",
            "source_assurance":"ESPN_SECONDARY_MATCHED_TO_ORIGINAL_OFFICIAL_BOX_SCORES",
            "rejection_examples":samples}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True)
    p.add_argument("--source-dir",required=True)
    p.add_argument("--sources-json",default="sources.json")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    raw=json.loads(Path(args.sources_json).read_text())["sources"]
    sources=[]
    for spec in raw:
        if spec.get("kind")=="espn_box" and spec.get("year") in (2025,2026):
            sources.append({"path":str(Path(args.source_dir)/spec["name"]),
                            "year":spec["year"],"sha256":spec["sha256"],
                            "updated_at":spec["updated_at"]})
    if len(sources)!=2:
        raise ValueError("TWO_PINNED_ESPN_SEASONS_REQUIRED")
    c=sqlite3.connect(args.db)
    result=backfill(c,sources)
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("status","original_warehouse_game_rows",
                  "expanded_shooting_rows","unmatched_or_conflicted","counts")},indent=2))
if __name__=="__main__":
    main()
