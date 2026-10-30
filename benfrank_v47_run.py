"""Run repaired availability/rotation simulation and a correctly scoped calibration.

This is the executable v4.7 per-prop entry point. Evidence and release authority
are separate from the directional projection. No unvalidated FULL promotion.
"""
import argparse
import json
from pathlib import Path

from benfrank_v45_evidence import write_json,digest
from benfrank_v47_model import trial_run
from benfrank_v47_uncertainty import apply as calibrated


def run(context,player,market,line,platform,calibration=None,trials=25000,seed=42):
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
    write_json(a.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('simulation','forecast')},indent=2))


if __name__=='__main__':main()
