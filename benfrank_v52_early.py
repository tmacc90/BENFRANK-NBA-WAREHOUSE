"""Early pregame inference: projected roles, explicit priors, full games, shadow ledger.

Final starters do not gate forecasting. Unknown inputs remain unknown; empirical
priors are labeled estimates, never fabricated player observations. This is an
additive, unvalidated challenger, not a declaration of accuracy or a ticket.
"""
import argparse
import collections
import copy
import datetime as dt
import hashlib
import json
import math
import random
import re
import statistics
from pathlib import Path

from acquire_history import name_key
from engine import stat,window_summary
from benfrank_v44_calibration import instant
from benfrank_v44_twon import validate,prepare_game,simulate_game,market_value,MARKETS,PROFILE_RATES,PCTS
from benfrank_v45_evidence import readonly,digest
from benfrank_v46_reconstructed_replay import allocate_minutes
from benfrank_v47_run import save_receipt
from benfrank_v52_blind import run as run_blind

UTC=dt.timezone.utc
VERSION='BENFRANK_V52_EARLY_PROJECTED_ROLE_1'
def now():return dt.datetime.now(UTC).isoformat()
def season_start(day):
    d=dt.date.fromisoformat(day);return d.year if d.month>=7 else d.year-1
def quantile(values,q):
    s=sorted(values);return s[round((len(s)-1)*q)] if s else None

def check_sources(prop,context,sources,cutoff):
    if prop['market'] not in MARKETS:raise ValueError('UNSUPPORTED_MARKET_ADAPTER: '+prop['market'])
    if isinstance(prop['line'],bool) or not isinstance(prop['line'],(int,float)) or not math.isfinite(prop['line']):raise ValueError('FINITE_EXACT_LINE_REQUIRED')
    if instant(cutoff)>=instant(prop['tipoff_utc']):raise ValueError('PREGAME_CUTOFF_REQUIRED')
    if context['game_date']!=prop['game_date'] or {context['home'],context['away']}!={prop['team'],prop['opponent']}:
        raise ValueError('PROP_CONTEXT_GAME_CONFLICT')
    if prop.get('game_id') and prop['game_id']!=context.get('game_id'):raise ValueError('PROP_CONTEXT_GAME_ID_CONFLICT')
    if instant(prop['tipoff_utc'])!=instant(context['tipoff_utc']):raise ValueError('PROP_CONTEXT_TIPOFF_CONFLICT')
    if sources['game_date']!=prop['game_date']:raise ValueError('DEPTH_TARGET_GAME_DATE_CONFLICT')
    if context['max_feature_game_date']>=prop['game_date']:raise ValueError('TARGET_OR_FUTURE_FEATURE_GAME')
    stamps=[context['pace_asof']]+[x['asof'] for x in context['team_rates'].values()]
    stamps += [p['asof'] for roster in context['rosters'].values() for p in roster]
    if any(instant(s)>instant(cutoff) for s in stamps):raise ValueError('HISTORICAL_PROFILE_AFTER_CUTOFF')
    for team in (context['home'],context['away']):
        d=sources['depths'].get(team)
        if not d:raise ValueError('MISSING_TEAM_DEPTH_CHART: '+team)
        age=(instant(cutoff)-instant(d['captured_at'])).total_seconds()
        if not 0<=age<=24*3600:raise ValueError('STALE_OR_FUTURE_DEPTH_CHART: '+team)
        if d.get('source_timestamp') and instant(d['source_timestamp'])>instant(cutoff):raise ValueError('DEPTH_PUBLICATION_AFTER_CUTOFF')
    ps=sources.get('projected_source')
    if ps and not 0<=(instant(cutoff)-instant(ps['captured_at'])).total_seconds()<=24*3600:raise ValueError('STALE_OR_FUTURE_PROJECTED_LINEUP')
    if prop['market']=='fantasy_score' and context.get('scoring_contract')!='PTS1_REB1.2_AST1.5_STL3_BLK3_TOV-1':
        raise ValueError('EXPLICIT_PLATFORM_FANTASY_SCORING_CONTRACT_REQUIRED')

