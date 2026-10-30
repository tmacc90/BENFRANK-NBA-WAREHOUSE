"""Execute blind ML in a separate process using ONLY historical pregame features.

Primary model output, opponent, prop line and even player identity never enter
the worker payload. Requires at least 45 eligible player games. Model remains
uncalibrated; this is not a production-certified independent AI.
"""
import datetime as dt
import json
import math
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from engine import stat, MARKETS

WORKER=Path(__file__).with_name("benfrank_v44_blind_worker.py")

def features(history,market):
    if len(history)<20:
        raise ValueError("At least 20 earlier games needed for features")
    def mean_stat(rows):
        return sum(float(stat(r,market)) for r in rows)/len(rows)
    def mean_mins(rows):
        return sum(float(r["minutes"]) for r in rows)/len(rows)
    last5=history[-5:]
    last10=history[-10:]
    last20=history[-20:]
    return [mean_stat(last5),mean_stat(last10),mean_stat(last20),
            mean_mins(last10),mean_stat(last5)-mean_stat(last20)]

def worker_input(rows,market):
    if market not in MARKETS:
        raise ValueError("Unsupported existing market")
    clean=[r for r in rows if r["minutes"] is not None and r["minutes"]>=8]
    if len(clean)<45:
        raise ValueError("At least 45 historical appearances with >=8 minutes required")
    train=[{"x":features(clean[:i],market),"y":float(stat(clean[i],market))}
           for i in range(20,len(clean))]
    return {"train":train,"candidate":features(clean,market),"ridge":0.15}

def run_separate(conn,player,market,asof,timeout=30):
    dt.date.fromisoformat(asof)
    # The worker is never given date, player, opponent or line.
    history=conn.execute("SELECT * FROM games WHERE lower(player)=lower(?) AND date<? "
                         "ORDER BY date ASC,team ASC",(player,asof)).fetchall()
    try:
        payload=worker_input(history,market)
    except ValueError as exc:
        return {"status":"BLOCKED","reason":str(exc),"training_n":0,
                "certification":"NOT_VALIDATED_OR_CALIBRATED"}
    serialized=json.dumps(payload,allow_nan=False)
    with tempfile.TemporaryDirectory(prefix="benfrank-blind-worker-") as tmp:
        try:
            result=subprocess.run([sys.executable,"-I",str(WORKER.resolve())],
                                  input=serialized,text=True,capture_output=True,
                                  cwd=tmp,timeout=timeout,check=False)
        except subprocess.TimeoutExpired:
            return {"status":"BLOCKED","reason":"Blind ML worker timeout",
                    "certification":"NOT_VALIDATED_OR_CALIBRATED"}
    if result.returncode:
        return {"status":"BLOCKED","reason":result.stdout[-1000:] or result.stderr[-500:],
                "certification":"NOT_VALIDATED_OR_CALIBRATED"}
    response=json.loads(result.stdout)
    if response.get("status")!="EXECUTED_PROCESS_SEPARATE_ML":
        raise RuntimeError("Blind ML process did not return a valid independent result")
    return response

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--player",required=True)
    p.add_argument("--market",required=True,choices=sorted(MARKETS))
    p.add_argument("--asof",required=True)
    args=p.parse_args()
    c=sqlite3.connect("file:"+str(Path(args.db).resolve())+"?mode=ro",uri=True)
    c.row_factory=sqlite3.Row
    try:
        result=run_separate(c,args.player,args.market,args.asof)
    finally:
        c.close()
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    main()
