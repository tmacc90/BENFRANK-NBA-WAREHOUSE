"""BENFRANK NBA v3.1: verified-data acquisition, evidence, walk-forward and batch controller."""
import argparse, csv, datetime as dt, json, math, os, sqlite3, statistics, time, urllib.request
from pathlib import Path
from engine import connect, import_csv, predict, stat, MARKETS

SCHEMA='''CREATE TABLE IF NOT EXISTS provenance (source TEXT, endpoint TEXT, retrieved_at TEXT, player TEXT, season TEXT, records INTEGER, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS context (date TEXT, team TEXT, opponent TEXT, pace REAL, defensive_rating REAL, opponent_rebound_pct REAL, injury_status TEXT, source TEXT, asof TEXT, PRIMARY KEY(date,team));
CREATE TABLE IF NOT EXISTS predictions (id INTEGER PRIMARY KEY, created_at TEXT, player TEXT, game_date TEXT, market TEXT, line REAL, direction TEXT, baseline REAL, report_json TEXT);
CREATE TABLE IF NOT EXISTS settlements (prediction_id INTEGER PRIMARY KEY, actual REAL, result TEXT, source TEXT, settled_at TEXT);'''

def migrate(c):
 c.executescript(SCHEMA);c.commit()

def fetch_nba(player_id,season,timeout=15):
 """Optional nba_api adapter. Never invent or silently substitute records."""
 try:
  from nba_api.stats.endpoints import playergamelog
 except ImportError:
  return [],'NBA_API_NOT_INSTALLED: pip install nba_api'
 try:
  response=playergamelog.PlayerGameLog(player_id=str(player_id),season=season,season_type_all_star='Regular Season',timeout=timeout)
  raw=response.get_dict()['resultSets'][0]
  return [dict(zip(raw['headers'],row)) for row in raw['rowSet']],'OK'
 except Exception as exc:return [],f'ACQUISITION_FAILED: {type(exc).__name__}: {str(exc)[:250]}'

def acquire(c,player,player_id,season,team=None,timeout=15):
 migrate(c)
 raw,status=fetch_nba(player_id,season,timeout)
 now=dt.datetime.now(dt.timezone.utc).isoformat()
 added=0;rejected=[]
 if status=='OK':
  for g in raw:
   try:
    day=dt.datetime.strptime(g['GAME_DATE'],'%b %d, %Y').date().isoformat()
    matchup=g['MATCHUP'];home=int('vs.' in matchup)
    opponent=matchup.split()[-1].upper()
    # PlayerGameLog omits starting status. Preserve NULL and require a separate
    # source reconciliation instead of defaulting every appearance to a start.
    from warehouse_v36 import stage
    gs=g.get('GS')
    row=dict(player=player,date=day,season=season,team=team or matchup.split()[0],
             opponent=opponent,home=home,starter=int(float(gs)) if gs not in (None,'') else None,
             minutes=float(g['MIN']),pts=float(g['PTS']),reb=float(g['REB']),ast=float(g['AST']),
             stl=float(g['STL']),blk=float(g['BLK']),tov=float(g['TOV']),fg3m=float(g['FG3M']),
             source_game_id=str(g.get('Game_ID') or g.get('GAME_ID') or ''),season_type='regular')
    result=stage(c,'nba_official',[row])
    if result['rejected']:raise ValueError(json.dumps(result['errors']))
    added+=result['staged']
   except Exception as e:rejected.append(f'{g.get("GAME_ID","unknown")}: {e}')
  if rejected:status='PARTIAL_VALIDATION_FAILURE'
  elif raw:status='STAGED_REQUIRES_CROSSCHECK'
  else:status='EMPTY_RESPONSE'
 c.execute('INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?)',('NBA Stats via nba_api','PlayerGameLog',now,player,season,added,status,'; '.join(rejected[:10])))
 c.commit()
 return {'player':player,'season':season,'records_imported':0,'records_staged':added,'status':status,'rejected_count':len(rejected),'rejections':rejected,'source':'NBA Stats via nba_api','retrieved_at':now}

def market_components(rows,market):
 """Line-blind opportunity/efficiency diagnostics, no claimed play-by-play data."""
 if not rows:return {'status':'NO_DATA'}
 minutes=[float(r['minutes']) for r in rows if r['minutes']>0]
 if not minutes:return {'status':'NO_MINUTES'}
 totals=[stat(r,market) for r in rows]
 per36=[stat(r,market)*36/r['minutes'] for r in rows if r['minutes']>0]
 return {'status':'CALCULATED_FROM_BOXSCORES','sample':len(rows),'minutes_mean':round(statistics.mean(minutes),2),'minutes_median':round(statistics.median(minutes),2),'stat_per_36_mean':round(statistics.mean(per36),3),'stat_mean':round(statistics.mean(totals),3),'opportunity_proxy':'per-36 box score; not verified touches/chances','uncertainty_stdev':round(statistics.stdev(totals),3) if len(totals)>1 else None}

def hell_tests(rows,market,line,baseline):
 if baseline is None:return {'status':'NOT_EXECUTED','reason':'Missing baseline'}
 minute_shocks=[0.75,0.85,1.0,1.15]
 efficiency_shocks=[0.8,0.9,1.0,1.1]
 scenarios=[]
 for m in minute_shocks:
  for e in efficiency_shocks:
   value=round(baseline*m*e,3)
   scenarios.append({'minutes_multiplier':m,'efficiency_multiplier':e,'projection':value,'side':'MORE' if value>line else 'LESS' if value<line else 'PUSH'})
 return {'status':'EXECUTED_SENSITIVITY_GRID','scenario_count':len(scenarios),'scenarios':scenarios,'warning':'Multipliers are stress assumptions, not learned game-script probabilities'}

