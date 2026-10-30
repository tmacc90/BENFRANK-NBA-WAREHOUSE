"""Staging-only player shot-attempt receipts from ESPN box score strings."""
def parse_attempts(fg,threes,ft,points):
    def pair(raw):
        pieces=str(raw).split("-")
        if len(pieces)!=2: raise ValueError("Invalid made-attempted format")
        m,a=map(int,pieces)
        if not 0<=m<=a<=80: raise ValueError("Invalid shot counts")
        return m,a
    fgm,fga=pair(fg)
    fg3m,fg3a=pair(threes)
    ftm,fta=pair(ft)
    fg2m=fgm-fg3m
    fg2a=fga-fg3a
    if fg2m<0 or fg2a<0 or fg2m>fg2a:
        raise ValueError("Three-point counts inconsistent with all field goals")
    if 2*fg2m+3*fg3m+ftm!=int(float(points)):
        raise ValueError("Points do not match shot scoring ledger")
    return {"fgm":fgm,"fga":fga,"fg2m":fg2m,"fg2a":fg2a,
            "fg3m":fg3m,"fg3a":fg3a,"ftm":ftm,"fta":fta}

SCHEMA="""CREATE TABLE IF NOT EXISTS player_shot_attempts (
    game_id TEXT NOT NULL, game_date TEXT NOT NULL, team TEXT NOT NULL,
    player TEXT NOT NULL, source TEXT NOT NULL,
    fga INTEGER, fgm INTEGER, fg2a INTEGER, fg2m INTEGER,
    fg3a INTEGER, fg3m INTEGER, fta INTEGER, ftm INTEGER,
    minutes REAL, source_sha256 TEXT NOT NULL, observed_at TEXT NOT NULL,
    verified_official INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(game_id,team,player,source)
);"""

def stage_attempts(conn,rows):
    conn.execute(SCHEMA)
    added=0
    rejected=0
    fields=("source_game_id","date","team","player","fga","fgm","fg2a","fg2m",
            "fg3a","fg3m","fta","ftm","minutes","source_body_sha","retrieved_at")
    for row in rows:
        if any(row.get(x) is None for x in fields):
            rejected+=1
            continue
        data=(row["source_game_id"],row["date"],row["team"],row["player"],
              "ESPN_SECONDARY",row["fga"],row["fgm"],row["fg2a"],row["fg2m"],
              row["fg3a"],row["fg3m"],row["fta"],row["ftm"],row["minutes"],
              row["source_body_sha"],row["retrieved_at"])
        c=conn.execute("""INSERT OR IGNORE INTO player_shot_attempts
        (game_id,game_date,team,player,source,fga,fgm,fg2a,fg2m,
         fg3a,fg3m,fta,ftm,minutes,source_sha256,observed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",data)
        added+=c.rowcount
    conn.commit()
    return {"staged":added,"missing_or_invalid":rejected,
            "authority":"ESPN_SECONDARY","official_verified":0,
            "promoted_to_games":0}
