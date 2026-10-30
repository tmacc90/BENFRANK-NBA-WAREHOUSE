"""Run repaired availability/rotation simulation and a correctly scoped calibration.

This is the executable v4.7 per-prop entry point. Evidence and release authority
are separate from the directional projection. No unvalidated FULL promotion.
"""
import argparse
import json
import hashlib
from pathlib import Path

from benfrank_v45_evidence import write_json,digest
from benfrank_v47_model import trial_run
from benfrank_v47_uncertainty import apply as calibrated
from benfrank_v44_calibration import instant


def validate_cutoff(context):
    mode=context.get('input_mode')
    if mode=='EXPLICIT_SYNTHETIC_TEST':return
    if mode!='RECONSTRUCTED_ASOF_WITH_ORIGINAL_OFFICIAL_AVAILABILITY':
        raise ValueError('SOURCE_BACKED_V47_CONTEXT_REQUIRED')
    capture=instant(context['line_capture_utc'])
    if capture>=instant(context['tipoff_utc']):raise ValueError('LINE_CAPTURE_NOT_PREGAME')
    if instant(context['official_report_time_utc'])>capture:raise ValueError('OFFICIAL_REPORT_AFTER_LINE_CAPTURE')
    if not context['max_feature_game_date']<=context['history_through_date']<context['game_date']:
        raise ValueError('TARGET_OR_FUTURE_GAME_IN_FORECAST_HISTORY')
    stamps=[context['pace_asof']]+[r['asof'] for r in context['team_rates'].values()]
    stamps += [p['asof'] for roster in context['rosters'].values() for p in roster]
    if any(instant(stamp)>capture for stamp in stamps):raise ValueError('RATE_OR_ROSTER_SOURCE_AFTER_LINE_CAPTURE')


def save_receipt(path,result):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    frozen={**result,'receipt_sha256':hashlib.sha256(json.dumps(result,sort_keys=True,allow_nan=False).encode()).hexdigest()}
    with path.open('x') as stream:
        stream.write(json.dumps(frozen,sort_keys=True,indent=2,allow_nan=False)+'\n')


def run(context,player,market,line,platform,calibration=None,trials=25000,seed=42):
    validate_cutoff(context)
    if market=='fantasy_score' and context.get('scoring_contract')!='PTS1_REB1.2_AST1.5_STL3_BLK3_TOV-1':
        raise ValueError('EXPLICIT_MATCHING_FANTASY_SCORING_CONTRACT_REQUIRED')
    receipt=trial_run(context,player,market,line,trials,seed)
    result={'framework':'BENFRANK NBA v4.7 availability/uncertainty repair','simulation':receipt,
            'direction_status':'PROVISIONAL_UNTIL_APPLICABLE_RELEASE_GATES_PASS',
            'direction':None,'certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET','release_blockers':[]}
    if receipt['p_over_raw'] is None:
        result.update(status='BLOCKED_NO_CONDITIONAL_PLAYED_DISTRIBUTION')
        result['release_blockers'].append('No conditional played distribution; voids are not UNDER wins')
        return result
    row={'player':player,'market':market,'line':line,'platform':platform,'game_id':context['game_id'],
         'tipoff_utc':context['tipoff_utc'],'p_over_raw':receipt['p_over_raw'],'mean':receipt['mean'],
         'q05':receipt['quantiles']['0.05'],'q95':receipt['quantiles']['0.95']}
    if calibration is not None:
        try:
            result['forecast']=calibrated(row,calibration)
            probability=result['forecast']['p_over_calibrated']
            result['status']='EXECUTED_WITH_SCOPED_CALIBRATION'
        except ValueError as exc:
            result['forecast']=row;probability=row['p_over_raw']
            result['status']='EXECUTED_CALIBRATION_BLOCKED'
            result['release_blockers'].append(str(exc))
    else:
        result['forecast']=row;probability=row['p_over_raw']
        result['status']='EXECUTED_UNCALIBRATED'
        result['release_blockers'].append('Validated platform/market/line-band calibration artifact required')
    result['direction']='OVER' if probability>=.5 else 'UNDER'
    if context.get('unknown_or_uncertain_availability'):
        result['release_blockers'].append('Material unknown/questionable availability requires authoritative final recheck')
    result['release_blockers'].append('Complete applicable 66-stage evidence and independent ticket authority still required')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context',required=True);p.add_argument('--player',required=True)
    p.add_argument('--market',required=True);p.add_argument('--line',type=float,required=True)
    p.add_argument('--platform',required=True);p.add_argument('--calibration');p.add_argument('--output',required=True)
    p.add_argument('--trials',type=int,default=25000);p.add_argument('--seed',type=int,default=42)
    a=p.parse_args();context=json.loads(Path(a.context).read_text())
    calibration=json.loads(Path(a.calibration).read_text()) if a.calibration else None
    result=run(context,a.player,a.market,a.line,a.platform,calibration,a.trials,a.seed)
    result['input_context_file_sha256']=digest(a.context)
    if a.calibration:result['calibration_file_sha256']=digest(a.calibration)
    save_receipt(a.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('simulation','forecast')},indent=2))


if __name__=='__main__':main()