def projected_five(depth,out):
    chosen=[]
    for pos in ('PG','SG','SF','PF','C'):
        options=depth['positions'][pos]
        found=next((n for n in options if name_key(n) not in out and name_key(n) not in {name_key(x) for x in chosen}),None)
        if found:chosen.append(found)
    return chosen

def resolve_projected_names(names,depth):
    """Allow only unique, explicit roster suffix differences; never fuzzy spelling."""
    def stem(n):return name_key(re.sub(r'\s+(Jr\.?|Sr\.?|II|III|IV)$','',n,flags=re.I))
    resolved=[];receipts=[]
    for name in names:
        key=name_key(name)
        if key in depth['players']:resolved.append(depth['players'][key]['player']);continue
        choices=[p for p in depth['players'].values() if stem(p['player'])==stem(name)]
        if len(choices)!=1:raise ValueError('AMBIGUOUS_OR_MISSING_PROJECTED_IDENTITY: '+name)
        player=choices[0];resolved.append(player['player'])
        receipts.append({'published_name':name,'espn_roster_name':player['player'],'espn_player_id':player.get('id'),
                         'rule':'UNIQUE_EXACT_BASE_NAME_WITH_EXPLICIT_GENERATIONAL_SUFFIX_DIFFERENCE'})
    return resolved,receipts

