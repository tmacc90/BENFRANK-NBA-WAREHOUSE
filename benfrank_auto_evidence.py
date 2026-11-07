"""Executable trace validation, line ladders and an honest 60-question bridge."""
import collections
import gzip
import hashlib
import json
import math
import copy
import random
from pathlib import Path

from benfrank_interrogation_60 import evaluate, QUESTIONS
from benfrank_auto_history import sha


def verify_trace(path, simulation, line):
    chain = hashlib.sha256(); counts = collections.Counter(); n = 0
    with gzip.open(path, 'rb') as stream:
        for raw in stream:
            index, seed, score, value = json.loads(raw)
            if index != n or seed != simulation['seed'] + n * 7919:
                raise ValueError('TRIAL_SEQUENCE_OR_SEED_CONFLICT')
            if (not isinstance(score, dict) or len(score) != 2
                    or any(type(v) is not int or v < 0 for v in score.values())
                    or len(set(score.values())) != 2):
                raise ValueError('INCOMPLETE_OR_INVALID_SIMULATED_FINAL')
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value)):
                raise ValueError('INVALID_TRIAL_TARGET_VALUE')
            label = 'VOID' if value is None else 'OVER' if value > line else 'UNDER' if value < line else 'PUSH'
            counts[label] += 1; chain.update(raw); n += 1
    if n != simulation['trials_executed'] or chain.hexdigest() != simulation['trial_chain_sha256']:
        raise ValueError('TRIAL_COUNT_OR_HASH_CONFLICT')
    for label, field in (('OVER', 'over_count'), ('UNDER', 'under_count'), ('PUSH', 'push_count'), ('VOID', 'void_count')):
        if counts[label] != simulation[field]:
            raise ValueError('TRIAL_OUTCOME_COUNT_CONFLICT')
    return dict(verified=True, trials_executed=n, seed=simulation['seed'],
                trials_sha256=chain.hexdigest(), input_sha256=simulation['context_sha256'],
                compressed_file_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                trace_file=str(path), counts=dict(counts),
                meaning='Trace sequence, seeds, outcomes and final-score integrity reproduced; not accuracy certification')


