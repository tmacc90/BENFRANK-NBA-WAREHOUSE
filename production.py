"""v3.2 evidence-gated advanced controller; no invented tracking or injury inputs."""
import argparse,csv,datetime as dt,json,math,random,sqlite3,statistics
from engine import connect,import_csv,stat,MARKETS
from upgrade import migrate,enriched,acquire

CONTEXT_SQL='''CREATE TABLE IF NOT EXISTS evidence (player TEXT,game_date TEXT,kind TEXT,metric TEXT,value TEXT,source TEXT,observed_at TEXT,PRIMARY KEY(player,game_date,kind,metric,source,observed_at));'''

def init(c):
 migrate(c);c.executescript(CONTEXT_SQL);c.commit()

def import_evidence(c,path):
 init(c);added=0
 with open(path,encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   for k in ('player','game_date','kind','metric','value','source','observed_at'):
    if not r.get(k):raise ValueError('Evidence missing '+k)
   dt.date.fromisoformat(r['game_date']);dt.datetime.fromisoformat(r['observed_at'].replace('Z','+00:00'))
   c.execute('INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?,?)',tuple(r[k] for k in ('player','game_date','kind','metric','value','source','observed_at')));added+=1
 c.commit();return added

def evidence(c,player,date,cutoff):
 if not date:return []
 # Date-only cutoff conservatively admits only evidence from previous calendar dates.
 if cutoff is None:cutoff=date+'T00:00:00+00:00'
 t=dt.datetime.fromisoformat(cutoff.replace('Z','+00:00'))
 if t.tzinfo is None:raise ValueError('Evidence cutoff must be timezone-aware')
 rows=c.execute('SELECT * FROM evidence WHERE lower(player)=lower(?) AND game_date=?',(player,date)).fetchall()
 valid=[]
 for r in rows:
  ts=dt.datetime.fromisoformat(r['observed_at'].replace('Z','+00:00'))
  if ts.tzinfo is None:continue
  if ts<=t:valid.append(dict(r))
 return valid

def blind_model(rows,market):
 # Deliberately isolated formula: no baseline, window votes, uploaded line, or opponent.
 valid=[r for r in rows[:25] if r['minutes']>=8]
 if len(valid)<8:return {'status':'INSUFFICIENT_DATA','n':len(valid)}
 recent=valid[:8];historical=valid[8:]
 mins=statistics.median(r['minutes'] for r in recent)
 recent_rate=statistics.median(stat(r,market)/r['minutes'] for r in recent)
 prior_rate=statistics.median(stat(r,market)/r['minutes'] for r in historical) if historical else recent_rate
 rate=.65*recent_rate+.35*prior_rate
 return {'status':'EXECUTED_BLIND_STATISTICAL_MODEL','projection':round(rate*mins,3),'n':len(valid),'method':'Separate robust per-minute rate model; no prop line or primary forecast; not an LLM'}

def sequential_proxy(rows,market,line,trials=25000,seed=42):
 """Sequential minute-level boxscore opportunity simulator, not play-by-play possession Twon."""
 valid=[r for r in rows[:30] if r['minutes']>=8]
 if len(valid)<8:return {'status':'INSUFFICIENT_DATA','trials':0,'reason':'Requires 8 player games with >=8 minutes'}
 if trials<1: return {'status':'SKIPPED','trials':0}
 rng=random.Random(seed);values=[]
 for _ in range(trials):
  sampled=rng.choice(valid)
  # Sample role and observed stat rate jointly; minute-by-minute sequential counts.
  minutes=max(1,min(48,round(rng.gauss(sampled['minutes'],2.5))))
  rate=max(0,stat(sampled,market)/sampled['minutes'])
  # Shared game regime for correlated within-game opportunities.
  regime=rng.lognormvariate(-.5*.12**2,.12)
  total=0.0
  for _minute in range(minutes):
   # Continuous-market proxy permits composite and fantasy scores; not a literal NBA possession engine.
   total+=rate*regime*rng.gammavariate(1.5,1/1.5)
  values.append(total)
 more=sum(v>line for v in values);less=sum(v<line for v in values)
 return {'status':'EXECUTED_SEQUENTIAL_MINUTE_PROXY','trials':trials,'mean':round(statistics.mean(values),3),'more_rate_uncalibrated':round(more/trials,4),'less_rate_uncalibrated':round(less/trials,4),'push_rate_uncalibrated':round(1-(more+less)/trials,4),'model_limitations':'Minute-by-minute stochastic boxscore proxy; NOT possession-by-possession NBA game simulation, no verified opponent scheme, no full team 240-minute conservation'}

def report(c,player,market,line,opponent='',asof=None,trials=25000,cutoff=None):
 if asof is None:raise ValueError('Require --asof YYYY-MM-DD to prevent lookahead')
 dt.date.fromisoformat(asof);init(c)
 base=enriched(c,player,market,line,opponent,asof,0)
 rows=c.execute('SELECT * FROM games WHERE lower(player)=lower(?) AND date<? ORDER BY date DESC',(player,asof)).fetchall()
 blind=blind_model(rows,market)
 sim=sequential_proxy(rows,market,line,trials)
 ev=evidence(c,player,asof,cutoff)
 base['version']='3.2.0';base['blind_statistical_model']=blind;base['sequential_minute_proxy']=sim
 base['verified_pregame_evidence']=ev
 base['execution'].update({'blind_statistical_model':blind['status'],'sequential_minute_proxy':sim['status'],'pregame_evidence': 'AVAILABLE' if ev else 'NO_VERIFIED_EVIDENCE','possession_level_twon':'NOT_IMPLEMENTED','probability_calibration':'NOT_VALIDATED','screenshot_parser':'MANUAL_CONFIRMATION_REQUIRED'})
 base['ticket_authority']='NO_TICKET'
 return base

def backtest(c,player,market,min_history=20,limit=200):
 rows=c.execute('SELECT * FROM games WHERE lower(player)=lower(?) ORDER BY date',(player,)).fetchall()
 tests=[]
 for i in range(min_history,len(rows)):
  if len(tests)>=limit:break
  train=rows[:i];target=rows[i];blind=blind_model(list(reversed(train)),market)
  if blind.get('projection') is None:continue
  y=stat(target,market);p=blind['projection'];tests.append({'date':target['date'],'predicted':p,'actual':round(y,3),'absolute_error':round(abs(p-y),3)})
 return {'status':'EXECUTED' if tests else 'INSUFFICIENT_HISTORY','n':len(tests),'mae':round(statistics.mean(x['absolute_error'] for x in tests),3) if tests else None,'rows':tests,'probability_calibration':'NOT_EXECUTED: point forecast only','validation':'chronological one-step-ahead; requires verified source records'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',default='nba.sqlite');sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('import-games');a.add_argument('csv')
 a=sub.add_parser('import-evidence');a.add_argument('csv')
 a=sub.add_parser('acquire');a.add_argument('--player',required=True);a.add_argument('--player-id',required=True);a.add_argument('--season',required=True)
 a=sub.add_parser('predict');a.add_argument('--player',required=True);a.add_argument('--market',required=True,choices=sorted(MARKETS));a.add_argument('--line',type=float,required=True);a.add_argument('--opponent',default='');a.add_argument('--asof',required=True);a.add_argument('--cutoff');a.add_argument('--trials',type=int,default=25000)
 a=sub.add_parser('batch');a.add_argument('csv');a.add_argument('--asof',required=True);a.add_argument('--trials',type=int,default=25000)
 a=sub.add_parser('backtest');a.add_argument('--player',required=True);a.add_argument('--market',required=True,choices=sorted(MARKETS))
 args=p.parse_args();c=connect(args.db);init(c)
 if args.command=='import-games':out={'imported':import_csv(c,args.csv)}
 elif args.command=='import-evidence':out={'imported':import_evidence(c,args.csv)}
 elif args.command=='acquire':out=acquire(c,args.player,args.player_id,args.season)
 elif args.command=='predict':out=report(c,args.player,args.market,args.line,args.opponent,args.asof,args.trials,args.cutoff)
 elif args.command=='backtest':out=backtest(c,args.player,args.market)
 else:
  results=[]
  with open(args.csv,encoding='utf-8-sig',newline='') as f:
   for row in csv.DictReader(f):
    try:results.append({'status':'OK','report':report(c,row['player'],row['market'],float(row['line']),row.get('opponent',''),row.get('asof') or args.asof,args.trials)})
    except Exception as exc:results.append({'status':'ERROR','error':str(exc),'player':row.get('player')})
  out={'version':'3.2.0','results':results}
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
