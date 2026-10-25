"""v3.6 verified-source acquisition staging, audit and 24-window readiness.
Does not bypass providers' access controls or assert live imports.
"""
import argparse, csv, datetime as dt, json, sqlite3, math
from pathlib import Path
from engine import connect, WINDOWS, OTHER

SOURCES = {
 'nba_official': {'rank':0,'mode':'official_api_or_permitted_export'},
 'espn': {'rank':1,'mode':'public_api_or_permitted_export'},
 'basketball_reference': {'rank':2,'mode':'permitted_export'},
 'statmuse': {'rank':3,'mode':'permitted_export'},
 'fox_sports': {'rank':4,'mode':'permitted_export'},
 'cbs_sports': {'rank':5,'mode':'permitted_export'},
 'g_league': {'rank':6,'mode':'permitted_export'},
 'college': {'rank':7,'mode':'permitted_export'},
 'fiba': {'rank':8,'mode':'permitted_export'},
}

def migrate(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS acquisition_runs(run_id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, records INTEGER DEFAULT 0, error TEXT);
 CREATE TABLE IF NOT EXISTS staged_games(id INTEGER PRIMARY KEY, player TEXT NOT NULL, game_date TEXT NOT NULL, season TEXT, team TEXT, opponent TEXT, source TEXT NOT NULL, source_game_id TEXT, season_type TEXT DEFAULT 'regular', home INTEGER, starter INTEGER, minutes REAL, pts REAL, reb REAL, ast REAL, stl REAL, blk REAL, tov REAL, fg3m REAL, retrieved_at TEXT NOT NULL, verified INTEGER DEFAULT 0, issue TEXT, UNIQUE(player,game_date,team,source));
 CREATE TABLE IF NOT EXISTS prop_snapshots(id INTEGER PRIMARY KEY, player TEXT NOT NULL, game_date TEXT NOT NULL, market TEXT NOT NULL, line REAL NOT NULL, platform TEXT, captured_at TEXT NOT NULL, scoring_contract TEXT, settlement TEXT);
 CREATE TABLE IF NOT EXISTS external_evidence(id INTEGER PRIMARY KEY, player TEXT, game_date TEXT, category TEXT NOT NULL, source TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL);
 ''');c.commit()

def stage(c, source, rows):
 if source not in SOURCES:raise ValueError('Unknown source')
 migrate(c); now=dt.datetime.now(dt.timezone.utc).isoformat(); ok=0; errors=[]
 for idx,r in enumerate(rows,1):
  try:
   date=dt.date.fromisoformat(str(r.get('date') or r.get('game_date'))).isoformat()
   player=str(r.get('player') or '').strip(); team=str(r.get('team') or '').strip().upper()
   if not player or not team:raise ValueError('player/team missing')
   vals=[]
   for k in ('minutes','pts','reb','ast','stl','blk','tov','fg3m'):
    x=r.get(k); vals.append(float(x) if x not in ('',None) else None)
   if any(x is not None and (not math.isfinite(x) or x<0) for x in vals):raise ValueError('nonfinite or negative stat')
   if vals[0] is not None and vals[0]>70:raise ValueError('minutes > 70')
   home=r.get('home');starter=r.get('starter')
   home=int(home) if home not in ('',None) else None
   starter=int(starter) if starter not in ('',None) else None
   if home not in (0,1,None) or starter not in (0,1,None):raise ValueError('invalid role')
   season_type=str(r.get('season_type') or 'unknown').lower()
   if season_type not in ('regular','playoffs','preseason','playin','unknown'):raise ValueError('invalid season type')
   issue=[]
   if season_type=='unknown':issue.append('SEASON_TYPE_UNVERIFIED')
   if not r.get('season'):issue.append('SEASON_UNVERIFIED')
   if starter is None:issue.append('STARTER_UNVERIFIED')
   if home is None:issue.append('HOME_UNVERIFIED')
   if any(v is None for v in vals):issue.append('STATS_INCOMPLETE')
   if not r.get('source_game_id'):issue.append('GAME_ID_UNVERIFIED')
   if not r.get('opponent'):issue.append('OPPONENT_MISSING')
   c.execute('''INSERT INTO staged_games(player,game_date,season,team,opponent,source,source_game_id,season_type,home,starter,minutes,pts,reb,ast,stl,blk,tov,fg3m,retrieved_at,verified,issue) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(player,game_date,team,source) DO UPDATE SET season=excluded.season,opponent=excluded.opponent,source_game_id=excluded.source_game_id,season_type=excluded.season_type,home=excluded.home,starter=excluded.starter,minutes=excluded.minutes,pts=excluded.pts,reb=excluded.reb,ast=excluded.ast,stl=excluded.stl,blk=excluded.blk,tov=excluded.tov,fg3m=excluded.fg3m,retrieved_at=excluded.retrieved_at,verified=0,issue=excluded.issue''',
    (player,date,r.get('season'),team,r.get('opponent'),source,r.get('source_game_id'),season_type,home,starter,*vals,now,0,';'.join(issue) if issue else 'AWAITING_CROSSCHECK'))
   ok+=1
  except Exception as e:errors.append({'row':idx,'reason':str(e)})
 c.execute('INSERT INTO acquisition_runs(source,started_at,finished_at,status,records,error) VALUES (?,?,?,?,?,?)',(source,now,now,'STAGED' if ok else 'NO_VALID_ROWS',ok,json.dumps(errors)));c.commit()
 return {'staged':ok,'rejected':len(errors),'errors':errors,'promoted_to_verified_games':0}

def audit(c,player=None):
 migrate(c)
 where=' WHERE player=?' if player else '';args=(player,) if player else ()
 total=c.execute('SELECT COUNT(*) FROM games'+where,args).fetchone()[0]
 staged=c.execute('SELECT COUNT(*) FROM staged_games'+where,args).fetchone()[0]
 unverified=c.execute('SELECT COUNT(*) FROM staged_games'+where+(' AND ' if where else ' WHERE ')+'(starter IS NULL OR home IS NULL OR issue IS NOT NULL)',args).fetchone()[0]
 rows=c.execute('SELECT date,season,team,opponent,starter FROM games'+where+' ORDER BY date DESC',args).fetchall()
 return {'verified_engine_rows':total,'staged_source_rows':staged,'staged_with_unresolved_evidence':unverified,'source_coverage':[dict(x) for x in c.execute('SELECT source,COUNT(*) count FROM staged_games'+where+' GROUP BY source',args)],'window_readiness':{**{k:{'available':min(len(rows),n),'required':n,'complete':len(rows)>=n} for k,n in WINDOWS.items()},**{k:{'status':'REQUIRES_CONTEXTUAL_FILTER' if rows else 'NO_DATA'} for k in OTHER}},'ready_for_real_data_calibration':False,'note':'Staged rows never silently become verified predictions. Official or independent cross-check and actual starter/season identity are required.'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',default='nba_warehouse.sqlite');s=p.add_subparsers(dest='cmd',required=True)
 imp=s.add_parser('stage');imp.add_argument('--source',required=True,choices=SOURCES);imp.add_argument('file')
 a=s.add_parser('audit');a.add_argument('--player')
 args=p.parse_args();c=connect(args.db)
 if args.cmd=='audit':out=audit(c,args.player)
 else:
  with open(args.file,encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f)) if args.file.endswith('.csv') else json.load(f)
  out=stage(c,args.source,rows)
 print(json.dumps(out,indent=2))
if __name__=='__main__':main()
