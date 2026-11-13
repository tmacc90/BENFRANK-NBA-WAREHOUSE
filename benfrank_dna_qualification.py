"""Selection gate above directional forecasts, with at most one primary."""
from benfrank_auto_history import now


def qualify(result, injury, sources):
    p=result['prop'];blockers=[]
    calibration=result.get('cover_calibration',{})
    probability=calibration.get('selected_side_probability')
    if (calibration.get('validated') is not True or calibration.get('model_version')!=result['version'] or
        calibration.get('market')!=p['market'] or type(probability) not in (int,float) or not 0<=probability<=1):
        blockers.append('NO_VERSION_AND_MARKET_MATCHED_VALIDATED_COVER_PROBABILITY')
    error=result.get('model_error',{})
    risk=error.get('estimated_error_probability')
    if error.get('calibration_status')!='TEMPORAL_VALIDATION_PASSED' or risk is None:
        blockers.append('MODEL_ERROR_UNCALIBRATED')
    elif risk>.25:blockers.append('MODEL_ERROR_RISK_ABOVE_25_PERCENT_POLICY')
    if not result['blind_model'].get('independence_evidence',{}).get('verified'):
        blockers.append('INDEPENDENT_BLIND_PROCESS_UNVERIFIED')
    if result.get('model_disagreement'):blockers.append('PRIMARY_BLIND_SIDE_DISAGREEMENT')
    if result.get('scenario_side_flip'):blockers.append('ADVERSARIAL_SCENARIO_REVERSES_SIDE')
    if injury.get('authority')!='ORIGINAL_NBA_INJURY_PDF' or injury.get('status')!='FULL':
        blockers.append('OFFICIAL_AVAILABILITY_INCOMPLETE')
    if sources.get('projected_status')!='FULL':blockers.append('PROJECTED_LINEUP_INCOMPLETE')
    if p.get('line_authority') not in ('PUBLIC_NATIVE_PRIZEPICKS_RESPONSE','SCREENSHOT_VISUALLY_VERIFIED_LITERAL_LINE'):
        blockers.append('EXACT_LINE_AUTHORITY_REQUIRES_VERIFICATION')
    permitted=p.get('allowed_wager_types')
    if permitted in ('over','under') and result['direction']!=permitted.upper():
        blockers.append('SELECTED_SIDE_UNAVAILABLE_ON_THIS_OFFER')
    breakeven=p.get('break_even_probability')
    if type(breakeven) not in (int,float) or not 0<breakeven<1:
        blockers.append('PAYOUT_BREAK_EVEN_NOT_SUPPLIED')
    elif probability is not None and probability-breakeven<.03:
        blockers.append('CALIBRATED_EDGE_BELOW_3_PERCENT_POLICY')
    return dict(status='FULL' if not blockers else 'LIMITED',timestamp=now(),source='Frozen model/source receipts',
        qualified=not blockers,primary=False,blockers=blockers,guaranteed=False,
        calibrated_side_probability=probability if calibration.get('validated') else None,
        estimated_model_error=risk,financial_edge=probability-breakeven if probability is not None and type(breakeven) in (int,float) else None,
        policy_version='BENFRANK_TICKET_GATE_20261113_1')


def rank(entries):
    candidates=[e for e in entries if e.get('ticket_qualification',{}).get('qualified')]
    candidates.sort(key=lambda e:(-e['ticket_qualification']['financial_edge'],
                                   e['ticket_qualification']['estimated_model_error'],e['prop']['snapshot_id']))
    selected=[dict(snapshot_id=e['prop']['snapshot_id'],player=e['prop']['player'],market=e['prop']['market'],
                   line=e['prop']['line'],direction=e['direction'],primary=i==0,
                   qualification=e['ticket_qualification']) for i,e in enumerate(candidates)]
    return dict(qualified=selected,primary=selected[0] if selected else None,status='FULL' if selected else 'LIMITED',
                exact_reason=None if selected else 'NO_PROP_MEETS_VALIDATED_PROBABILITY_ERROR_SOURCE_AND_PAYOUT_GATES',guaranteed=False)