def early_context(base,prop,sources,history,injury,cutoff):
    check_sources(prop,base,sources,cutoff)
    ctx=copy.deepcopy(base);ctx.update(snapshot_id=prop['snapshot_id'],line_capture_utc=cutoff,
        input_mode='EARLY_PREGAME_PROJECTED_ROLE_SCENARIOS',analysis_cutoff_utc=cutoff,
        final_starters_required=False,official_final_starters_confirmed=False,
        native_platform_capture_utc=prop.get('native_platform_line_capture_utc'),
        line_clock_kind='ANALYSIS_INPUT_FREEZE_NOT_NATIVE_PLATFORM_CLOCK',early_role_evidence={})
    if instant(injury['retrieved_at'])>instant(cutoff):raise ValueError('INJURY_RETRIEVAL_AFTER_CUTOFF')
    injury_age=(instant(cutoff)-instant(injury['retrieved_at'])).total_seconds()
    if not 0<=injury_age<=36*3600:raise ValueError('STALE_INJURY_SNAPSHOT')
    prior_source=copy.deepcopy([p for rs in base['rosters'].values() for p in rs if p.get('observed_profile_games',0)>=3])
    if len(prior_source)<7:raise ValueError('OBSERVED_PEER_PRIOR_POOL_REQUIRED')
    regularizers=[]
    for team,roster in ctx['rosters'].items():
        depth=sources['depths'][team];out=set()
        team_status=injury['teams'].get(team,{})
        for p in roster:
            obs=team_status.get(name_key(p['player']))
            p['availability_status']=obs['status'] if obs else 'UNKNOWN_NOT_CLEARED'
            p['availability_observation']=obs or {'status':'UNKNOWN_NOT_CLEARED','reason':'UNLISTED_IS_NOT_MEDICAL_CLEARANCE'}
            if p['availability_status']=='Out':out.add(name_key(p['player']));p['probability_played']=0.0
        derived=projected_five(depth,out)
        published,identity_receipts=resolve_projected_names(sources.get('projected',{}).get(team,{}).get('players',[]),depth)
        published=[n for n in published if name_key(n) not in out]
        if published and len(published)!=5:published=[]
        primary=published or derived
        keys={name_key(n) for n in primary}
        known={name_key(p['player']) for p in roster}
        if not keys.issubset(known):raise ValueError('PROJECTED_STARTER_MISSING_PROFILE: '+str(sorted(keys-known)))
        for p in roster:
            key=name_key(p['player']);info=depth['players'].get(key)
            p['depth_rank']=min(info['ranks'].values()) if info else None
            p['projected_starter']=key in keys
            # Original explicit statuses have priority. Do not turn depth labels into clearance.
            if p['availability_status']!='Out':
                p['probability_played']={'Available':.985,'Probable':.90,'Questionable':.50,'Doubtful':.15}.get(p['availability_status'],p['probability_played'] or .80)
                if p['availability_status']=='UNKNOWN_NOT_CLEARED' and p['availability_observation'].get('reported_status'):
                    p['probability_played']=.50
                p['availability_probability_kind']='UNVALIDATED_EARLY_SCENARIO_DESIGN_PARAMETER_NOT_CLEARANCE'
            rows=history.get(key,[])
            sy=season_start(prop['game_date']);current=[r for r in rows if r['season']==str(sy)+'-'+str(sy+1)[-2:]]
            recent=[r['minutes'] for r in (current or rows)[-5:] if r['minutes']>0]
            if p.get('observed_profile_games',0)==0:
                pool=sorted(prior_source,key=lambda x:x['minutes_mean'])[:max(7,len(prior_source)//2)]
                for field in (*PROFILE_RATES,*PCTS):p[field]=statistics.median(x[field] for x in pool)
                p['shooting_beta']={k:[25*p[k],25*(1-p[k])] for k in PCTS}
                samples=[m for peer in pool for m in peer['historical_minutes'] if m>0]
                if not samples:raise ValueError('NO_OBSERVED_PEER_MINUTE_EXPOSURE')
                # A source-based reserve prior is allowed only as an explicit unvalidated estimate.
                p['minutes_mean']=min(8.0,quantile(samples,.10))
                p['minute_prior_samples']=[min(10.0,m) for m in sorted(samples)[:max(7,len(samples)//5)]]
                p['historical_minutes']=[]
                p['profile_kind']='EMPIRICAL_RESERVE_PEER_PRIOR_ZERO_OBSERVED_TARGET_GAMES'
                p['source']='MODEL_PRIOR_FROM_OBSERVED_PEERS_NOT_TARGET_GAME_LOGS'
                p['source_peer_players']=sorted({x['player'] for x in pool})
                p['minutes_source']='DEPTH_ROLE_AND_OBSERVED_RESERVE_PEER_PRIOR_UNVALIDATED'
                regularizers.append({'team':team,'player':p['player'],'observed_target_games':0,'peer_players':p['source_peer_players']})
            else:
                p['profile_kind']='OBSERVED_PLAYER_HISTORY_SHRUNK_RATE'
                if recent:
                    p['minutes_mean']=.8*statistics.median(recent)+.2*p['minutes_mean']
                    p['historical_minutes']=recent
            p['minutes_mean']=min(44,max(0,p['minutes_mean']*(1.05 if p['projected_starter'] else .92)))
        targets=allocate_minutes({p['player']:p['minutes_mean']*p['probability_played'] for p in roster})
        for p in roster:p['minutes_target']=targets[p['player']]
        ctx['early_role_evidence'][team]={'depth_derived_five':derived,'published_projected_five':published,
            'selected_projected_five':primary,'sources_disagree':bool(published and set(map(name_key,published))!=set(map(name_key,derived))),
            'depth_source_sha256':depth['sha256'],'depth_captured_at':depth['captured_at'],
            'projected_identity_resolutions':identity_receipts,
            'projected_source':sources.get('projected_source'),'official_confirmation_required':False}
    ctx['labeled_zero_history_priors']=regularizers
    ctx['injury_source_authority']=injury.get('authority','ORIGINAL_NBA_INJURY_PDF')
    ctx['injury_source_sha256']=injury['sha256']
    ctx['official_report_time_utc']=injury['printed_at']
    ctx['official_report_sha256']=injury['sha256'] if ctx['injury_source_authority']=='ORIGINAL_NBA_INJURY_PDF' else None
    ctx['injury_retrieved_at_utc']=injury['retrieved_at']
    ctx['limitations']=['Early forecast uses projected roles, not confirmed starters.',
        'Unknown availability and material in/out cases are modeled explicitly; probabilities are unvalidated design assumptions.',
        'Zero-history reserve priors, when present, are modeled estimates from observed peers, not fabricated target logs.',
        'No matching market probability calibration or real-game accuracy certification is asserted.',
        'Zone, contest and potential-assist tracking remain unavailable when not observed.']
    validate(ctx);return ctx

def scenarios(context,seed,count=256,forced=None):
    rng=random.Random(seed);cases=[]
    for i in range(count):
        c=copy.deepcopy(context);c['rosters']={};states={}
        for team,roster in context['rosters'].items():
            for attempt in range(1000):
                active=[copy.deepcopy(p) for p in roster if p['availability_status']!='Out' and
                    ((forced or {}).get(p['player'],rng.random()<p['probability_played']))]
                if len(active)>=7:break
            else:raise ValueError('NO_FEASIBLE_NON_OUT_ROTATION')
            names={p['player'] for p in active}
            for p in roster:
                if p['availability_status'] in ('Questionable','Doubtful') or p.get('availability_observation',{}).get('reported_status'):
                    states[p['player']]=p['player'] in names
            weights={}
            alternative=context['early_role_evidence'][team]
            use_depth=bool(alternative['sources_disagree'] and i%2)
            start_keys=set(map(name_key,alternative['depth_derived_five'] if use_depth else alternative['selected_projected_five']))
            for p in active:
                samples=p['historical_minutes'] or p.get('minute_prior_samples',[])
                residual=rng.choice(samples)-statistics.mean(samples) if samples else 0
                weights[p['player']]=min(48,max(.1,p['minutes_mean']+residual))*(1.03 if name_key(p['player']) in start_keys else .97)
                for name,(a,b) in p['shooting_beta'].items():p[name]=rng.betavariate(max(a,.01),max(b,.01))
            allocation=allocate_minutes(weights)
            for p in active:p['minutes_target']=allocation[p['player']]
            c['rosters'][team]=active
        c['pace_per_team']=min(125,max(75,rng.gauss(context['pace_per_team'],context['pace_sd'])))
        c['scenario_material_availability']=states
        cases.append((c,prepare_game(c)))
    return cases

def simulate(context,player,market,line,trials,seed,minimum=25000):
    if isinstance(trials,bool) or not minimum<=trials<=50000:raise ValueError('ACTUAL_TRIAL_COUNT_OUT_OF_RANGE')
    cases=scenarios(context,seed^0x5200);rng=random.Random(seed);values=[];voids=0;counts=collections.Counter();groups={};chain=hashlib.sha256();checkpoints=[]
    for i in range(trials):
        c,prepared=cases[rng.randrange(len(cases))]
        game=simulate_game(c,seed+i*7919,prepared=prepared,max_overtimes=12,max_shooting_sequences=32,last_player_exception=True)
        if game['score_tied_after_overtime_limit'] or game['shot_sequence_ceiling_hit']:raise ValueError('INCOMPLETE_GAME_TAIL_GUARD')
        if game['regulation_team_minutes']!={context['home']:240,context['away']:240}:raise ValueError('REGULATION_MINUTE_CONSERVATION_FAILURE')
        target=game['stats'].get(player);v=market_value(target,market) if target and target['minutes']>0 else None
        label='VOID' if v is None else 'OVER' if v>line else 'UNDER' if v<line else 'PUSH';counts[label]+=1
        if v is None:voids+=1
        else:values.append(v)
        for name,active in c['scenario_material_availability'].items():
            key=name+'|'+('IN' if active else 'OUT');g=groups.setdefault(key,collections.Counter());g[label]+=1
        chain.update(json.dumps([i,seed+i*7919,game['score'],v],sort_keys=True).encode()+b'\n')
        if (i+1)%5000==0:checkpoints.append({'complete_games':i+1,'counts':dict(counts),'chain_sha256':chain.hexdigest()})
    total=counts['OVER']+counts['UNDER'];p=counts['OVER']/total if total else None
    conditional={}
    for key,g in groups.items():
        n=g['OVER']+g['UNDER'];conditional[key]={'counts':dict(g),'played_nonpush_n':n,'p_over_raw':g['OVER']/n if n else None}
    return {'model':VERSION,'trials_executed':trials,'over_count':counts['OVER'],'under_count':counts['UNDER'],
        'push_count':counts['PUSH'],'void_count':voids,'played_trials':len(values),'p_over_raw':p,
        'mean':statistics.mean(values) if values else None,'quantiles':{str(q):quantile(values,q) for q in (.05,.25,.5,.75,.95)},
        'histogram':{str(k):n for k,n in sorted(collections.Counter(values).items())},
        'conditional_questionable_states':conditional,'seed':seed,'checkpoints':checkpoints,'trial_chain_sha256':chain.hexdigest(),
        'complete_sequential_games':True,'regulation_team_minutes':{context['home']:240,context['away']:240},
        'context_sha256':hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest(),
        'model_source_sha256':digest(__file__),'physics_source_sha256':digest(Path(__file__).with_name('benfrank_v44_twon.py')),
        'executed_at':now(),'probability_calibration_applied':False}

def stress(context,player,side,kind):
    c=copy.deepcopy(context)
    for roster in c['rosters'].values():
        for p in roster:
            if p['player']!=player:continue
            samples=p['historical_minutes'] or p.get('minute_prior_samples',[])
            if kind=='P25_MINUTES_CONVERSION_PROXY':
                p['minutes_mean']=quantile(samples,.25) if samples else p['minutes_mean']*.8
                multiplier=.9;c['pace_per_team']=max(75,c['pace_per_team']-.674*c['pace_sd'])
            else:
                p['minutes_mean']=min(44,max(p['minutes_mean']*1.2,quantile(samples,.75) or 0))
                multiplier=1.1;c['pace_per_team']=min(125,c['pace_per_team']+.674*c['pace_sd'])
            for key in PCTS:p[key]=min(.99,max(.01,p[key]*multiplier))
            # Rate proxies are explicitly not measured rebound chances or potential assists.
            for key in ('reb_per36','ast_per36'):p[key]*=multiplier
            p['shooting_beta']={key:[25*p[key],25*(1-p[key])] for key in PCTS}
    return c

def run_one(prop,base,sources,injury,db,trials=25000,stress_trials=2000):
    cutoff=now();check_sources(prop,base,sources,cutoff)
    conn=readonly(db)
    try:rows=[dict(r) for r in conn.execute('SELECT * FROM games WHERE date<? ORDER BY date,player',(prop['game_date'],))]
    finally:conn.close()
    history=collections.defaultdict(list)
    for r in rows:history[name_key(r['player'])].append(r)
    context=early_context(base,prop,sources,history,injury,cutoff)
    blind=run_blind(db,prop['player'],prop['market'],prop['game_date'])
    seed=int(hashlib.sha256(('V52|'+prop['snapshot_id']).encode()).hexdigest()[:8],16)
    main=simulate(context,prop['player'],prop['market'],prop['line'],trials,seed)
    if main['p_over_raw'] is None:raise ValueError('NO_CONDITIONAL_PLAYED_DISTRIBUTION')
    direction='OVER' if main['p_over_raw']>=.5 else 'UNDER'
    bside='OVER' if blind['projection']>prop['line'] else 'UNDER' if blind['projection']<prop['line'] else 'AT_LINE'
    stresses={}
    for j,kind in enumerate(('P25_MINUTES_CONVERSION_PROXY','HIGH_MINUTES_HOT_CONVERSION_PROXY')):
        modified=stress(context,prop['player'],direction,kind)
        r=simulate(modified,prop['player'],prop['market'],prop['line'],stress_trials,seed^(0x5250+j),minimum=1000)
        r['limitation']='Assumption stress using observed minutes and rate/efficiency proxies; not measured P25 opportunity x conversion.'
        stresses[kind]=r
    tested=[r['p_over_raw'] for r in stresses.values() if r['p_over_raw'] is not None]
    tested += [r['p_over_raw'] for r in main['conditional_questionable_states'].values() if r['played_nonpush_n']>=100 and r['p_over_raw'] is not None]
    flips=any(('OVER' if p>=.5 else 'UNDER')!=direction for p in tested)
    target=history[name_key(prop['player'])];ordered=list(reversed(target))
    windows={k:window_summary(ordered[:n],prop['market'],prop['line'],n) for k,n in [('L5',5),('L10',10),('L15',15),('L20',20),('L25',25),('L32',32),('L52',52)]}
    sy=season_start(prop['game_date'])
    for key,selected in [('available_archive',ordered),('current_season',[r for r in ordered if r['season'].startswith(str(sy))]),
                         ('previous_season',[r for r in ordered if r['season'].startswith(str(sy-1))])]:
        windows[key]=window_summary(selected,prop['market'],prop['line'])
    for w in windows.values():
        for old,new in [('more','over_count'),('less','under_count'),('more_rate','over_rate'),('less_rate','under_rate')]:w[new]=w.pop(old)
    completed=now()
    result={'version':VERSION,'prop':prop,'analysis_cutoff_utc':cutoff,'forecast_completed_at_utc':completed,
        'status':'FORWARD_TEST_READY' if instant(completed)<instant(prop['tipoff_utc']) else 'LATE_EXECUTION_NOT_FORWARD_ELIGIBLE',
        'direction':direction,'projection':main['mean'],'blind_direction':bside,'blind_model':blind,
        'model_disagreement':direction!=bside,'scenario_side_flip':flips,'scenario_risk':'FRAGILE' if flips else 'STABLE_IN_TESTED_CASES_ONLY',
        'main_simulation':main,'stress_simulations':stresses,'context':context,'historical_windows':windows,
        'actual_complete_game_count_all_branches':trials+2*stress_trials,
        'execution_ready_without_final_starters':True,'final_starters_required':False,
        'missing_evidence':['Independent model accuracy/calibration on a new forward cohort',
            'Native current-line recheck when not provided; uploaded line stays the tested hypothesis',
            'Observed defender/zone/contest/potential-assist/rebound-chance tracking where absent',
            'Genuine complete career and translated college/G League history where absent'],
        'certification':'UNVALIDATED_EARLY_CHALLENGER','ticket_authority':'RESEARCH_ONLY',
        'governance':'User-authorized EARLY_PREGAME mode supersedes final-starter waiting only; original governing files and receipts are preserved.',
        'uncertainty_note':'Raw model side shares and stress stability are not calibrated winning probabilities.'}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',required=True);p.add_argument('--contexts',required=True)
    p.add_argument('--sources',required=True);p.add_argument('--injury',required=True)
    p.add_argument('--history-db',required=True);p.add_argument('--output',required=True);p.add_argument('--ledger',required=True)
    p.add_argument('--trials',type=int,default=25000);p.add_argument('--stress-trials',type=int,default=2000)
    a=p.parse_args();sources=json.loads(Path(a.sources).read_text());injury=json.loads(Path(a.injury).read_text())
    board=json.loads(Path(a.board).read_text());root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
    from benfrank_v52_ledger import record_prediction
    result=[]
    for prop in board:
        try:
            base=json.loads((Path(a.contexts)/(prop.get('context_id',prop['snapshot_id'])+'.json')).read_text())
            r=run_one(prop,base,sources,injury,a.history_db,a.trials,a.stress_trials)
            path=root/(prop['snapshot_id']+'.json');save_receipt(path,r)
            if r['status']=='FORWARD_TEST_READY':record_prediction(a.ledger,json.loads(path.read_text()))
            result.append({'player':prop['player'],'direction':r['direction'],'projection':r['projection'],
                'blind_projection':r['blind_model']['projection'],'model_disagreement':r['model_disagreement'],
                'scenario_risk':r['scenario_risk'],'actual_complete_games':r['actual_complete_game_count_all_branches'],'status':r['status']})
        except Exception as exc:result.append({'player':prop.get('player'),'status':'BLOCKED','exact_blocker':type(exc).__name__+': '+str(exc)})
        print(json.dumps(result[-1]),flush=True)
    save_receipt(root/'comparison.json',{'version':VERSION,'results':result,'completed_at_utc':now(),'final_starters_required':False})
    return 0 if all(r['status']=='FORWARD_TEST_READY' for r in result) else 2
if __name__=='__main__':raise SystemExit(main())
