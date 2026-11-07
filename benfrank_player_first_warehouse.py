"""Player-first L52 evidence warehouse: raw multi-source capture + strict game-log import.

Use explicit player IDs and trusted per-game normalized JSON. Raw ESPN endpoint
capture is independent of normalization; never invent games from aggregate stats.
"""
import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from benfrank_interrogation_60 import QUESTIONS

ALLOWED_HOSTS = {"site.api.espn.com", "site.web.api.espn.com",
                 "www.basketball-reference.com", "www.nba.com",
                 "www.cbssports.com", "www.statmuse.com"}
MARKET_FIELDS = {"3PM": ("three_pm",), "PTS": ("points",),
                 "REB": ("rebounds",), "PTS_REB": ("points", "rebounds")}
WINDOWS = (5, 10, 15, 20, 25, 32, 52)

def connect(path):
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS raw_sources (
      sha256 TEXT PRIMARY KEY, url TEXT NOT NULL, retrieved_utc TEXT NOT NULL,
      payload BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS player_games (
      player_id TEXT NOT NULL, game_id TEXT NOT NULL, game_date TEXT NOT NULL,
      team TEXT NOT NULL, opponent TEXT NOT NULL, minutes REAL,
      points INTEGER, rebounds INTEGER, three_pm INTEGER,
      source_sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
      PRIMARY KEY(player_id,game_id,source_sha256));
    """)
    return db

def capture(db, url, timeout=20):
    host = urlparse(url).hostname
    if urlparse(url).scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError("UNAPPROVED_SOURCE_HOST")
    req = urllib.request.Request(url, headers={"User-Agent": "BENFRANK-Research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if urlparse(response.geturl()).hostname != host:
            raise ValueError("SOURCE_REDIRECT_CONFLICT")
        payload = response.read(5_000_001)
        if not payload or len(payload) > 5_000_000:
            raise ValueError("SOURCE_SIZE_INVALID")
    sha = hashlib.sha256(payload).hexdigest()
    db.execute("INSERT OR IGNORE INTO raw_sources VALUES(?,?,?,?)",
               (sha,url,dt.datetime.now(dt.timezone.utc).isoformat(),payload))
    db.commit()
    return sha

def ingest(db, records):
    for r in records:
        required = ("player_id","game_id","game_date","team","opponent",
                    "source_sha256","source_url")
        if any(not str(r.get(k,"")).strip() for k in required):
            raise ValueError("MISSING_GAME_IDENTITY_OR_PROVENANCE")
        dt.date.fromisoformat(r["game_date"])
        if not db.execute("SELECT 1 FROM raw_sources WHERE sha256=? AND url=?",
                          (r["source_sha256"],r["source_url"])).fetchone():
            raise ValueError("RAW_SOURCE_RECEIPT_MISSING")
        values = []
        for key in ("points","rebounds","three_pm"):
            v = r.get(key)
            if v is not None and (type(v) is not int or v < 0):
                raise ValueError("INVALID_COUNTING_STAT")
            values.append(v)
        db.execute("INSERT OR REPLACE INTO player_games VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (str(r["player_id"]),str(r["game_id"]),r["game_date"],
                    r["team"],r["opponent"],r.get("minutes"),
                    *values,r["source_sha256"],r["source_url"]))
    db.commit()

def l52(db, player_id, market, line, cutoff_date):
    if market not in MARKET_FIELDS:
        raise ValueError("UNSUPPORTED_MARKET")
    dt.date.fromisoformat(cutoff_date)
    rows = db.execute("""SELECT game_id,game_date,points,rebounds,three_pm,
                       COUNT(DISTINCT source_sha256) FROM player_games
                       WHERE player_id=? AND game_date<?
                       GROUP BY game_id ORDER BY game_date DESC,game_id DESC""",
                       (str(player_id),cutoff_date)).fetchall()
    # Reject conflicting values across sources, rather than silently preferring one.
    valid = []
    for game_id,date,*rest in rows:
        variants = db.execute("""SELECT DISTINCT points,rebounds,three_pm
            FROM player_games WHERE player_id=? AND game_id=?""",
            (str(player_id),game_id)).fetchall()
        if len(variants)!=1:
            continue
        stats = dict(zip(("points","rebounds","three_pm"),variants[0]))
        fields = MARKET_FIELDS[market]
        if any(stats[f] is None for f in fields):
            continue
        valid.append({"game_id":game_id,"date":date,
                      "value":sum(stats[f] for f in fields)})
        if len(valid)==52:
            break
    output = {}
    for n in WINDOWS:
        sample=valid[:n]
        output["L"+str(n)]={"available":len(sample),"requested":n,
            "over":sum(g["value"]>line for g in sample),
            "under":sum(g["value"]<line for g in sample),
            "push":sum(g["value"]==line for g in sample),
            "complete":len(sample)==n}
    return {"player_id":str(player_id),"market":market,"line":line,
            "cutoff_date":cutoff_date,"games":valid,"windows":output,
            "l52_complete":len(valid)==52,
            "note":"Coverage counts are historical frequencies, not calibrated forecasts."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--capture-url",action="append",default=[])
    p.add_argument("--ingest-json")
    p.add_argument("--player-id")
    p.add_argument("--market")
    p.add_argument("--line",type=float)
    p.add_argument("--cutoff-date")
    args=p.parse_args()
    db=connect(args.db)
    try:
        for url in args.capture_url:
            print(json.dumps({"url":url,"sha256":capture(db,url)}))
        if args.ingest_json:
            ingest(db,json.loads(Path(args.ingest_json).read_text()))
        if args.player_id:
            if args.market is None or args.line is None or not args.cutoff_date:
                p.error("--player-id requires --market --line --cutoff-date")
            print(json.dumps(l52(db,args.player_id,args.market,args.line,
                                  args.cutoff_date),indent=2))
    finally:
        db.close()
if __name__=="__main__":
    main()
