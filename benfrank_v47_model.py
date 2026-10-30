"""Availability-aware, variable-minute sequential 5-on-5 challenger.

Confirmed-out players cannot enter a scenario roster or any substitution path.
Unknown is not healthy. Every executed trial still simulates the complete game;
an inactive target contributes VOID, not an artificial UNDER result.
"""
import collections
import copy
import datetime as dt
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

from acquire_history import name_key, team_key
from benfrank_v44_twon import validate, prepare_game, simulate_game, market_value, MARKETS
from benfrank_v45_evidence import digest
from benfrank_v46_reconstructed_replay import allocate_minutes
from benfrank_v47_availability import observation, UNKNOWN
from benfrank_v47_history import offered_roster


def fit_availability(history, snapshots, archives, documents):
    counts=collections.defaultdict(lambda:[0,0]);seen=set();seen_games=set();excluded=collections.Counter()
    for s in sorted(snapshots,key=lambda s:(s['captured_at'],s['snapshot_id'])):
        if not '2026-02-01'<=s['game_date']<='2026-04-12':
            raise ValueError('ONLY_DECLARED_DEVELOPMENT_DATES_MAY_FIT_AVAILABILITY')
        gid=s['game_id'];g=history.schedule[gid];home,away=team_key(g['home_team_tricode']),team_key(g['away_team_tricode'])
        if gid in seen_games:continue
        seen_games.add(gid)
        report=archives.get(s['captured_at'])
        if report is None:
            excluded['NO_ORIGINAL_REPORT']+=1;continue
        through=(dt.date.fromisoformat(s['game_date'])-dt.timedelta(days=2)).isoformat()
        for team in (home,away):
            for source_name in offered_roster(documents[s['source_file']],s,team):
                player=history.canonical(source_name);key=(s['game_date'],team,name_key(player))
                if key in seen:continue
                seen.add(key)
                prior=history.prior(player,through,12)
                if not prior:
                    excluded['NO_PRIOR_IDENTITY_FOR_AVAILABILITY_LABEL']+=1;continue
                status=observation(report,s['game_date'],home,away,team,player)['status']
                role='CORE' if statistics.mean(r['minutes'] for r in prior[:5])>=20 else 'BENCH'
                actual=history.actual.get((name_key(player),s['game_date'],team))
                played=int(actual is not None)
                for bucket in (status+'|'+role,status+'|ALL'):
                    counts[bucket][0]+=played;counts[bucket][1]+=1
    model={'method':'DEVELOPMENT_ONLY_BETA_SHRUNK_OFFERED_PLAYER_AVAILABILITY',
           'counts':dict(counts),'development_player_games':len(seen),'exclusions':dict(excluded),
           'unlisted_players_cleared':False,'certification':'NOT_CERTIFIED'}
    return model


def availability_probability(model,status,role):
    if status=='Out':return 0.0
    counts=model['counts'].get(status+'|'+role) or model['counts'].get(status+'|ALL')
    if not counts:
        counts=model['counts'].get(UNKNOWN+'|'+role) or model['counts'].get(UNKNOWN+'|ALL')
    if not counts:raise ValueError('DEVELOPMENT_AVAILABILITY_PRIOR_REQUIRED')
    played,total=counts
    return (played+1)/(total+2)


