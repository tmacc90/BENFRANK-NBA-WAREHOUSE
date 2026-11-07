"""Append-only early prediction/settlement ledger; no retroactive pick replacement.

The settlement adapter uses completed ESPN summaries with explicit source tier.
Prospective scorecards do not turn secondary labels into official certification.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from acquire_history import name_key
from engine import stat
from benfrank_v44_calibration import instant
from benfrank_v51_espn_game_details import fetch_json,BASE,verify_completed_summary
from espn_live_stage import rows_from_summary

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path);c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE IF NOT EXISTS early_predictions(
      id TEXT PRIMARY KEY,issued_at TEXT NOT NULL,tipoff_utc TEXT NOT NULL,receipt_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS early_settlements(
      id TEXT PRIMARY KEY,prediction_id TEXT NOT NULL,observed_at TEXT NOT NULL,source_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS freeze_predictions_update BEFORE UPDATE ON early_predictions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_PREDICTION'); END;
    CREATE TRIGGER IF NOT EXISTS freeze_predictions_delete BEFORE DELETE ON early_predictions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_PREDICTION'); END;
    CREATE TRIGGER IF NOT EXISTS freeze_settlements_update BEFORE UPDATE ON early_settlements BEGIN SELECT RAISE(ABORT,'IMMUTABLE_SETTLEMENT'); END;
    CREATE TRIGGER IF NOT EXISTS freeze_settlements_delete BEFORE DELETE ON early_settlements BEGIN SELECT RAISE(ABORT,'IMMUTABLE_SETTLEMENT'); END;''')
    return c

def record_prediction(path,receipt):
    issued=now();prop=receipt['prop']
    if receipt['status']!='FORWARD_TEST_READY':raise ValueError('ONLY_FORWARD_TEST_READY_PREDICTIONS_MAY_ENTER_COHORT')
    simulation=receipt.get('main_simulation',{})
    if (type(simulation.get('trials_executed')) is not int or simulation['trials_executed']<25000 or
        simulation.get('complete_sequential_games') is not True or
        sum(simulation.get(k,0) for k in ('over_count','under_count','push_count','void_count'))!=simulation['trials_executed']):
        raise ValueError('QUALIFYING_COMPLETE_25000_GAME_RECEIPT_REQUIRED')
    if not instant(receipt['analysis_cutoff_utc'])<=instant(receipt['forecast_completed_at_utc'])<=instant(issued)<instant(prop['tipoff_utc']):
        raise ValueError('ACTUAL_PREDICTION_INSERT_MUST_PRECEDE_TIPOFF')
    payload={k:v for k,v in receipt.items() if k!='receipt_sha256'}
    sha=hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    if receipt.get('receipt_sha256')!=sha:raise ValueError('PREDICTION_RECEIPT_HASH_CONFLICT')
    c=connect(path)
    try:
        with c:c.execute('INSERT INTO early_predictions VALUES(?,?,?,?,?)',
            (prop['snapshot_id'],issued,prop['tipoff_utc'],sha,json.dumps(receipt,sort_keys=True,allow_nan=False)))
    finally:c.close()

def settle(path,fetch=fetch_json):
    c=connect(path);results=[];cache={}
    try:
        pending=c.execute('SELECT * FROM early_predictions WHERE id NOT IN (SELECT prediction_id FROM early_settlements) ORDER BY issued_at').fetchall()
        for row in pending:
            r=json.loads(row['payload_json']);p=r['prop'];eid=str(p['espn_event_id'])
            if instant(now())<=instant(p['tipoff_utc']):results.append({'id':row['id'],'status':'PENDING_GAME'});continue
            try:
                if eid not in cache:cache[eid]=fetch(BASE+'summary?event='+eid)
                document,raw=cache[eid];sha=hashlib.sha256(raw).hexdigest()
                comp=document['header']['competitions'][0]
                if ((comp.get('status') or {}).get('type') or {}).get('completed') is not True:
                    results.append({'id':row['id'],'status':'PENDING_FINAL'});continue
                teams={x['homeAway']:x['team']['abbreviation'] for x in comp['competitors']}
                from acquire_history import team_key
                if set(map(team_key,teams.values()))!={p['team'],p['opponent']}:raise ValueError('SETTLEMENT_OPPONENT_CONFLICT')
                event={'event_id':eid,'date':p['game_date'],'home':teams['home'],'away':teams['away']}
                verify_completed_summary(document,event)
                rows=rows_from_summary(eid,p['game_date'],teams['home'],teams['away'],document)
                target=[x for x in rows if name_key(x['player'])==name_key(p['player']) and team_key(x['team'])==p['team']]
                if len(target)!=1 or target[0]['minutes']<=0:
                    results.append({'id':row['id'],'status':'UNRESOLVED_DNP_OR_PLATFORM_VOID_RULE'});continue
                actual=stat(target[0],p['market']);label='OVER' if actual>p['line'] else 'UNDER' if actual<p['line'] else 'PUSH'
                value={'prediction_id':row['id'],'actual':actual,'outcome':label,'direction':r['direction'],
                    'correct':label==r['direction'] if label!='PUSH' else None,'observed_at':now(),
                    'source_url':BASE+'summary?event='+eid,'source_sha256':sha,'assurance':'ESPN_SECONDARY_FINAL_NOT_NATIVE_PLATFORM_SETTLEMENT',
                    'native_platform_settlement_verified':False,'official_nba_independently_verified':False}
                sid=hashlib.sha256((row['id']+'|'+sha).encode()).hexdigest()
                with c:c.execute('INSERT INTO early_settlements VALUES(?,?,?,?,?)',(sid,row['id'],value['observed_at'],sha,json.dumps(value,sort_keys=True)))
                results.append(value)
            except Exception as exc:results.append({'id':row['id'],'status':'BLOCKED','reason':type(exc).__name__+': '+str(exc)})
    finally:c.close()
    return results

def scorecard(path):
    c=connect(path)
    try:
        preds={r['id']:json.loads(r['payload_json']) for r in c.execute('SELECT * FROM early_predictions ORDER BY issued_at,id')}
        labels=[json.loads(r['payload_json']) for r in c.execute('SELECT * FROM early_settlements ORDER BY observed_at,id')]
    finally:c.close()
    groups=collections.defaultdict(list);first={};cohort_ids=set()
    for rid,receipt in preds.items():
        p=receipt['prop'];key=tuple(p.get(k,rid) for k in ('game_id','player','market','line','platform'))
        if key not in first:first[key]=rid;cohort_ids.add(rid)
    for label in labels:
        if label['prediction_id'] not in cohort_ids:continue
        if label['outcome']=='PUSH':continue
        r=preds[label['prediction_id']];p=r['prop'];band=(int(p['line']//5)*5,int(p['line']//5)*5+5)
        y=int(label['outcome']=='OVER');prob=r['main_simulation']['p_over_raw']
        groups[(p['platform'],p['market'],band)].append((label['correct'],(prob-y)**2,p['game_id']))
    return {'version':'V52_FORWARD_SCORECARD_1','predictions_frozen_before_tipoff':len(preds),'settlement_rows':len(labels),
        'unique_prop_first_forecasts':len(cohort_ids),'pre_tipoff_revisions_excluded_from_primary_scorecard':len(preds)-len(cohort_ids),
        'revision_policy':'All snapshots retained; first-issued forecast per exact game/player/market/line/platform enters the primary scorecard',
        'strata':[{'platform':key[0],'market':key[1],'line_band':key[2],'n':len(v),'unique_games':len({x[2] for x in v}),
                   'hit_rate':sum(x[0] for x in v)/len(v),'raw_brier':sum(x[1] for x in v)/len(v),
                   'probability_calibration_certified':False} for key,v in sorted(groups.items())],
        'certification':'UNVALIDATED','outcome_assurance':'ESPN_SECONDARY_UNLESS_SEPARATELY_VERIFIED',
        'note':'No refitting or pooled-market certification. Small forward cohorts are measurement, not proof of an edge.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--settle',action='store_true');p.add_argument('--output',required=True)
    a=p.parse_args();r={'settlements':settle(a.db) if a.settle else [],'scorecard':scorecard(a.db)}
    from benfrank_v47_run import save_receipt
    save_receipt(a.output,r);print(json.dumps(r,indent=2))
if __name__=='__main__':main()
