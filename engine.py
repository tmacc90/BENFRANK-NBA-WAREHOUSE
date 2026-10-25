import argparse,csv,datetime as dt,json,math,random,sqlite3,statistics
from pathlib import Path

WINDOWS={'L3':3,'L5':5,'L7':7,'L10':10,'L12':12,'L15':15,'L20':20,'L25':25,'L30':30,'L40':40,'L50':50,'L60':60}
OTHER=['current_season','previous_season','two_seasons_ago','last_three_seasons','career','current_team','starter','reserve','vs_opponent_L3','vs_opponent_L5','vs_opponent_season','vs_opponent_career']
MARKETS={'points':'pts','rebounds':'reb','assists':'ast','steals':'stl','blocks':'blk','turnovers':'tov','threes':'fg3m','pra':None,'pr':None,'pa':None,'ra':None,'fantasy_score':None}
SCORING={'points':1,'rebounds':1.2,'assists':1.5,'steals':3,'blocks':3,'turnovers':-1}
FIELDS=['player','date','season','team','opponent','home','starter','minutes','pts','reb','ast','stl','blk','tov','fg3m']

def connect(path):
 c=sqlite3.connect(path);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS games (player TEXT,date TEXT,season TEXT,team TEXT,opponent TEXT,home INTEGER,starter INTEGER,minutes REAL,pts REAL,reb REAL,ast REAL,stl REAL,blk REAL,tov REAL,fg3m REAL,PRIMARY KEY(player,date,team))')
 c.commit();return c

def import_csv(c,path):
 n=0
 with open(path,newline='',encoding='utf-8-sig') as f:
  for r in csv.DictReader(f):
   missing=set(FIELDS)-set(r)
   if missing:raise ValueError('Missing CSV columns: '+','.join(sorted(missing)))
   dt.date.fromisoformat(r['date']); vals=[r[k] for k in FIELDS]
   for i in [5,6]:vals[i]=int(vals[i])
   for i in range(7,len(vals)):vals[i]=float(vals[i])
   c.execute('INSERT OR REPLACE INTO games VALUES ('+','.join('?' for _ in FIELDS)+')',vals);n+=1
 c.commit();return n

def stat(r,market):
 if market=='fantasy_score':return r['pts']+1.2*r['reb']+1.5*r['ast']+3*(r['stl']+r['blk'])-r['tov']
 if market in ('pra','pr','pa','ra'):
  return sum(r[k] for k in {'pra':['pts','reb','ast'],'pr':['pts','reb'],'pa':['pts','ast'],'ra':['reb','ast']}[market])
 return r[MARKETS[market]]

def season_start(s):
 try:return int(str(s)[:4])
 except:return -1

def subsets(rows,opponent):
 rows=sorted(rows,key=lambda x:x['date'],reverse=True)
 result={k:rows[:n] for k,n in WINDOWS.items()}
 if not rows:return {**result,**{k:[] for k in OTHER}}
 season=max(season_start(r['season']) for r in rows)
 current_team=rows[0]['team'];vs=[r for r in rows if r['opponent'].casefold()==opponent.casefold()] if opponent else []
 result.update({'current_season':[r for r in rows if season_start(r['season'])==season], 'previous_season':[r for r in rows if season_start(r['season'])==season-1], 'two_seasons_ago':[r for r in rows if season_start(r['season'])==season-2], 'last_three_seasons':[r for r in rows if season-2<=season_start(r['season'])<=season], 'career':rows,'current_team':[r for r in rows if r['team']==current_team],'starter':[r for r in rows if r['starter']==1],'reserve':[r for r in rows if r['starter']==0],'vs_opponent_L3':vs[:3],'vs_opponent_L5':vs[:5],'vs_opponent_season':[r for r in vs if season_start(r['season'])==season],'vs_opponent_career':vs})
 return result

def window_summary(rows,market,line,requested=None):
 v=[stat(r,market) for r in rows];n=len(v)
 if not n:return {'n':0,'status':'NO_DATA','mean':None,'median':None,'expected':None,'more':0,'less':0,'push':0,'more_rate':None,'less_rate':None}
 more=sum(x>line for x in v);less=sum(x<line for x in v);push=n-more-less
 # independent line-blind estimate: mean of stat values, not using uploaded line
 expected=statistics.mean(v)
 return {'n':n,'status':'COMPLETE' if requested is None or n>=requested else 'PARTIAL','mean':round(expected,3),'median':round(statistics.median(v),3),'expected':round(expected,3),'stdev':round(statistics.stdev(v),3) if n>1 else None,'more':more,'less':less,'push':push,'more_rate':round(more/n,4),'less_rate':round(less/n,4),'minutes_avg':round(statistics.mean(r['minutes'] for r in rows),2)}

