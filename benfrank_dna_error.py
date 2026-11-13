"""Separate decision-error model. Only frozen, settled forward decisions train it.

No synthetic labels, retrospective forecasts, raw-hit-rate complements or
unsettled decisions enter the fit. Insufficient support returns UNCALIBRATED.
"""
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from benfrank_auto_history import now, instant
from benfrank_dna_history import MARKETS

VERSION='BENFRANK_ERROR_RIDGE_LOGISTIC_1'


def features(receipt):
    sim=receipt['main_simulation'];p=sim['p_over_raw'];prop=receipt['prop']
    selected=p if receipt['direction']=='OVER' else 1-p
    distribution={float(k):v for k,v in sim.get('histogram',{}).items()}
    n=sum(distribution.values())
    mean=sum(k*v for k,v in distribution.items())/n if n else receipt['projection']
    sd=math.sqrt(sum(v*(k-mean)**2 for k,v in distribution.items())/max(1,n))
    games=receipt.get('source_audit',{}).get('games',0)
    return [1.0, selected, abs(mean-prop['line'])/max(1,sd),
            float(receipt.get('model_disagreement',True)),float(receipt.get('scenario_side_flip',True)),
            min(games,100)/100, *[float(prop['market']==m) for m in MARKETS]]


def load_forward(path, cutoff):
    if not Path(path).is_file():return [],{'ledger':'ABSENT','excluded':0}
    conn=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    rows=[];excluded=0;seen=set()
    try:
        for row in conn.execute('''SELECT p.id,p.issued_at,p.tipoff_utc,p.receipt_sha256,p.payload_json,
                 s.observed_at,s.payload_json AS settlement FROM early_predictions p
                 JOIN early_settlements s ON s.prediction_id=p.id ORDER BY p.issued_at,p.id'''):
            try:
                r=json.loads(row['payload_json']);s=json.loads(row['settlement']);p=r['prop']
                raw={k:v for k,v in r.items() if k!='receipt_sha256'}
                digest=hashlib.sha256(json.dumps(raw,sort_keys=True,allow_nan=False).encode()).hexdigest()
                if digest!=row['receipt_sha256'] or digest!=r['receipt_sha256']:raise ValueError('HASH_CONFLICT')
                if not (instant(row['issued_at'])<instant(row['tipoff_utc'])<instant(row['observed_at'])<instant(cutoff)):
                    raise ValueError('NONFORWARD_OR_UNSETTLED_BY_CUTOFF')
                if r.get('status')!='FORWARD_TEST_READY' or not r.get('main_simulation',{}).get('trial_evidence',{}).get('verified'):
                    raise ValueError('UNVERIFIED_FORWARD_DECISION')
                if s.get('correct') not in (True,False) or s.get('outcome') not in ('OVER','UNDER') or not s.get('source_sha256'):
                    raise ValueError('NO_VERIFIED_NONPUSH_OUTCOME')
                source=Path(s.get('source_path',''))
                if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=s['source_sha256']:
                    raise ValueError('NO_RETAINED_VERIFIABLE_OUTCOME_SOURCE')
                # Recompute the label from the retained completed box, rather
                # than trusting a mutable user assertion of "correct".
                from benfrank_v51_espn_game_details import verify_completed_summary
                from espn_live_stage import rows_from_summary
                from acquire_history import name_key,team_key
                from engine import stat
                doc=json.loads(source.read_bytes());comp=doc['header']['competitions'][0]
                sides={x['homeAway']:x['team']['abbreviation'] for x in comp['competitors']}
                event=dict(event_id=str(p['espn_event_id']),date=p['game_date'],**sides)
                verify_completed_summary(doc,event)
                boxes=rows_from_summary(event['event_id'],event['date'],sides['home'],sides['away'],doc)
                target=[x for x in boxes if name_key(x['player'])==name_key(p['player']) and team_key(x['team'])==p['team']]
                if len(target)!=1:raise ValueError('UNRESOLVED_SETTLEMENT_PLAYER')
                actual=stat(target[0],p['market'])
                outcome='OVER' if actual>p['line'] else 'UNDER' if actual<p['line'] else 'PUSH'
                if outcome!=s['outcome'] or (outcome==r['direction']) is not s['correct']:
                    raise ValueError('OUTCOME_LABEL_DISAGREEMENT')
                key=(p['game_id'],p['player'],p['market'],p['line'])
                if key in seen:continue
                seen.add(key)
                # Version isolation: changed forecast engines need a new forward cohort.
                if r.get('dna_repair_version')!='20261113_1':raise ValueError('OTHER_MODEL_VERSION')
                rows.append(dict(x=features(r),y=int(not s['correct']),game=p['game_id'],
                                 date=p['game_date'],issued=row['issued_at'],settled=row['observed_at'],id=row['id']))
            except (ValueError,KeyError,TypeError):excluded+=1
    except sqlite3.OperationalError:
        return [],{'ledger':'NO_COMPATIBLE_FORWARD_TABLES','excluded':0}
    finally:conn.close()
    return rows,dict(ledger='READ_ONLY',excluded=excluded)


