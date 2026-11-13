"""One acquisition-to-freeze workflow, preserving all legacy execution modes."""
import collections
import datetime as dt
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

from acquire_history import name_key
from engine import window_summary
from benfrank_auto_history import Store, acquire_logs, acquire_mirror, write_history, now, sha, encode, instant
from benfrank_auto_context import (schedule, discover, capture_roles, acquire_recent_boxes,
                                  ProfileHistory, build_context, captured_board)
from benfrank_auto_evidence import sensitivity, interrogation
from benfrank_v52_early import run_one, season_start
from benfrank_v52_ledger import record_prediction
from benfrank_v47_run import save_receipt
from benfrank_v53_core import report as dna_report
from benfrank_manual_prop import resolve_manual_forward_prop

VERSION = 'BENFRANK_DNA_REPAIR_20261113_1'
STAGES = ('exact_line_schedule', 'player_identity', 'automatic_acquisition', 'source_reconciliation',
          'historical_windows', 'player_profiles_matchup_roles', 'sequential_25000', 'independent_blind_process',
          'adversarial_stress', 'sensitivity', 'player_dna_100', 'interrogation_60', 'model_error', 'ticket_qualification', 'pregame_freeze', 'postgame_grading')


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')


def historical_windows(rows, market, line, day, opponent=None, expected_minutes=None):
    from benfrank_dna_history import historical_windows as season_windows
    return season_windows(rows, market, line, day, opponent, expected_minutes)


def dna_input(prop, rows, result):
    translated = []
    for row in rows:
        r = {out: row.get(key) for out, key in (('points', 'pts'), ('rebounds', 'reb'), ('assists', 'ast'),
                ('steals', 'stl'), ('blocks', 'blk'), ('turnovers', 'tov'), ('three_pm', 'fg3m'))}
        r.update(date=row['date'], season=row['season'], game_id=row['game_id'], played=True,
                 opponent=row['opponent'], home=row['home'], minutes=row['minutes'], fga=row.get('fga'),
                 three_pa=row.get('fg3a'), fta=row.get('fta'), oreb=row.get('oreb'), dreb=row.get('dreb'))
        translated.append(r)
    p = dict(prop, cutoff=prop['game_date'])
    p['market'] = {'pr': 'points_rebounds', 'pa': 'points_assists', 'ra': 'rebounds_assists'}.get(prop['market'], prop['market'])
    target = next(p for roster in result['context']['rosters'].values() for p in roster
                  if name_key(p['player']) == name_key(prop['player']))
    return dict(prop=p, historical_games=translated, upcoming_features={
        'minutes': target['minutes_mean'], 'home': int(prop['team'] == result['context']['home']),
        'pace': result['context']['pace_per_team'],
        'fga': (target['fg2a_per36'] + target['fg3a_per36']) * target['minutes_mean'] / 36,
        'three_pa': target['fg3a_per36'] * target['minutes_mean'] / 36,
        'fta': target['fta_per36'] * target['minutes_mean'] / 36},
        model_outputs=dict(primary_side=result['direction'], primary_projection=result['projection'],
                           blind_projection=result['blind_model'].get('projection')))


def preservation_snapshot():
    root = Path(__file__).parent
    paths = list(root.glob('*.sqlite'))
    for folder in ('docs', 'diagnostics', 'models', 'architecture', 'configs'):
        paths += [p for p in (root / folder).rglob('*') if p.is_file()]
    paths += [root / p for p in ('identity_crosswalks.json', 'sources.json', 'benfrank_v44_governance.py')]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def preservation_check(before,after):
    """Original files must be identical; additive receipts/configs are permitted."""
    changed=[path for path,digest in before.items() if after.get(path)!=digest]
    return dict(verified=not changed,changed_or_removed_originals=changed,
                new_files=sorted(set(after)-set(before)))