def simulate(rows,market,line,trials,seed,minutes_override=None):
 if trials<=0:return {'status':'SKIPPED_FOR_BACKTEST','trials':0}
 if len(rows)<3:return {'status':'NOT_EXECUTED','reason':'At least 3 verified games required'}
 rng=random.Random(seed);results=[]
 for _ in range(trials):
  # historical game-state bootstrap with minutes reweighting; NOT possession-by-possession Twon
  r=rng.choice(rows);v=stat(r,market)
  if minutes_override is not None and r['minutes']>0:v*=minutes_override/r['minutes']
  results.append(v)
 more=sum(x>line for x in results);less=sum(x<line for x in results)
 return {'status':'EXECUTED_EMPIRICAL_BOOTSTRAP','trials':trials,'mean':round(statistics.mean(results),3),'more_probability_uncalibrated':round(more/trials,4),'less_probability_uncalibrated':round(less/trials,4),'push_probability_uncalibrated':round((trials-more-less)/trials,4),'method':'Historical game bootstrap; not sequential possession simulation; probabilities uncalibrated'}

def predict(c,player,market,line,opponent='',asof=None,trials=25000,seed=42,minutes=None):
 if market not in MARKETS:raise ValueError('Unsupported market '+market)
 if asof:dt.date.fromisoformat(asof)
 query='SELECT * FROM games WHERE lower(player)=lower(?)'+(' AND date < ?' if asof else '')+' ORDER BY date DESC'
 rows=c.execute(query,(player,asof) if asof else (player,)).fetchall()
 ss=subsets(rows,opponent)
 windows={k:window_summary(v,market,line,WINDOWS.get(k)) for k,v in ss.items()}
 # Reference blend is NOT a calibrated forecast and intentionally avoids line dependence.
 usable=[(k,w) for k,w in windows.items() if k in ('L5','L10','L20','current_season','previous_season') and w['n']>=3]
 weights={'L5':0.20,'L10':0.25,'L20':0.20,'current_season':0.25,'previous_season':0.10}
 denom=sum(weights[k] for k,_ in usable)
 fair=sum(w['expected']*weights[k] for k,w in usable)/denom if denom else None
 sim=simulate(rows[:20],market,line,trials,seed,minutes)
 side='MORE' if fair is not None and fair>line else 'LESS' if fair is not None else 'UNRESOLVED'
 return {'version':'3.0.0','player':player,'market':market,'line':line,'opponent':opponent,'asof_exclusive':asof,'games_available':len(rows),'windows':windows,'baseline_projection':round(fair,3) if fair is not None else None,'baseline_method':'Provisional correlated-window weighted average; not calibrated; no line used','direction':side,'ticket_authority':'NO_TICKET','simulation':sim,'execution':{'historical_windows':'EXECUTED','exact_line_counts':'EXECUTED','official_data_ingestion':'USER_SUPPLIED_CSV_ONLY','matchup_defense':'NOT_IMPLEMENTED','injury_lineups':'NOT_IMPLEMENTED','blind_ai':'NOT_IMPLEMENTED','sequential_twon':'NOT_IMPLEMENTED','hell_tests':'NOT_IMPLEMENTED','calibration':'NOT_IMPLEMENTED'}}

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',default='nba.sqlite');sub=p.add_subparsers(dest='cmd',required=True)
 imp=sub.add_parser('import');imp.add_argument('csv')
 pred=sub.add_parser('predict');pred.add_argument('--player',required=True);pred.add_argument('--market',required=True,choices=sorted(MARKETS));pred.add_argument('--line',type=float,required=True);pred.add_argument('--opponent',default='');pred.add_argument('--asof');pred.add_argument('--trials',type=int,default=25000);pred.add_argument('--seed',type=int,default=42);pred.add_argument('--minutes',type=float)
 a=p.parse_args();c=connect(a.db)
 if a.cmd=='import':print(json.dumps({'imported':import_csv(c,a.csv)}))
 else:print(json.dumps(predict(c,a.player,a.market,a.line,a.opponent,a.asof,a.trials,a.seed,a.minutes),indent=2))
if __name__=='__main__':main()