def build_context(history,snapshot,document,archives,availability_model):
    date=dt.date.fromisoformat(snapshot['game_date']);through=(date-dt.timedelta(days=2)).isoformat()
    start_year=date.year if date.month>=7 else date.year-1
    game=history.schedule[snapshot['game_id']]
    home,away=team_key(game['home_team_tricode']),team_key(game['away_team_tricode'])
    if {home,away}!={snapshot['team'],snapshot['opponent']}:
        raise ValueError('OFFICIAL_SCHEDULE_AND_CAPTURE_TEAM_CONFLICT')
    report=archives.get(snapshot['captured_at'])
    if report is None:raise ValueError('ORIGINAL_PREGAME_OFFICIAL_REPORT_REQUIRED')
    if report['issues']:raise ValueError('UNRESOLVED_OFFICIAL_INJURY_TABLE_PARSE_ISSUES')
    rosters,rates,paces,pace_sds,features,unknowns={},{},[],[],[],[]
    for team in (home,away):
        names={history.canonical(n) for n in offered_roster(document,snapshot,team)}
        group=report['game_team_reports'].get(snapshot['game_date']+'|'+away+'@'+home+'|'+team)
        if group:names.update(history.canonical(r['player']) for r in group['players'].values())
        source_mode='PUBLISHED_PREGAME_PROP_ROSTER_PLUS_ORIGINAL_OFFICIAL_REPORT'
        if len(names)<7:
            dates=sorted({r['date'] for r in history.by_team[team] if r['date']<=through},reverse=True)[:8]
            names.update(r['player'] for r in history.by_team[team] if r['date'] in dates)
            source_mode='PRIOR_TEAM_ROSTER_FALLBACK_WITH_UNVERIFIED_CURRENT_MEMBERSHIP'
        if team==snapshot['team']:names.add(history.canonical(snapshot['player']))
        profiles=[]
        for name in sorted(names):
            p=history.profile(name,through,start_year)
            obs=observation(report,snapshot['game_date'],home,away,team,p['player'])
            role='CORE' if p['minutes_mean']>=20 else 'BENCH'
            probability=availability_probability(availability_model,obs['status'],role)
            p.update(availability_status=obs['status'],availability_observation=obs,
                     probability_played=probability,roster_source=source_mode)
            profiles.append(p)
        target=history.canonical(snapshot['player'])
        profiles.sort(key=lambda p:(p['player']==target and team==snapshot['team'],p['minutes_mean']*p['probability_played'],p['player']),reverse=True)
        profiles=profiles[:15]
        if len([p for p in profiles if p['probability_played']>0])<7:
            raise ValueError('INSUFFICIENT_SOURCE_BACKED_NON_OUT_ROTATION')
        weights={p['player']:p['minutes_mean']*p['probability_played'] for p in profiles}
        targets=allocate_minutes(weights)
        for p in profiles:
            p['minutes_target']=targets[p['player']]
            if p['max_feature_game_date']:features.append(p['max_feature_game_date'])
            if p['availability_status'] in (UNKNOWN,'Questionable','Doubtful'):
                unknowns.append({'team':team,'player':p['player'],'status':p['availability_status']})
        rosters[team]=profiles
        r,pace,sd,dates=history.team_rates(team,through);rates[team]=r;paces.append(pace);pace_sds.append(sd);features.extend(dates)
    context={'game_id':snapshot['game_id'],'game_date':snapshot['game_date'],'tipoff_utc':snapshot['tipoff_utc'],
        'snapshot_id':snapshot['snapshot_id'],'platform':snapshot['platform'],'line_capture_utc':snapshot['captured_at'],
        'home':home,'away':away,'rosters':rosters,'team_rates':rates,'pace_per_team':max(75,min(125,statistics.mean(paces))),
        'pace_sd':max(1,statistics.mean(pace_sds)),'pace_source':'PRIOR_OBSERVED_BOX_SCORE_POSSESSION_ESTIMATOR',
        'pace_asof':through+'T23:59:59+00:00','history_through_date':through,'max_feature_game_date':max(features),
        'input_mode':'RECONSTRUCTED_ASOF_WITH_ORIGINAL_OFFICIAL_AVAILABILITY',
        'constructed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'official_report_time_utc':report['report_time_utc'],
        'official_report_sha256':report['source_pdf_sha256'],'unknown_or_uncertain_availability':unknowns,
        'availability_model_sha256':hashlib.sha256(json.dumps(availability_model,sort_keys=True).encode()).hexdigest(),
        'source_hashes':history.source_hashes,'certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET',
        'limitations':['Secondary public line/roster publication is not native platform authentication',
                       'Unknown material availability blocks FULL until authoritative final clearance',
                       'Minute allocation and box-score possession estimates remain model forecasts, not observed rotations']}
    if context['max_feature_game_date']>through:raise ValueError('FUTURE_OR_TARGET_GAME_ENTERED_FEATURES')
    validate(context)
    return context