def run(config_path, output, state_dir='auto_state', trials=25000, stress_trials=2000):
    if type(trials) is not int or not 25000 <= trials <= 50000:
        raise ValueError('25000_TO_50000_MAIN_TRIALS_REQUIRED')
    if type(stress_trials) is not int or not 1000 <= stress_trials <= 50000:
        raise ValueError('1000_TO_50000_STRESS_TRIALS_REQUIRED')
    config = json.loads(Path(config_path).read_text())
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    raw_config = Path(config_path).read_bytes()
    (root / 'input_config.json').write_bytes(raw_config)
    if config.get('screenshots'):
        import shutil
        retained=[]
        (root/'screenshots').mkdir()
        for index,value in enumerate(config['screenshots']):
            original=Path(value).resolve()
            target=root/'screenshots'/(str(index)+original.suffix.lower())
            shutil.copyfile(original,target);retained.append(str(target))
        config['screenshots']=retained
    protected = preservation_snapshot()
    started = now(); day = config['game_date']; dt.date.fromisoformat(day)
    mode = config.get('mode', 'future_discovery')
    if mode not in ('future_discovery', 'captured_forward_board', 'historical_research', 'manual_forward_prop',
                    'uploaded_props', 'native_category_test'):
        raise ValueError('UNKNOWN_AUTOMATIC_RUN_MODE')
    receipt = dict(version=VERSION, started_utc=started, mode=mode, game_date=day, stages=[], props=[],
                   config_sha256=hashlib.sha256(raw_config).hexdigest(), certified=False,
                   calibration_applied=False, accuracy_certified=False, original_rules_preserved=True,
                   old_warehouse_opened_for_writing=False, original_prediction_receipts_modified=False)
    store = Store(Path(state_dir).resolve())
    board = []
    manual_roles = None

    def stage(name, function):
        start = now(); timer = time.monotonic()
        try:
            value = function()
            state='FULL'
            if name=='optional_tracking_sources' and any(x.get('status')!='FULL' for x in value.values()):
                state='LIMITED'
            if name=='official_availability_and_public_projected_lineups' and (value[1].get('status')!='FULL' or value[0].get('projected_status')!='FULL'):
                state='LIMITED'
            receipt['stages'].append(dict(stage=name, status=state, started_utc=start,
                completed_utc=now(), timestamp=now(), source='Retained run inputs and source_manifest.json',
                execution_details='Function returned; data-specific limitations are retained in its receipt',
                limitations=[], duration_seconds=round(time.monotonic()-timer, 3)))
            print(encode(dict(stage=name, status=state)), flush=True)
            return value
        except Exception as error:
            receipt['stages'].append(dict(stage=name, status='BLOCKED', started_utc=start, completed_utc=now(),
                timestamp=now(), source='Retained inputs and source_manifest.json', execution_details='Function raised',
                limitations=[str(error)], exact_reason=type(error).__name__ + ': ' + str(error)))
            raise

    try:
        requested_deadline = config.get('pregame_cutoff_utc')
        if requested_deadline and instant(started) >= instant(requested_deadline):
            raise ValueError('REQUESTED_PREGAME_CUTOFF_ALREADY_PASSED')
        if mode == 'future_discovery':
            board, discovery = stage('native_prop_discovery', lambda: discover(store, day,
                config.get('max_props', 6), config.get('max_games', 3),
                **({'requested_prop': config['requested_prop']} if config.get('requested_prop') else {})))
            games = discovery['games']; write(root / 'discovery.json', discovery)
        elif mode == 'captured_forward_board':
            board,discovery=stage('supplied_capture_and_current_schedule',lambda:captured_board(store,config))
            games=discovery['games'];write(root/'discovery.json',discovery)
        elif mode == 'manual_forward_prop':
            board, discovery, manual_roles = stage('manual_line_with_verified_future_espn_schedule',
                lambda: resolve_manual_forward_prop(store, config))
            games = discovery['games']
            write(root / 'discovery.json', discovery)
        elif mode in ('uploaded_props', 'native_category_test'):
            from benfrank_dna_intake import resolve_batch
            board, discovery, manual_roles = stage('all_uploaded_props_schedule_identity',
                lambda: resolve_batch(store, config))
            games = discovery['games']
            write(root / 'discovery.json', discovery)
        else:
            board = config['props']
            games = stage('historical_schedule_acquisition', lambda: schedule(store, day))
            for i, p in enumerate(board):
                p.setdefault('snapshot_id', 'screenshot_20261106_' + str(i + 1))
                p.setdefault('platform', 'PrizePicks')
                matches = [g for g in games if p['opponent'] in (g['home'], g['away'])
                           and (not p.get('team') or p['team'] in (g['home'], g['away']))]
                if len(matches) != 1:
                    raise ValueError('HISTORICAL_SCREENSHOT_SCHEDULE_AMBIGUOUS:' + p['player'])
                g = matches[0]
                p.update(game_id=g['game_id'], espn_event_id=g['espn_event_id'], tipoff_utc=g['tipoff_utc'],
                         game_date=day, team=g['away'] if p['opponent'] == g['home'] else g['home'])
        if not board:
            raise ValueError('NO_SUPPORTED_FUTURE_EXACT_LINES_DISCOVERED')
        if len({p['snapshot_id'] for p in board}) != len(board):
            raise ValueError('DUPLICATE_SNAPSHOT_ID')
        for p in board:
            if (type(p['line']) not in (int, float) or not math.isfinite(p['line']) or p['line'] < 0
                    or Path(p['snapshot_id']).name != p['snapshot_id'] or p['snapshot_id'] in ('.', '..')):
                raise ValueError('INVALID_PROP_LINE_OR_SNAPSHOT_PATH')
            if requested_deadline:
                if instant(requested_deadline) >= instant(p['tipoff_utc']):
                    raise ValueError('REQUESTED_PREGAME_CUTOFF_MUST_PRECEDE_TIPOFF')
                p['requested_pregame_cutoff_utc'] = requested_deadline
        write(root / 'board.json', board)
        teams = sorted({p[k] for p in board for k in ('team', 'opponent')})
        sources, injury, identities = stage('depth_projected_roles_and_availability',
            (lambda: manual_roles) if manual_roles is not None
            else (lambda: capture_roles(store, teams, day)))
        from benfrank_dna_sources import supplement_roles, supplementary
        sources, injury = stage('official_availability_and_public_projected_lineups',
            lambda: supplement_roles(store, sources, injury, teams, day))
        write(root / 'sources.json', sources); write(root / 'injury.json', injury)
        if config.get('supplementary_sources', True):
            extra = stage('optional_tracking_sources', lambda: supplementary(store, day, {p['player'] for p in board}))
            write(root / 'supplementary_sources.json', extra)
        identity_errors = {}
        for p in board:
            matches = [x for x in sources['depths'].get(p['team'], {}).get('players', {}).values()
                       if name_key(x['player']) == name_key(p['player'])]
            if len(matches) != 1:
                identity_errors[p['snapshot_id']] = 'NO_UNIQUE_EXACT_NAME_IN_SOURCE_TEAM_DEPTH'
            else:
                p.update(player=matches[0]['player'], espn_player_id=matches[0]['id'])
        # Current depth is used only for acquisition identities in historical mode.
        write(root / 'resolved_board.json', board)
        from benfrank_dna_sources import career_baselines
        careers=stage('verified_career_aggregate_baselines',lambda:career_baselines(store,board,day))
        write(root/'career_baselines.json',careers)
        if mode == 'historical_research' and any(not p.get('original_cutoff_utc') for p in board):
            # Acquire the actual targets while original replay clocks are missing;
            # don't waste hundreds of roster requests for a gated replay.
            identities = {p['espn_player_id']: p['player'] for p in board if p.get('espn_player_id')}
        audit = stage('automatic_multiseason_player_logs', lambda: acquire_logs(store, identities, day,
                        seasons=config.get('max_seasons', 3)))
        write(root / 'gamelog_acquisition.json', audit)
        try:
            archive = stage('independent_pinned_nba_archive_fallback', lambda: acquire_mirror(store,
                            identities.values(), Path(__file__).with_name('sources.json')))
        except Exception as error:
            archive = dict(status='LIMITED', exact_reason=str(error),
                           alternative='Continue with independently validated ESPN records; no agreement invented')
        write(root / 'archive_acquisition.json', archive)
        # Legitimate direct official request; blocked responses remain source failures.
        official_url = 'https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json'
        try:
            store.fetch(official_url, 'NBA_DIRECT')
        except Exception as error:
            store.failure(official_url, error)
        cutoff = now()
        recon = stage('source_reconciliation', lambda: store.reconcile(cutoff, day,
                      strict_observed=mode != 'historical_research'))
        boxes = stage('complete_prior_team_boxes', lambda: acquire_recent_boxes(store, recon['records'], teams, day))
        cutoff = now()
        recon = stage('reconciliation_after_box_crosscheck', lambda: store.reconcile(cutoff, day,
                      strict_observed=mode != 'historical_research'))
        write(root / 'reconciliation.json', recon)
        write(root / 'prior_team_boxes.json', boxes)
        history_db = root / 'derived_history.sqlite'
        stage('v52_history_read_model', lambda: write_history(recon['records'], history_db))
        history = ProfileHistory(recon['records'], boxes)
        for p in board:
            entry = dict(prop=p, status='BLOCKED', direction=None, certified=False,
                         stage_results={s: dict(status='BLOCKED', exact_reason='UPSTREAM_INPUTS_NOT_READY',
                             source='run input and source manifest', timestamp=now(),
                             execution_details='Awaiting dependencies', limitations=['Upstream inputs pending']) for s in STAGES})
            receipt['props'].append(entry)
            windows={}; target=[]
            sid = p['snapshot_id']; folder = root / 'props' / sid; folder.mkdir(parents=True)
            def mark(name, status='FULL', **extra):
                entry['stage_results'][name] = dict(status=status, timestamp=now(),
                    source=extra.pop('source', 'Retained source_manifest.json and per-prop receipts'),
                    execution_details=extra.pop('execution_details', 'Executed; see attached numerical/source receipt'),
                    limitations=extra.pop('limitations', []), **extra)
            try:
                mark('exact_line_schedule', source=p.get('source_url', 'original branch screenshot transcription'),
                     line_authority=p.get('line_authority', 'UNKNOWN'),
                     native_platform_line_verified=p.get('line_authority') == 'PUBLIC_NATIVE_PRIZEPICKS_RESPONSE',
                     original_cutoff_known=bool(p.get('original_cutoff_utc')) if mode == 'historical_research' else True)
                if sid in identity_errors:
                    raise ValueError(identity_errors[sid])
                mark('player_identity', espn_player_id=p['espn_player_id'], method='EXACT_NORMALIZED_NAME_PLUS_CURRENT_DEPTH_ID')
                target = [r for r in recon['records'] if name_key(r['player']) == name_key(p['player'])]
                windows = historical_windows(target, p['market'], p['line'], day, p['opponent'])
                write(folder / 'historical_windows.json', windows)
                mark('automatic_acquisition', actual_games=len(target))
                conflicts = [c for c in recon['conflicts'] if c['player_key'] == name_key(p['player'])]
                mark('source_reconciliation', quarantined_games=len(conflicts),
                     independently_agreeing_games=sum(r['independent_sources_agree'] for r in target),
                     original_stat_publication_vintage_verified=False)
                mark('historical_windows', receipt=str(folder / 'historical_windows.json'),
                     current_season_games=windows['current_season']['n'],
                     policy='CURRENT_SEASON_L5_L10_L15_IF_AVAILABLE_PREVIOUS_H2H_CAREER')
                blockers = []
                if len(target) < 3:
                    blockers.append('FEWER_THAN_THREE_VERIFIED_PRIOR_APPEARANCES:' + str(len(target)))
                if mode == 'historical_research':
                    if not p.get('original_cutoff_utc'):
                        blockers.append('ORIGINAL_PREGAME_CUTOFF_NOT_RECORDED')
                    # A contemporary fetch must never impersonate an archived injury/depth snapshot.
                    blockers += ['ARCHIVED_PREGAME_DEPTH_OR_PROJECTED_ROLES_NOT_SUPPLIED',
                                 'ARCHIVED_PREGAME_AVAILABILITY_NOT_SUPPLIED']
                if blockers:
                    raise ValueError('; '.join(blockers))
                if instant(cutoff) >= instant(p['tipoff_utc']):
                    raise ValueError('ACTUAL_INFERENCE_CUTOFF_ALREADY_AFTER_TIPOFF')
                if requested_deadline and instant(now()) >= instant(requested_deadline):
                    raise ValueError('REQUESTED_PREGAME_CUTOFF_PASSED_DURING_ACQUISITION')
                game = next(g for g in games if g['game_id'] == p['game_id'])
                base = build_context(p, game, sources, history, boxes, cutoff, injury)
                write(folder / 'base_context.json', base)
                mark('player_profiles_matchup_roles', receipt=str(folder / 'base_context.json'))
                print(encode(dict(stage='start_prop', player=p['player'], market=p['market'], line=p['line'])), flush=True)
                result = run_one(p, base, sources, injury, history_db, trials, stress_trials,
                                 trace_dir=folder / 'trials', cutoff_utc=cutoff)
                mark('sequential_25000', trials=result['main_simulation']['trials_executed'],
                     proof=result['main_simulation']['trial_evidence'])
                mark('independent_blind_process', 'FULL' if result['blind_model'].get('independence_evidence',{}).get('verified') else 'BLOCKED',
                     proof=result['blind_model'].get('independence_evidence',{}),
                     limitations=[result['blind_model'].get('exact_blocker')] if result['blind_model'].get('exact_blocker') else [],
                     independently_validated_accuracy=False)
                target_profile = next(x for roster in result['context']['rosters'].values() for x in roster
                                      if name_key(x['player']) == name_key(p['player']))
                windows = historical_windows(target, p['market'], p['line'], day, p['opponent'], target_profile['minutes_mean'])
                for window in windows.values():
                    window['projection_minus_line'] = result['projection'] - p['line']
                result['historical_windows'] = windows
                result['career_baseline']=careers.get(p['player'],dict(status='LIMITED',exact_reason='NO_CAREER_AGGREGATE'))
                if result['career_baseline'].get('career_games'):
                    result['career_baseline']=dict(result['career_baseline'],
                        career_mean_minus_exact_line=result['career_baseline']['career_means'][p['market']]-p['line'],
                        available_exact_line_archive_games=windows['career_available']['n'])
                # Initial DNA receipt predates the model; retain it and append the model-attached version.
                write(folder / 'historical_windows_with_projection.json', windows)
                result['sensitivity'] = sensitivity(result['main_simulation'], p['line'])
                result['adversarial'] = dict(selected_side=result['direction'],
                    opposing_side='UNDER' if result['direction'] == 'OVER' else 'OVER',
                    tested_cases={k: dict(p_over_raw=v['p_over_raw'], trials=v['trials_executed'],
                        trace_sha256=v['trial_chain_sha256'], proof=v['trial_evidence'])
                        for k, v in result['stress_simulations'].items()},
                    scenario_side_flip=result['scenario_side_flip'], model_disagreement=result['model_disagreement'],
                    limitation='Assumption stresses, not empirically measured tracking opportunity/conversion')
                result['adversarial']['availability_in_out_cases']=result['main_simulation']['conditional_questionable_states']
                opposing=[]
                for name,case in result['stress_simulations'].items():
                    probability=case['p_over_raw']
                    if probability is not None:
                        opposing.append(dict(scenario=name,opposing_side_probability_raw=1-probability if result['direction']=='OVER' else probability,
                                             trials=case['trials_executed']))
                result['adversarial']['strongest_executed_opposing_case']=max(opposing,key=lambda x:x['opposing_side_probability_raw']) if opposing else None
                mark('adversarial_stress', receipt=result['adversarial'])
                mark('sensitivity', receipt=result['sensitivity'])
                dna = dna_report(dna_input(p, target, result)); write(folder / 'dna_100.json', dna)
                mark('player_dna_100', tested=len(dna['dna_100_test_results']),
                     available=sum(t['status'] != 'UNAVAILABLE' for t in dna['dna_100_test_results']),
                     receipt=str(folder / 'dna_100.json'))
                source_audit = dict(games=len(target), independently_agreeing_games=sum(r['independent_sources_agree'] for r in target),
                    reconciliation_sha256=sha(recon), source_documents=sorted({d for r in target for d in r['source_documents']}))
                result['source_audit'] = source_audit
                result['interrogation'] = interrogation(result, source_audit, folder / 'prediction.json')
                write(folder / 'interrogation_60.json', result['interrogation'])
                mark('interrogation_60', total=60, verified=result['interrogation']['verified_count'],
                     certified=result['interrogation']['certified'], receipt=str(folder / 'interrogation_60.json'))
                result['certified'] = False
                result['dna_repair_version'] = '20261113_1'
                from benfrank_dna_error import assess
                result['model_error'] = assess(Path(state_dir).resolve() / 'forward_ledger.sqlite', result)
                mark('model_error',result['model_error']['status'],receipt=result['model_error'],limitations=[result['model_error']['limitation']])
                from benfrank_dna_qualification import qualify
                result['ticket_qualification'] = qualify(result,injury,sources)
                mark('ticket_qualification',result['ticket_qualification']['status'],receipt=result['ticket_qualification'],limitations=result['ticket_qualification']['blockers'])
                from benfrank_dna_history import SCORING, SCORING_VERSION, SCORING_SOURCE
                result['scoring_formula'] = dict(weights=SCORING, version=SCORING_VERSION, source=SCORING_SOURCE,
                    verified_date='2026-11-13', overtime_included=True)
                if requested_deadline:
                    result['requested_pregame_cutoff_utc'] = requested_deadline
                    if instant(now()) >= instant(requested_deadline):
                        result['status'] = 'COMPLETED_AFTER_REQUESTED_CUTOFF_NOT_FORWARD_ELIGIBLE'
                # Freeze the entire comparison/stress/sensitivity receipt before entering cohort.
                save_receipt(folder / 'prediction.json', result)
                frozen = json.loads((folder / 'prediction.json').read_text())
                if frozen['status'] == 'COMPLETED_AFTER_REQUESTED_CUTOFF_NOT_FORWARD_ELIGIBLE':
                    raise ValueError('SIMULATION_COMPLETED_AFTER_REQUESTED_PREGAME_CUTOFF')
                if frozen['status'] != 'FORWARD_TEST_READY':
                    raise ValueError('SIMULATION_COMPLETED_AFTER_TIPOFF_CANNOT_FREEZE_FORWARD')
                ledger = Path(state_dir).resolve() / 'forward_ledger.sqlite'
                record_prediction(ledger, frozen)
                mark('pregame_freeze', ledger=str(ledger), receipt_sha256=frozen['receipt_sha256'],
                     issued_before_tipoff=True)
                mark('postgame_grading', 'LIMITED', ledger=str(ledger),
                     exact_reason='GAME_NOT_FINAL; scheduled grading reads immutable frozen receipt')
                entry.update(status='FORWARD_TEST_READY_UNCALIBRATED', direction=result['direction'],
                             projection=result['projection'], p_over_raw=result['main_simulation']['p_over_raw'],
                             blind_projection=result['blind_model'].get('projection'), model_disagreement=result['model_disagreement'],
                             scenario_side_flip=result['scenario_side_flip'],
                             ticket_qualification=result['ticket_qualification'],
                             prediction_receipt=str(folder / 'prediction.json'))
                from benfrank_dna_report import write_prop_report
                write_prop_report(folder / 'report.md', result)
            except Exception as error:
                entry['exact_blocker'] = type(error).__name__ + ': ' + str(error)
                # A sourced historical fallback can still issue a direction;
                # it does not impersonate the blocked numerical forecast.
                if entry['direction'] is None and 'windows' in locals():
                    baseline=next((windows[k] for k in ('current_season','previous_season','career_available')
                                   if windows.get(k,{}).get('n',0)>0),None)
                    if baseline:
                        entry.update(direction='OVER' if baseline['mean']>=p['line'] else 'UNDER',
                            direction_authority='HISTORICAL_MEAN_ONLY_FALLBACK_NOT_SIMULATION',
                            ticket_qualification=dict(qualified=False,primary=False,
                                blockers=[entry['exact_blocker']],guaranteed=False))
                for s in entry['stage_results'].values():
                    if s['status'] == 'BLOCKED':
                        s['exact_reason'] = entry['exact_blocker']
                # All 60 questions still receive an explicit state in blocked runs.
                if entry['stage_results']['interrogation_60']['status'] == 'BLOCKED':
                    from benfrank_interrogation_60 import evaluate, QUESTIONS
                    q = evaluate({key: dict(status='unavailable', answer=entry['exact_blocker']) for key, _ in QUESTIONS},
                        sport='NBA', player=p['player'], market=p['market'], line=p['line'],
                        cutoff_utc=p.get('original_cutoff_utc') or '')
                    write(folder / 'blocked_interrogation_60.json', q)
                    entry['stage_results']['interrogation_60'].update(
                        audit_executed=True, questions=60, verified=0, receipt=str(folder / 'blocked_interrogation_60.json'))
            write(folder / 'stage_receipt.json', entry)
            print(encode(dict(player=p['player'], status=entry['status'], direction=entry['direction'],
                              exact_blocker=entry.get('exact_blocker'))), flush=True)
    except Exception as error:
        receipt['fatal_blocker'] = type(error).__name__ + ': ' + str(error)
    finally:
        store.db.commit()
        write(root / 'source_manifest.json', store.manifest())
        store.db.close()
        receipt['completed_utc'] = now()
        receipt['preservation_check'] = preservation_check(protected,preservation_snapshot())
        receipt['preservation_verified'] = receipt['preservation_check']['verified']
        receipt['protected_file_hashes'] = protected
        receipt['predictions_frozen_before_tipoff'] = sum(p['status'] == 'FORWARD_TEST_READY_UNCALIBRATED' for p in receipt['props'])
        receipt['all_requested_props_executed'] = bool(receipt['props']) and len(receipt['props']) == len(board) and all(
            p['status'] == 'FORWARD_TEST_READY_UNCALIBRATED' for p in receipt['props'])
        if 'discovery' in locals() and discovery.get('rejected'):
            receipt['intake_rejections']=discovery['rejected']
            receipt['all_requested_props_executed']=False
        from benfrank_dna_qualification import rank
        write(root/'ticket_ranking.json',rank(receipt['props']))
        receipt['status'] = 'FORWARD_RESEARCH_EXECUTED' if receipt['all_requested_props_executed'] else 'INCOMPLETE_EXACT_BLOCKERS_RECORDED'
        write(root / 'execution_receipt.json', receipt)
        report_lines = ['# 🏀 BENFRANK execution readiness', '',
            f"Run: {VERSION} | {mode} | {day}", '',
            f"**{receipt['status']}** — {receipt['predictions_frozen_before_tipoff']} predictions frozen before tipoff.",
            'Accuracy certification: **false**. Probability calibration: **not applied**.', '',
            '| Player | Market / line | Side | State |', '|---|---|---|---|']
        for p in receipt['props']:
            report_lines.append(f"| {p['prop']['player']} | {p['prop']['market']} {p['prop']['line']} | {p['direction'] or '—'} | {p['status']} |")
        for p in receipt['props']:
            report_lines += ['', '## ' + p['prop']['player'], '', '| Stage | State | Exact reason / receipt |', '|---|---|---|']
            for name, s in p['stage_results'].items():
                report_lines.append(f"| {name} | {s['status']} | {s.get('exact_reason', s.get('receipt', 'See stage_receipt.json'))} |")
        if receipt.get('fatal_blocker'):
            report_lines += ['', '**Fatal blocker:** ' + receipt['fatal_blocker']]
        report_lines += ['', 'Original warehouse writes: **0**. Protected governing/data/receipt hash check: **' + str(receipt['preservation_verified']) + '**.',
                         'Every raw capture, provider failure, quarantined disagreement and simulated trial is retained in the run/state artifacts.',
                         'Unmeasured tracking inputs, independently validated Blind AI accuracy, complete career coverage and new forward calibration remain unverified.']
        (root / 'readiness_report.md').write_text('\n'.join(report_lines) + '\n')
    print(encode(dict(status=receipt['status'], frozen=receipt['predictions_frozen_before_tipoff'],
                      fatal_blocker=receipt.get('fatal_blocker'))), flush=True)
    return receipt, 0 if receipt['all_requested_props_executed'] and receipt['preservation_verified'] else 2
