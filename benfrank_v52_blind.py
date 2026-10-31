"""Independent early pooled ridge: real lagged games, including thin-history targets.

The separate numerical worker sees no name, line, opponent, primary forecast,
or primary decision. No fake target games are made to meet a minimum sample.
"""
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from acquire_history import name_key
from engine import stat
from benfrank_v45_evidence import readonly,digest

def features(rows,market):
    if len(rows)<3:raise ValueError('THREE_REAL_PRIOR_TARGET_APPEARANCES_REQUIRED')
    last3=rows[-3:];last10=rows[-10:];last20=rows[-20:]
    mean=lambda rs:statistics.mean(stat(r,market) for r in rs)
    return [mean(last3),mean(last10),mean(last20),statistics.median(r['minutes'] for r in last3),mean(last3)-mean(last20)]

def payload(conn,player,market,day):
    rows=[dict(r) for r in conn.execute('SELECT * FROM games WHERE date<? AND minutes>=8 ORDER BY date,player,team',(day,))]
    histories={};training=[]
    for row in rows:
        key=name_key(row['player']);prior=histories.setdefault(key,[])
        # At least three genuinely earlier appearances, never same-day outcomes.
        earlier=[r for r in prior[-21:] if r['date']<row['date']]
        if len(earlier)>=3:training.append({'x':features(earlier,market),'y':float(stat(row,market))})
        prior.append(row)
    target=histories.get(name_key(player),[])
    if len(target)<3:raise ValueError('THREE_REAL_PRIOR_TARGET_APPEARANCES_REQUIRED')
    if len(training)<100:raise ValueError('ONE_HUNDRED_REAL_CHRONOLOGICAL_PEER_TRAINING_ROWS_REQUIRED')
    return {'train':training,'candidate':features(target,market),'ridge':.15},len(target)

def run(db,player,market,day):
    conn=readonly(db)
    try:data,n=payload(conn,player,market,day)
    finally:conn.close()
    worker=Path(__file__).with_name('benfrank_v44_blind_worker.py')
    with tempfile.TemporaryDirectory(prefix='benfrank-v52-blind-') as tmp:
        r=subprocess.run([sys.executable,'-I',str(worker.resolve())],input=json.dumps(data,allow_nan=False),
                         text=True,capture_output=True,cwd=tmp,timeout=90,check=False)
    if r.returncode:raise ValueError('EARLY_BLIND_PROCESS_FAILURE: '+r.stdout[-300:])
    result=json.loads(r.stdout)
    result.update(model='BENFRANK_V52_POOLED_LAGGED_RIDGE_1',
        algorithm='Pooled chronological peer ridge with 3/10/20 available-game features; missing target games are never invented',
        target_observed_appearances=n,thin_target_history=n<20,
        candidate_history_coverage={'L3':min(n,3),'L10':min(n,10),'L20':min(n,20)},
        historical_cutoff_exclusive=day,market_probability_calibration_applied=False,
        worker_source_sha256=digest(worker),orchestrator_source_sha256=digest(__file__),
        certification='NOT_VALIDATED_OR_CALIBRATED')
    return result