def reproduce_trace_samples(context, simulation, player, market, path):
    """Re-execute complete games from recorded context/seeds after serialization."""
    from benfrank_v52_early import scenarios
    from benfrank_v44_twon import simulate_game, market_value
    context=copy.deepcopy(context)
    # The automatic builder constructs home then away. JSON key sorting must
    # not change the random-draw order when restoring the frozen context.
    context['rosters']={t:context['rosters'][t] for t in (context['home'],context['away'])}
    seed=simulation['seed'];n=simulation['trials_executed']
    selected={0,n//4,n//2,(3*n)//4,n-1};expected={}
    with gzip.open(path,'rt') as stream:
        for raw in stream:
            row=json.loads(raw)
            if row[0] in selected:expected[row[0]]=row
    cases=scenarios(context,seed^0x5200);chooser=random.Random(seed);checked=[]
    for i in range(n):
        c,prepared=cases[chooser.randrange(len(cases))]
        if i not in selected:continue
        game=simulate_game(c,seed+i*7919,prepared=prepared,max_overtimes=12,
                           max_shooting_sequences=32,last_player_exception=True)
        target=game['stats'].get(player)
        value=market_value(target,market) if target and target['minutes']>0 else None
        if [i,seed+i*7919,game['score'],value]!=expected.get(i):
            raise ValueError('DETERMINISTIC_PHYSICAL_TRIAL_REPLAY_CONFLICT:'+str(i))
        checked.append(i)
    return dict(verified=True, complete_games_reexecuted=len(checked), trial_indices=checked,
                meaning='Independent full-game reexecution of predeclared trace samples, not accuracy validation')


def sensitivity(simulation, line):
    histogram = {float(k): n for k, n in simulation['histogram'].items()}
    def at(threshold):
        over = sum(n for v, n in histogram.items() if v > threshold)
        under = sum(n for v, n in histogram.items() if v < threshold)
        push = sum(n for v, n in histogram.items() if v == threshold)
        p = over / (over + under) if over + under else None
        return dict(line=threshold, over=over, under=under, push=push,
                    void=simulation['void_count'], p_over_raw=p,
                    side='OVER' if p is not None and p >= .5 else 'UNDER' if p is not None else None)
    requested = sorted({max(0, line + d) for d in (-2, -1, -.5, 0, .5, 1, 2)})
    # Search the whole simulated support; the +0.5/+1.0 tests share genuine draws.
    support = sorted({v for v in histogram} | {v + .5 for v in histogram})
    flip = next((x for x in (at(v) for v in support) if x['side'] == 'UNDER'), None)
    return dict(ladder=[at(v) for v in requested], first_under_line_in_simulated_support=flip,
                method='RETHRESHOLD_THE_SAME_EXECUTED_MAIN_TRIALS; NO_EXTRA_TRIALS_CLAIMED',
                calibration_applied=False, most_favorable_alternative_requires_payout_comparison=True)


def interrogation(result, source_audit, receipt_path):
    prop = result['prop']; answers = {}
    def verified(key, value, source, measurement):
        answers[key] = dict(status='verified', answer=str(value), source=source,
                            measurement=str(measurement), execution_receipt=str(receipt_path))
    verified('exact_line', prop['line'], prop.get('source_url', 'original screenshot manifest'), prop['snapshot_id'])
    verified('cutoff', result['analysis_cutoff_utc'], 'actual acquisition and inference clocks', result['analysis_cutoff_utc'])
    windows = result['historical_windows']
    for key in ('windows', 'records', 'push_counts', 'analytical_findings', 'findings', 'historical_verification'):
        verified(key, windows, 'reconciled player-game observations', source_audit['reconciliation_sha256'])
    verified('data', source_audit, 'append-only raw source store', source_audit['reconciliation_sha256'])
    verified('documentation', source_audit['source_documents'], 'raw response manifest', source_audit['reconciliation_sha256'])
    main = result['main_simulation']
    if main.get('trial_evidence', {}).get('verified'):
        for key in ('simulation', 'probability_indicators', 'statistical_indicators'):
            verified(key, dict(trials=main['trials_executed'], p_over_raw=main['p_over_raw'],
                               void=main['void_count'], quantiles=main['quantiles']),
                     'existing v5.2 complete-game simulator; raw uncalibrated shares', main['trial_chain_sha256'])
    blind = result['blind_model']
    verified('predictive_intelligence', blind, 'separate numerical ridge worker', blind['input_sha256'])
    # The governing blind_ai question requires independently validated accuracy.
    answers['blind_ai'] = dict(status='unavailable', answer='Process separation verified; independent accuracy validation absent',
                              source='blind process receipt', measurement=blind['input_sha256'], execution_receipt=str(receipt_path))
    for key in ('workload', 'availability', 'opponent_dna', 'game_script'):
        verified(key, dict(roles=result['context']['early_role_evidence'],
                           pace=result['context']['pace_per_team'],
                           team_rates=result['context']['team_rates'],
                           limitations=result['context']['limitations']),
                 'observed prior boxes and depth; explicit unvalidated early scenarios', main['context_sha256'])
    for key in ('adversarial', 'adversarial_verification', 'confidence_assessment', 'statistical_validation'):
        verified(key, result['adversarial'], 'executed downside and upside complete-game traces',
                 sha(result['adversarial']))
    for key in ('sensitivity', 'flip_point'):
        verified(key, result['sensitivity'], 'rethresholded executed main trials', main['trial_chain_sha256'])
    for key in ('decision_intelligence', 'decision_synthesis', 'final_decision'):
        verified(key, result['direction'], 'uncalibrated higher main-model side share; disagreements retained', main['trial_chain_sha256'])
    if source_audit['independently_agreeing_games'] == source_audit['games'] and source_audit['games']:
        for key in ('confirmation', 'corroboration'):
            verified(key, source_audit, 'ESPN vs pinned NBA Stats archive', source_audit['reconciliation_sha256'])
    for key, _ in QUESTIONS:
        if key not in answers:
            answers[key] = dict(status='unavailable', answer='No executed, source-backed measurement satisfies this question')
    answers['calibration'] = dict(status='unavailable', answer='No qualifying new forward calibration cohort; raw shares only')
    r = evaluate(answers, sport='NBA', player=prop['player'], market=prop['market'], line=prop['line'],
                 cutoff_utc=result['analysis_cutoff_utc'], preferred_side=result['direction'])
    r['accuracy_or_calibration_certification'] = False
    return r