def independent_model(rows,market):
 """Line-blind alternative to the correlated-window mean: trimmed per-minute rate x median minutes."""
 usable=[r for r in rows[:15] if r['minutes']>=5]
 if len(usable)<5:return {'status':'INSUFFICIENT_DATA','n':len(usable)}
 rates=sorted(stat(r,market)/r['minutes'] for r in usable)
 trim=max(1,len(rates)//10)
 trimmed=rates[trim:-trim] if len(rates)>2*trim else rates
 median_minutes=statistics.median(r['minutes'] for r in usable[:10])
 return {'status':'EXECUTED_INDEPENDENT_FORMULA','projection':round(statistics.mean(trimmed)*median_minutes,3),'n':len(usable),'method':'Trimmed per-minute rate times median recent minutes; not independent data, not AI'}

def enriched(c,player,market,line,opponent='',asof=None,trials=25000,seed=42,minutes=None):
 migrate(c)
 base=predict(c,player,market,line,opponent,asof,trials,seed,minutes)
 rows=c.execute('SELECT * FROM games WHERE lower(player)=lower(?) AND date < ? ORDER BY date DESC',(player,asof or '9999-12-31')).fetchall()
 alt=independent_model(rows,market)
 base['version']='3.1.0'
 base['opportunity_diagnostics']=market_components(rows[:20],market)
 base['alternative_line_blind_model']=alt
 base['hell_tests']=hell_tests(rows,market,line,base['baseline_projection'])
 base['evidence_conflict']=bool(base['baseline_projection'] is not None and alt.get('projection') is not None and ((base['baseline_projection']>line)!=(alt['projection']>line)))
 base['execution'].update({'opportunity_diagnostics':base['opportunity_diagnostics']['status'],'alternative_model':alt['status'],'hell_tests':base['hell_tests']['status'],'provenance_log':'AVAILABLE','walk_forward_validation':'AVAILABLE_AS_COMMAND','matchup_defense':'NO_VERIFIED_MATCHUP_INPUT','injury_lineups':'NO_VERIFIED_AVAILABILITY_INPUT','blind_ai':'NOT_IMPLEMENTED_INDEPENDENT_AI','sequential_twon':'NOT_IMPLEMENTED','calibration':'NOT_CALIBRATED'})
 return base

def walkforward(c,player,market,line,min_history=20,limit=100):
 rows=c.execute('SELECT * FROM games WHERE lower(player)=lower(?) ORDER BY date',(player,)).fetchall()
 results=[]
 for i in range(min_history,len(rows)):
  if len(results)>=limit:break
  date=rows[i]['date'];report=predict(c,player,market,line,asof=date,trials=0)
  fair=report['baseline_projection']
  if fair is None:continue
  actual=stat(rows[i],market)
  results.append({'date':date,'projection':fair,'actual':actual,'error':round(fair-actual,3),'side':'MORE' if fair>line else 'LESS','outcome':'MORE' if actual>line else 'LESS' if actual<line else 'PUSH'})
 valid=[r for r in results if r['outcome']!='PUSH']
 return {'status':'EXECUTED' if results else 'INSUFFICIENT_HISTORY','player':player,'market':market,'line':line,'n':len(results),'nonpush_n':len(valid),'mae':round(statistics.mean(abs(r['error']) for r in results),3) if results else None,'direction_accuracy_nonpush':round(sum(r['side']==r['outcome'] for r in valid)/len(valid),4) if valid else None,'warning':'Fixed threshold historical test; not calibrated probabilities; data source/coverage must be audited','rows':results}

def run_batch(c,path,asof=None,trials=25000):
 reports=[]
 with open(path,newline='',encoding='utf-8-sig') as f:
  for i,r in enumerate(csv.DictReader(f),1):
   try:
    report=enriched(c,r['player'],r['market'],float(r['line']),r.get('opponent',''),r.get('asof') or asof,trials,42+i)
    reports.append({'row':i,'status':'EXECUTED','report':report})
   except Exception as exc:reports.append({'row':i,'status':'ERROR','reason':str(exc)})
 return {'version':'3.1.0','props':len(reports),'results':reports}

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',default='nba.sqlite');sub=p.add_subparsers(dest='cmd',required=True)
 ac=sub.add_parser('acquire');ac.add_argument('--player',required=True);ac.add_argument('--player-id',required=True);ac.add_argument('--season',required=True);ac.add_argument('--team')
 pr=sub.add_parser('predict');pr.add_argument('--player',required=True);pr.add_argument('--market',required=True,choices=sorted(MARKETS));pr.add_argument('--line',type=float,required=True);pr.add_argument('--opponent',default='');pr.add_argument('--asof');pr.add_argument('--trials',type=int,default=25000)
 ba=sub.add_parser('batch');ba.add_argument('csv');ba.add_argument('--asof');ba.add_argument('--trials',type=int,default=25000)
 bt=sub.add_parser('backtest');bt.add_argument('--player',required=True);bt.add_argument('--market',required=True,choices=sorted(MARKETS));bt.add_argument('--line',type=float,required=True)
 a=p.parse_args();c=connect(a.db);migrate(c)
 if a.cmd=='acquire':out=acquire(c,a.player,a.player_id,a.season,a.team)
 elif a.cmd=='predict':out=enriched(c,a.player,a.market,a.line,a.opponent,a.asof,a.trials)
 elif a.cmd=='batch':out=run_batch(c,a.csv,a.asof,a.trials)
 else:out=walkforward(c,a.player,a.market,a.line)
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