def assess(ledger, receipt):
    cutoff=receipt['analysis_cutoff_utc'];rows,audit=load_forward(ledger,cutoff)
    base=dict(version=VERSION,status='LIMITED',timestamp=now(),source=str(ledger),
        calibration_status='UNCALIBRATED',estimated_error_probability=None,training_n=0,validation_n=0,
        eligible_frozen_settled_n=len(rows),input_audit=audit,cover_probability_is_separate=True,
        limitation='Raw cover probability is not used as a calibrated estimate of model-error risk')
    dates=sorted({r['date'] for r in rows})
    if len(rows)<300 or len(dates)<14:
        return dict(base,exact_blocker='NEED_300_VERSION_MATCHED_FROZEN_SETTLED_DECISIONS_OVER_14_DATES',
                    required_remaining=max(0,300-len(rows)))
    # Time split also separates game clusters. Training outcomes must have been
    # observed before the first validation forecast, not merely played earlier.
    split=dates[max(1,int(len(dates)*.7))]
    validation=[r for r in rows if r['date']>=split]
    first=min(instant(r['issued']) for r in validation)
    train=[r for r in rows if r['date']<split and instant(r['settled'])<first]
    if len(train)<200 or len(validation)<100 or len({r['game'] for r in validation})<30:
        return dict(base,exact_blocker='INSUFFICIENT_DISJOINT_TIME_GAME_VALIDATION_SUPPORT',
                    training_n=len(train),validation_n=len(validation))
    import numpy as np
    x=np.asarray([r['x'] for r in train]);y=np.asarray([r['y'] for r in train]);w=np.zeros(x.shape[1])
    for _ in range(80):
        prob=1/(1+np.exp(-np.clip(x@w,-25,25)))
        gradient=x.T@(prob-y)+2*w
        hessian=(x.T*(prob*(1-prob)))@x+2*np.eye(len(w))
        step=np.linalg.solve(hessian,gradient);w-=step
        if np.max(abs(step))<1e-7:break
    def predict(vector):return float(1/(1+np.exp(-np.clip(np.dot(vector,w),-25,25))))
    probs=[predict(r['x']) for r in validation]
    brier=sum((p-r['y'])**2 for p,r in zip(probs,validation))/len(validation)
    error=sum(r['y'] for r in validation)/len(validation)
    gap=abs(sum(probs)/len(probs)-error)
    validated=gap<=.05 and brier<.25
    return dict(base,status='FULL' if validated else 'LIMITED',
        calibration_status='TEMPORAL_VALIDATION_PASSED' if validated else 'UNCALIBRATED',
        estimated_error_probability=predict(features(receipt)) if validated else None,
        training_n=len(train),validation_n=len(validation),validation_brier=brier,
        validation_mean_calibration_gap=gap,validation_observed_error_rate=error,
        training_ids=[r['id'] for r in train],validation_ids=[r['id'] for r in validation],
        coefficients=w.tolist(),calibration_scope='Overall mean on held-out dates; market-specific calibration not established',
        exact_blocker=None if validated else 'TEMPORAL_ERROR_VALIDATION_FAILED')
