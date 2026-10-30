"""Execute predeclared development -> calibration freeze -> separate new test.

Every phase and exclusion has its own receipt. The previous v4.6 study remains
unchanged and becomes development evidence, never a regraded held-out success.
"""
import argparse
import collections
import concurrent.futures
import datetime as dt
import hashlib
import json
import sqlite3
import statistics
from pathlib import Path

from engine import connect, FIELDS, stat
from benfrank_v44_snapshot_ledger import export
from benfrank_v44_calibration import scores, probability_from_history
from benfrank_v44_blind_orchestrator import run_separate
from benfrank_v45_evidence import readonly,digest,write_json
from benfrank_v45_backtest import clustered_brier_interval
from benfrank_v47_availability import load_archive
from benfrank_v47_history import History
from benfrank_v47_model import build_context,fit_availability,trial_run
from benfrank_v47_board import normalize_scheduled,cohort,season_aggregate_check
from benfrank_v47_uncertainty import fit as fit_uncertainty,apply as adjust,wilson


def execute(job):
    context_file,snapshot,result_path=job
    context=json.loads(Path(context_file).read_text())
    seed=int(hashlib.sha256(('V47|'+snapshot['snapshot_id']).encode()).hexdigest()[:8],16)
    result=trial_run(context,snapshot['player'],snapshot['market'],snapshot['line'],25000,seed)
    result.update(snapshot_id=snapshot['snapshot_id'],context_file_sha256=digest(context_file),
                  executed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    write_json(result_path,result)
    return result


def feature_database(history,path):
    conn=connect(path)
    conn.execute('CREATE TABLE research_source_assurance(player,date,team,source_tier)')
    with conn:
        conn.executemany('INSERT INTO games VALUES ('+','.join('?' for _ in FIELDS)+')',
                         [tuple(r[k] for k in FIELDS) for r in history.games])
        conn.executemany('INSERT INTO research_source_assurance VALUES (?,?,?,?)',
                         [(r['player'],r['date'],r['team'],r['source_tier']) for r in history.games])
    conn.close()


def phase(name,selected,history,documents,archives,availability,out,workers,blind_db):
    folder=out/name;folder.mkdir();(folder/'contexts').mkdir();(folder/'simulations').mkdir()
    jobs=[];rejections=[]
    for s in selected:
        token=hashlib.sha256(s['snapshot_id'].encode()).hexdigest()
        try:
            context=build_context(history,s,documents[s['source_file']],archives,availability)
            path=folder/'contexts'/(token+'.json');write_json(path,context)
            jobs.append((str(path),s,str(folder/'simulations'/(token+'.json'))))
        except (ValueError,KeyError,TypeError) as exc:
            rejections.append({'snapshot_id':s['snapshot_id'],'reason':str(exc)})
    manifest={'partition':name,'selected':selected,'context_eligible':len(jobs),'context_exclusions':rejections,
              'frozen_before_simulation':dt.datetime.now(dt.timezone.utc).isoformat(),
              'model_source_sha256':digest(Path(__file__).with_name('benfrank_v47_model.py')),
              'physics_source_sha256':digest(Path(__file__).with_name('benfrank_v44_twon.py')),
              'history_source_sha256':digest(Path(__file__).with_name('benfrank_v47_history.py')),
              'trials_per_exact_line':25000}
    write_json(folder/'manifest.json',manifest)
    rows=[];executed=0
    conn=readonly(blind_db)
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(execute,job):job for job in jobs}
            for future in concurrent.futures.as_completed(futures):
                context_file,s,path=futures[future]
                try:
                    receipt=future.result();executed+=receipt['trials_executed']
                    if sum(receipt[k] for k in ('over_count','under_count','push_count','void_count'))!=25000:
                        raise ValueError('COMPLETE_GAME_TRIAL_COUNTS_INCONSISTENT')
                    if receipt['p_over_raw'] is None:raise ValueError('NO_CONDITIONAL_PLAYED_SIMULATION_DISTRIBUTION')
                    actual=history.actual.get((__import__('acquire_history').name_key(s['player']),s['game_date'],s['team']))
                    if actual is None:raise ValueError('UNPLAYED_OR_NO_UNIQUE_SOURCE_SETTLEMENT_POLICY_UNATTESTED')
                    value=float(stat(actual,s['market']))
                    if value==s['line']:raise ValueError('PUSH_EXCLUDED_FROM_BINARY_CALIBRATION_RECEIPT_RETAINED')
                    context=json.loads(Path(context_file).read_text())
                    prior=history.prior(s['player'],context['history_through_date'])
                    baseline=probability_from_history(prior,s['market'],s['line'])
                    if baseline is None:raise ValueError('INSUFFICIENT_PRIOR_EMPIRICAL_BASELINE')
                    asof=(dt.date.fromisoformat(context['history_through_date'])+dt.timedelta(days=1)).isoformat()
                    blind=run_separate(conn,s['player'],s['market'],asof)
                    rows.append({**{k:s[k] for k in ('snapshot_id','player','market','line','platform','game_id','game_date','tipoff_utc')},
                        'partition':name,'actual':value,'over_result':int(value>s['line']),'mean':receipt['mean'],
                        'q05':receipt['quantiles']['0.05'],'q95':receipt['quantiles']['0.95'],
                        'p_over_raw':receipt['p_over_raw'],'p_over_baseline':baseline['p_over_raw'],
                        'void_probability':receipt['void_probability'],'blind_prediction':blind.get('projection'),'blind_receipt':blind,
                        'source_tier':actual['source_tier'],'unknown_availability_count':len(context['unknown_or_uncertain_availability']),
                        'simulation_receipt':str(Path(path).relative_to(out))})
                    print(json.dumps({'phase':name,'predictions':len(rows),'actual_trials_executed':executed}),flush=True)
                except (ValueError,KeyError,TypeError,OSError) as exc:
                    rejections.append({'snapshot_id':s['snapshot_id'],'reason':str(exc)})
        result={'phase':name,'predictions':rows,'rejections':rejections,'simulation_trials_executed':executed,
                'manifest_sha256':digest(folder/'manifest.json'),'certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET'}
        write_json(folder/'phase.json',result)
        return result
    finally:conn.close()


