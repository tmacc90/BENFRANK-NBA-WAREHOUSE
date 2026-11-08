"""One acquisition-to-freeze workflow, preserving all legacy execution modes."""
import collections
import datetime as dt
import hashlib
import json
import math
import re
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
from benfrank_lineup_acquisition import acquire_history_context
from benfrank_lineup_mirror import history_context as mirror_history_context, season_end_for_date

VERSION = 'BENFRANK_AUTO_ACQUIRE_TO_FREEZE_1'
STAGES = ('exact_line_schedule', 'player_identity', 'automatic_acquisition', 'source_reconciliation',
          'historical_windows', 'player_profiles_matchup_roles', 'sequential_25000', 'independent_blind_process',
          'adversarial_stress', 'sensitivity', 'player_dna_100', 'interrogation_60', 'pregame_freeze', 'postgame_grading')


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')


def historical_windows(rows, market, line, day):
    rows = sorted((r for r in rows if r['date'] < day), key=lambda r: (r['date'], r['game_id']), reverse=True)
    result = {}
    sy = season_start(day)
    groups = [('L' + str(n), rows[:n], n) for n in (5, 10, 15, 20, 25, 32, 52)]
    groups += [('current_season', [r for r in rows if r['season'].startswith(str(sy))], None),
               ('previous_season', [r for r in rows if r['season'].startswith(str(sy - 1))], None),
               ('available_archive', rows, None)]
    for key, group, n in groups:
        w = window_summary(group, market, line, n)
        for old, new in (('more', 'over_count'), ('less', 'under_count'), ('push', 'push_count'),
                         ('more_rate', 'over_rate'), ('less_rate', 'under_rate')):
            w[new] = w.pop(old)
        w.update(requested=n, game_ids=[r['game_id'] for r in group])
        result[key] = w
    return result


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
                           blind_projection=result['blind_model']['projection']))


def lineup_game_specs(rows):
    """Exact NBA game IDs from reconciled pre-cutoff observations for mirror fallback."""
    specs = []
    seen = set()
    ordered = sorted(rows, key=lambda r: (r.get('date', ''), r.get('game_id', '')), reverse=True)
    for row in ordered:
        candidates = []
        direct = row.get('source_game_id')
        if direct:
            candidates.append(str(direct))
        for values in (row.get('source_game_ids') or {}).values():
            candidates.extend(map(str, values or []))
        for gid in candidates:
            if not re.fullmatch(r'\d{10}', gid) or gid in seen:
                continue
            specs.append({'game_id': gid, 'season': season_end_for_date(row['date'])})
            seen.add(gid)
    return specs