def rotation_scenarios(context,count=256,seed=1):
    rng=random.Random(seed);scenarios=[];rejected_draws=0
    for _ in range(count):
        scenario={**context,'rosters':{}}
        for team in (context['home'],context['away']):
            active=[]
            for attempt in range(1000):
                active=[dict(p) for p in context['rosters'][team] if p['availability_status']!='Out' and rng.random()<p['probability_played']]
                if len(active)>=7:break
                rejected_draws+=1
            if len(active)<7:raise ValueError('UNABLE_TO_DRAW_LEGAL_NON_OUT_ROTATION')
            weights={}
            for p in active:
                samples=p['historical_minutes']
                residual=rng.choice(samples)-statistics.mean(samples) if samples else rng.uniform(-6,6)
                weights[p['player']]=min(48,max(2,p['minutes_mean']+residual))
                for name,(a,b) in p['shooting_beta'].items():p[name]=rng.betavariate(a,b)
            targets=allocate_minutes(weights)
            for p in active:p['minutes_target']=targets[p['player']]
            scenario['rosters'][team]=active
        scenario['pace_per_team']=max(75,min(125,rng.gauss(context['pace_per_team'],context['pace_sd'])))
        prepared=prepare_game(scenario)
        scenarios.append((scenario,prepared))
    return scenarios,rejected_draws


def trial_run(context,player,market,line,trials=25000,seed=42,scenario_count=256):
    validate(context)
    if market not in MARKETS or not isinstance(line,(int,float)) or isinstance(line,bool) or not math.isfinite(line):
        raise ValueError('VALID_SUPPORTED_EXACT_LINE_REQUIRED')
    if not isinstance(trials,int) or not 25000<=trials<=50000:raise ValueError('25000_TO_50000_ACTUAL_GAMES_REQUIRED')
    if player not in {p['player'] for r in context['rosters'].values() for p in r}:raise ValueError('TARGET_ABSENT_FROM_SOURCED_ROSTER')
    scenarios,rejected=rotation_scenarios(context,scenario_count,seed^0x4737)
    chooser=random.Random(seed^0x4A19);values=[];voids=0;overtime=0
    max_minutes={context['home']:240,context['away']:240}
    for i in range(trials):
        scenario,prepared=scenarios[chooser.randrange(len(scenarios))]
        game=simulate_game(scenario,seed+i*7919,prepared=prepared,max_overtimes=12,max_shooting_sequences=32)
        if game['score_tied_after_overtime_limit'] or game['shot_sequence_ceiling_hit']:
            raise ValueError('SIMULATION_TAIL_GUARD_REACHED_NO_COMPLETE_RECEIPT')
        if game['regulation_team_minutes']!=max_minutes:raise ValueError('REGULATION_MINUTES_NOT_CONSERVED')
        if player not in game['stats'] or game['stats'][player]['minutes']==0:
            voids+=1
        else:values.append(market_value(game['stats'][player],market))
        overtime+=int(bool(game['overtime_periods']))
    over=sum(x>line for x in values);under=sum(x<line for x in values);push=len(values)-over-under
    ordered=sorted(values)
    quantiles={str(q):ordered[round((len(ordered)-1)*q)] if ordered else None for q in (.05,.25,.5,.75,.95)}
    effective=over+under
    return {'model':'BENFRANK_V47_AVAILABILITY_ROTATION_1','status':'EXECUTED_25000_PLUS_COMPLETE_SEQUENTIAL_GAMES',
        'game_id':context['game_id'],'game_date':context['game_date'],'snapshot_id':context.get('snapshot_id'),
        'platform':context.get('platform'),'line_capture_utc':context.get('line_capture_utc'),
        'executed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'prediction_origin':context.get('input_mode'),
        'player':player,'market':market,'exact_line':line,'trials_executed':trials,'over_count':over,'under_count':under,
        'push_count':push,'void_count':voids,'played_trials':len(values),'seed':seed,
        'p_over_raw':over/effective if effective else None,'void_probability':voids/trials,
        'mean':statistics.mean(values) if values else None,'quantiles':quantiles,'rotation_scenario_count':len(scenarios),
        'infeasible_availability_draws_rejected':rejected,'regulation_team_minutes':max_minutes,
        'overtime_trials':overtime,'out_players_eligible_for_substitution':False,
        'probability_conditioning':'OVER_UNDER_CONDITIONAL_ON_TARGET_PLAYING_NONPUSH_VOID_REPORTED_SEPARATELY',
        'context_sha256':hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest(),
        'model_source_sha256':digest(__file__),'physics_source_sha256':digest(Path(__file__).with_name('benfrank_v44_twon.py')),
        'certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET'}