def evaluate(test,model):
    rows=test['predictions']
    if not rows:return {'status':'BLOCKED_NO_NEW_TEST_PREDICTIONS'}
    if any(r['game_id'] in model['development_game_ids'] for r in rows):raise ValueError('DEVELOPMENT_NEW_TEST_GAME_LEAKAGE')
    if min(r['tipoff_utc'] for r in rows)<=model['latest_development_tipoff']:raise ValueError('NEW_TEST_NOT_CHRONOLOGICALLY_LATER')
    adjusted=[adjust(r,model) for r in rows]
    raw_hits=sum(r['q05']<=r['actual']<=r['q95'] for r in adjusted)
    corrected_hits=sum(r['q05_adjusted']<=r['actual']<=r['q95_adjusted'] for r in adjusted)
    blind=[r for r in adjusted if r['blind_prediction'] is not None]
    return {'status':'NEW_PERIOD_VALIDATION_EXECUTED','new_test_games':len(adjusted),
        'raw_coverage_90pct':raw_hits/len(adjusted),'adjusted_coverage_90pct':corrected_hits/len(adjusted),
        'adjusted_coverage_successes':corrected_hits,'coverage_wilson_95pct':wilson(corrected_hits,len(adjusted)),
        'raw_mae':statistics.mean(abs(r['mean']-r['actual']) for r in adjusted),
        'adjusted_mae':statistics.mean(abs(r['mean_adjusted']-r['actual']) for r in adjusted),
        'blind_evaluated':len(blind),'blind_mae':statistics.mean(abs(r['blind_prediction']-r['actual']) for r in blind) if blind else None,
        'raw_brier_log_loss':scores(adjusted,'p_over_raw'),'adjusted_brier_log_loss':scores(adjusted,'p_over_calibrated'),
        'baseline_brier_log_loss':scores(adjusted,'p_over_baseline'),
        'brier_delta_vs_baseline':clustered_brier_interval(adjusted,'p_over_calibrated','p_over_baseline'),
        'source_tiers':dict(collections.Counter(r['source_tier'] for r in rows)),
        'unknown_material_availability_cases':sum(r['unknown_availability_count']>0 for r in rows),
        'heldout_results':adjusted,'certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET',
        'interpretation':'Fresh model test period, separate from inspected v4.6 games. Secondary current-game labels and uncertain material availability retain their explicit release limits.'}