def preservation_snapshot():
    root = Path(__file__).parent
    paths = list(root.glob('*.sqlite'))
    for folder in ('docs', 'diagnostics', 'models', 'architecture', 'configs'):
        paths += [p for p in (root / folder).rglob('*') if p.is_file()]
    paths += [root / p for p in ('identity_crosswalks.json', 'sources.json', 'benfrank_v44_governance.py')]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


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
    protected = preservation_snapshot()
    started = now(); day = config['game_date']; dt.date.fromisoformat(day)
    mode = config.get('mode', 'future_discovery')
    if mode not in ('future_discovery', 'captured_forward_board', 'historical_research',
                     'manual_forward_prop', 'manual_forward_board'):
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
            receipt['stages'].append(dict(stage=name, status='EXECUTED', started_utc=start,
                                           completed_utc=now(), duration_seconds=round(time.monotonic()-timer, 3)))
            print(encode(dict(stage=name, status='EXECUTED')), flush=True)
            return value
        except Exception as error:
            receipt['stages'].append(dict(stage=name, status='FAILED', started_utc=start, completed_utc=now(),
                                           exact_reason=type(error).__name__ + ': ' + str(error)))
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
        elif mode == 'manual_forward_board':
            board = [dict(p) for p in config.get('props', [])]
            games = stage('manual_board_verified_future_schedule', lambda: schedule(store, day))
            if not board:
                raise ValueError('MANUAL_FORWARD_BOARD_REQUIRES_PROPS')
            for i, p in enumerate(board):
                for required in ('player', 'market', 'line', 'team', 'opponent', 'line_capture_utc'):
                    if required not in p:
                        raise ValueError('MANUAL_FORWARD_BOARD_MISSING_' + required.upper())
                matches = [g for g in games
                           if {g['home'], g['away']} == {p['team'], p['opponent']}
                           and instant(g['tipoff_utc']) > instant(started)
                           and g.get('status', {}).get('state') == 'pre']
                if len(matches) != 1:
                    raise ValueError('MANUAL_FORWARD_BOARD_SCHEDULE_AMBIGUOUS:' + p['player'])
                g = matches[0]
                if instant(p['line_capture_utc']) >= instant(g['tipoff_utc']):
                    raise ValueError('MANUAL_LINE_CAPTURE_NOT_PREGAME:' + p['player'])
                p.setdefault('snapshot_id', 'manual_board_' + str(i + 1))
                p.setdefault('platform', 'PrizePicks')
                p.setdefault('line_authority', 'USER_SUPPLIED_SCREENSHOT_FROZEN_LINE')
                p.setdefault('source_url', 'user_supplied_screenshot')
                p.setdefault('source_document', p['snapshot_id'])
                p.update(game_id=g['game_id'], espn_event_id=g['espn_event_id'],
                         tipoff_utc=g['tipoff_utc'], game_date=day)
            write(root / 'discovery.json', {
                'mode': 'manual_forward_board',
                'games': games,
                'line_authority': 'USER_SUPPLIED_SCREENSHOT_FROZEN_LINE',
                'native_platform_line_recheck': False,
            })
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
        write(root / 'sources.json', sources); write(root / 'injury.json', injury)
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
        if mode == 'historical_research' and any(not p.get('original_cutoff_utc') for p in board):
            # Acquire the actual targets while original replay clocks are missing;
            # don't waste hundreds of roster requests for a gated replay.
            identities = {p['espn_player_id']: p['player'] for p in board if p.get('espn_player_id')}
        audit = stage('automatic_multiseason_player_logs', lambda: acquire_logs(store, identities, day,
                        seasons=config.get('max_seasons', 3)))
        write(root / 'gamelog_acquisition.json', audit)
        archive = stage('independent_pinned_nba_archive_fallback', lambda: acquire_mirror(store,
                        identities.values(), Path(__file__).with_name('sources.json')))
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
                         stage_results={s: dict(status='BLOCKED', exact_reason='UPSTREAM_INPUTS_NOT_READY') for s in STAGES})
            receipt['props'].append(entry)
            sid = p['snapshot_id']; folder = root / 'props' / sid; folder.mkdir(parents=True)
            def mark(name, status='EXECUTED', **extra):
                entry['stage_results'][name] = dict(status=status, **extra)
            try:
                mark('exact_line_schedule', source=p.get('source_url', 'original branch screenshot transcription'),
                     line_authority=p.get('line_authority', 'UNKNOWN'),
                     native_platform_line_verified=p.get('line_authority') == 'PUBLIC_NATIVE_PRIZEPICKS_RESPONSE',
                     original_cutoff_known=bool(p.get('original_cutoff_utc')) if mode == 'historical_research' else True)
                if sid in identity_errors:
                    raise ValueError(identity_errors[sid])
                mark('player_identity', espn_player_id=p['espn_player_id'], method='EXACT_NORMALIZED_NAME_PLUS_CURRENT_DEPTH_ID')
                target = [r for r in recon['records'] if name_key(r['player']) == name_key(p['player'])]
                windows = historical_windows(target, p['market'], p['line'], day)
                write(folder / 'historical_windows.json', windows)
                mark('automatic_acquisition', actual_games=len(target))
                conflicts = [c for c in recon['conflicts'] if c['player_key'] == name_key(p['player'])]
                mark('source_reconciliation', quarantined_games=len(conflicts),
                     independently_agreeing_games=sum(r['independent_sources_agree'] for r in target),
                     original_stat_publication_vintage_verified=False)
                mark('historical_windows', receipt=str(folder / 'historical_windows.json'),
                     l52_available=windows['L52']['n'], l52_complete=windows['L52']['n'] == 52)
                # Additive Stage 33-35 evidence. The validated public possession
                # mirror is preferred in cloud runners; direct NBA/CDN remains a fallback.
                # Neither route may impersonate FULL when its validation/sample gate fails.
                lineup_root = Path(state_dir).resolve() / 'lineup_cache'
                lineup_attempts = []
                lineup_evidence = None
                try:
                    specs = lineup_game_specs(target)
                    mirror = mirror_history_context(
                        p['player'], specs, lineup_root,
                        max_games=int(config.get('lineup_history_games', 12)))
                    lineup_attempts.append({'route': 'SPORTSDATAVERSE_NBA_STATS_MIRROR',
                                            'quality': mirror.get('quality'),
                                            'upstream_commit': mirror.get('upstream_commit')})
                    lineup_evidence = mirror
                except Exception as error:
                    lineup_attempts.append({'route': 'SPORTSDATAVERSE_NBA_STATS_MIRROR',
                                            'error': type(error).__name__ + ': ' + str(error)})
                if not lineup_evidence or lineup_evidence.get('quality') not in ('FULL', 'FALLBACK'):
                    try:
                        direct = acquire_history_context(
                            p['player'], target, lineup_root,
                            max_games=int(config.get('lineup_history_games', 12)))
                        lineup_attempts.append({'route': 'NBA_CDN_OR_STATS_DIRECT',
                                                'quality': direct.get('quality')})
                        lineup_evidence = direct
                    except Exception as error:
                        lineup_attempts.append({'route': 'NBA_CDN_OR_STATS_DIRECT',
                                                'error': type(error).__name__ + ': ' + str(error)})
                if not lineup_evidence:
                    lineup_evidence = {'player': p['player'], 'quality': 'LIMITED'}
                lineup_evidence['acquisition_routes_attempted'] = lineup_attempts
                if lineup_evidence.get('quality') not in ('FULL', 'FALLBACK', 'LIMITED'):
                    lineup_evidence['quality'] = 'LIMITED'
                if not lineup_evidence.get('stage_receipts'):
                    reason = '; '.join(x.get('error', x.get('route', 'UNKNOWN')) for x in lineup_attempts)
                    lineup_evidence.update(
                        requested_games=0, usable_games=0, games=[], teammates={}, five_man_units={},
                        target={'closing_share': None},
                        stage_receipts={
                            '33': {'stage': 'Teammate WOWY', 'execution': 'EXECUTED',
                                   'quality': 'LIMITED', 'exact_reason': reason},
                            '34': {'stage': 'Five-Man Lineups', 'execution': 'EXECUTED',
                                   'quality': 'LIMITED', 'exact_reason': reason},
                            '35': {'stage': 'Closing Lineup', 'execution': 'EXECUTED',
                                   'quality': 'LIMITED', 'exact_reason': reason},
                        })
                write(folder / 'lineup_evidence.json', lineup_evidence)
                for number, key in (('33', 'stage_33_teammate_wowy'),
                                    ('34', 'stage_34_five_man_lineups'),
                                    ('35', 'stage_35_closing_lineup')):
                    stage_receipt = dict(lineup_evidence['stage_receipts'][number])
                    stage_receipt.pop('execution', None)
                    entry['stage_results'][key] = dict(
                        status='EXECUTED', receipt=str(folder / 'lineup_evidence.json'),
                        **stage_receipt)
                blockers = []
                if windows['L52']['n'] < 52:
                    blockers.append('L52_INCOMPLETE_REAL_APPEARANCES:' + str(windows['L52']['n']))
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
                base['lineup_evidence'] = lineup_evidence
                write(folder / 'base_context.json', base)
                mark('player_profiles_matchup_roles', receipt=str(folder / 'base_context.json'))
                print(encode(dict(stage='start_prop', player=p['player'], market=p['market'], line=p['line'])), flush=True)
                result = run_one(p, base, sources, injury, history_db, trials, stress_trials,
                                 trace_dir=folder / 'trials', cutoff_utc=cutoff)
                mark('sequential_25000', trials=result['main_simulation']['trials_executed'],
                     proof=result['main_simulation']['trial_evidence'])
                mark('independent_blind_process', proof=result['blind_model']['independence_evidence'],
                     independently_validated_accuracy=False)
                result['historical_windows'] = windows
                result['sensitivity'] = sensitivity(result['main_simulation'], p['line'])
                result['adversarial'] = dict(selected_side=result['direction'],
                    opposing_side='UNDER' if result['direction'] == 'OVER' else 'OVER',
                    tested_cases={k: dict(p_over_raw=v['p_over_raw'], trials=v['trials_executed'],
                        trace_sha256=v['trial_chain_sha256'], proof=v['trial_evidence'])
                        for k, v in result['stress_simulations'].items()},
                    scenario_side_flip=result['scenario_side_flip'], model_disagreement=result['model_disagreement'],
                    limitation='Assumption stresses, not empirically measured tracking opportunity/conversion')
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
                mark('postgame_grading', 'PREPARED_PENDING_FINAL', ledger=str(ledger),
                     exact_reason='GAME_NOT_FINAL; scheduled grading reads immutable frozen receipt')
                entry.update(status='FORWARD_TEST_READY_UNCALIBRATED', direction=result['direction'],
                             projection=result['projection'], p_over_raw=result['main_simulation']['p_over_raw'],
                             blind_projection=result['blind_model']['projection'], model_disagreement=result['model_disagreement'],
                             scenario_side_flip=result['scenario_side_flip'],
                             prediction_receipt=str(folder / 'prediction.json'))
            except Exception as error:
                entry['exact_blocker'] = type(error).__name__ + ': ' + str(error)
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
        receipt['preservation_verified'] = preservation_snapshot() == protected
        receipt['protected_file_hashes'] = protected
        receipt['predictions_frozen_before_tipoff'] = sum(p['status'] == 'FORWARD_TEST_READY_UNCALIBRATED' for p in receipt['props'])
        receipt['all_requested_props_executed'] = bool(receipt['props']) and len(receipt['props']) == len(board) and all(
            p['status'] == 'FORWARD_TEST_READY_UNCALIBRATED' for p in receipt['props'])
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