def run(args):
    out=Path(args.out_dir).resolve();out.mkdir(parents=True,exist_ok=False)
    protocol=json.loads(Path(args.protocol).read_text())
    write_json(out/'protocol.json',protocol)
    h=History(args.warehouse,args.shooting_database,args.current_schedule,args.current_espn)
    c=readonly(Path(args.development_lines)/'snapshots.sqlite');development=export(c);c.close()
    documents={name:json.loads((Path(args.development_lines)/name).read_text()) for name in {s['source_file'] for s in development}}
    archives=load_archive(args.development_injuries,h.aliases)
    availability=fit_availability(h,development,archives,documents);write_json(out/'availability-model.json',availability)
    previous=json.loads(Path(args.prior_selection).read_text())['snapshot_ids'];lookup={s['snapshot_id']:s for s in development}
    selected=[lookup[sid] for sid in previous]
    new_rows,new_docs,new_rejections=normalize_scheduled(args.new_capture_root,h,out/'new-test-lines.sqlite')
    low,high=protocol['new_test_game_dates'];new_selected=cohort(new_rows,low,high)
    if set(s['game_id'] for s in selected)&set(s['game_id'] for s in new_selected):raise ValueError('COHORTS_NOT_DISJOINT')
    write_json(out/'new-test-cohort-frozen.json',{'snapshots':new_selected,'source_mapping_exclusions':new_rejections,
        'frozen_before_development_fit':dt.datetime.now(dt.timezone.utc).isoformat(),'protocol_sha256':digest(args.protocol)})
    feature_database(h,out/'research-features.sqlite')
    dev=phase('DEVELOPMENT',selected,h,documents,archives,availability,out,args.workers,out/'research-features.sqlite')
    calibration=fit_uncertainty(dev['predictions']);calibration['protocol_sha256']=digest(args.protocol)
    calibration['frozen_at']=dt.datetime.now(dt.timezone.utc).isoformat();write_json(out/'calibration-model.json',calibration)
    print(json.dumps({'calibration_frozen':True,'development_n':calibration['development_n'],'conformal_n':calibration['conformal_calibration_n']}),flush=True)
    new_archives=load_archive(args.new_injuries,h.aliases)
    new=phase('NEW_TEST',new_selected,h,new_docs,new_archives,availability,out,args.workers,out/'research-features.sqlite')
    result={'status':'AVAILABILITY_AND_UNCERTAINTY_REPAIRS_EXECUTED','components_repaired':True,
        'availability_integration':'ORIGINAL_OFFICIAL_REPORTS_GAME_SCOPED_UNKNOWN_NOT_CLEARED',
        'minute_model':'VARIABLE_PLAYED_STATUS_AND_CONSERVED_TEAM_ROTATION_SCENARIOS',
        'uncertainty_model':'DEVELOPMENT_FIT_THEN_DISJOINT_CONFORMAL_SAMPLE_THEN_LATER_NEW_TEST',
        'calibration_sha256_before_new_test':digest(out/'calibration-model.json'),
        'development_trials':dev['simulation_trials_executed'],'new_test_trials':new['simulation_trials_executed'],
        'new_test_evaluation':evaluate(new,calibration),'source_hashes':h.source_hashes,
        'current_ingestion_rejections':h.current_rejections,'certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET',
        'original_warehouse_unchanged':digest(args.warehouse)==h.source_hashes['warehouse']}
    write_json(out/'repair-validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='new_test_evaluation'},indent=2))
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('warehouse','shooting-database','current-schedule','current-espn','development-lines','development-injuries',
                 'prior-selection','new-capture-root','new-injuries','out-dir'):
        p.add_argument('--'+flag,required=True)
    p.add_argument('--protocol',default='configs/v47_validation_protocol.json')
    p.add_argument('--workers',type=int,default=6)
    run(p.parse_args())


if __name__=='__main__':main()
