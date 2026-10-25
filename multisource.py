"""BENFRANK NBA v3.4 multi-source import, provenance, conflicts and coverage.

No scraping bypass. ESPN public JSON attempted opportunistically; other sources
support user-exported CSV/JSON until their page layouts can be validated.
"""
import argparse,csv,datetime as dt,json,sqlite3,urllib.request
from pathlib import Path
from engine import connect, FIELDS, predict
from upgrade import migrate

SOURCE_RANK={'nba_official':0,'espn':1,'statmuse':2,'fox_sports':3,'basketball_reference':4,'manual':5}
ALIASES={'date':['date','game_date','GAME_DATE'],'season':['season'],'team':['team','team_abbr'],'opponent':['opponent','opp','opponent_abbr'],'home':['home'],'starter':['starter','started','gs'],'minutes':['minutes','min','MIN'],'pts':['pts','points','PTS'],'reb':['reb','rebounds','REB'],'ast':['ast','assists','AST'],'stl':['stl','steals','STL'],'blk':['blk','blocks','BLK'],'tov':['tov','to','turnovers','TOV'],'fg3m':['fg3m','3pm','3ptm','FG3M']}

def migrate_sources(c):
 migrate(c)
 c.executescript('''CREATE TABLE IF NOT EXISTS source_games (player TEXT NOT NULL,date TEXT NOT NULL,team TEXT NOT NULL,source TEXT NOT NULL,season TEXT,opponent TEXT,home INTEGER,starter INTEGER,minutes REAL,pts REAL,reb REAL,ast REAL,stl REAL,blk REAL,tov REAL,fg3m REAL,retrieved_at TEXT NOT NULL,PRIMARY KEY(player,date,team,source));
 CREATE TABLE IF NOT EXISTS source_conflicts (player TEXT,date TEXT,team TEXT,field TEXT,selected_source TEXT,selected_value TEXT,other_source TEXT,other_value TEXT,recorded_at TEXT);
 CREATE TABLE IF NOT EXISTS import_audit (id INTEGER PRIMARY KEY,source TEXT,player TEXT,filename TEXT,accepted INTEGER,rejected INTEGER,details TEXT,created_at TEXT);''')
 c.commit()

def first(row,names):
 for name in names:
  if name in row and row[name] not in ('',None):return row[name]
 raise ValueError('missing '+names[0])

def minutes_value(x):
 if isinstance(x,str) and ':' in x:
  a,b=x.split(':',1);return int(a)+int(b)/60
 return float(x)

def normalize(row,player,season=None):
 r={}
 for key,names in ALIASES.items():
  try:r[key]=first(row,names)
  except ValueError:
   if key=='season' and season:r[key]=season
   elif key in ('home','starter'):r[key]=None
   else:raise
 d=str(r['date'])
 for fmt in ('%Y-%m-%d','%b %d, %Y','%m/%d/%Y'):
  try:d=dt.datetime.strptime(d,fmt).date().isoformat();break
  except ValueError:pass
 dt.date.fromisoformat(d)
 r['date']=d;r['player']=player
 r['team']=str(r['team']).upper();r['opponent']=str(r['opponent']).upper()
 for k in ('home','starter'):
  if r[k] is None:raise ValueError('unknown '+k+'; cannot invent game role')
  r[k]=int(r[k]);assert r[k] in (0,1)
 for k in ('minutes','pts','reb','ast','stl','blk','tov','fg3m'):
  r[k]=minutes_value(r[k]) if k=='minutes' else float(r[k])
  if r[k]<0:raise ValueError('negative '+k)
 if r['minutes']>70:raise ValueError('minutes over 70')
 if r['fg3m']>r['pts']/3:raise ValueError('3PM exceeds points')
 return r

def reconcile(c,player,date,team):
 sources=c.execute('SELECT * FROM source_games WHERE player=? AND date=? AND team=?',(player,date,team)).fetchall()
 if not sources:return
 chosen=min(sources,key=lambda x:SOURCE_RANK[x['source']]);now=dt.datetime.now(dt.timezone.utc).isoformat()
 c.execute('DELETE FROM source_conflicts WHERE player=? AND date=? AND team=?',(player,date,team))
 for other in sources:
  if other['source']==chosen['source']:continue
  for field in FIELDS[3:]:
   if chosen[field]!=other[field]:
    c.execute('INSERT INTO source_conflicts VALUES (?,?,?,?,?,?,?,?,?)',(player,date,team,field,chosen['source'],str(chosen[field]),other['source'],str(other[field]),now))
 c.execute('INSERT OR REPLACE INTO games VALUES ('+','.join('?' for _ in FIELDS)+')',tuple(chosen[k] for k in FIELDS))

def import_records(c,source,player,rows,season=None,filename='inline'):
 if source not in SOURCE_RANK:raise ValueError('Unsupported source')
 migrate_sources(c);accepted=0;errors=[];keys=set();now=dt.datetime.now(dt.timezone.utc).isoformat()
 for index,row in enumerate(rows,1):
  try:
   r=normalize(row,player,season)
   cols=FIELDS+['source','retrieved_at']
   values=[r[k] for k in FIELDS]+[source,now]
   c.execute('INSERT OR REPLACE INTO source_games ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',values)
   keys.add((r['player'],r['date'],r['team']));accepted+=1
  except Exception as e:errors.append({'row':index,'error':str(e)})
 for key in keys:reconcile(c,*key)
 c.execute('INSERT INTO import_audit (source,player,filename,accepted,rejected,details,created_at) VALUES (?,?,?,?,?,?,?)',(source,player,filename,accepted,len(errors),json.dumps(errors[:100]),now))
 c.commit()
 return {'source':source,'accepted':accepted,'rejected':len(errors),'errors':errors[:20],'total_player_games':c.execute('SELECT COUNT(*) FROM games WHERE player=?',(player,)).fetchone()[0],'conflicts':c.execute('SELECT COUNT(*) FROM source_conflicts WHERE player=?',(player,)).fetchone()[0]}

def read_records(path):
 p=Path(path)
 if p.suffix.lower()=='.csv':
  with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
 if p.suffix.lower()=='.json':
  data=json.loads(p.read_text(encoding='utf-8'))
  if isinstance(data,list):return data
  if isinstance(data,dict) and isinstance(data.get('games'),list):return data['games']
 raise ValueError('Expected CSV or JSON list / {"games": [...]}')

def fetch_espn_json(athlete_id,season,timeout=12):
 """Fetch public ESPN game-log JSON; schema may change. Raw response retained for review."""
 url=f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{int(athlete_id)}/gamelog?season={int(season)}'
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'BENFRANK-NBA-Research/3.4 (public game-log retrieval)','Accept':'application/json'})
  with urllib.request.urlopen(req,timeout=timeout) as response: data=json.load(response)
  return {'status':'FETCHED_RAW_REQUIRES_SCHEMA_VALIDATION','url':url,'data':data}
 except Exception as e:return {'status':'FETCH_FAILED','url':url,'error':f'{type(e).__name__}: {str(e)[:250]}'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',default='nba_warehouse.sqlite');sub=p.add_subparsers(dest='command',required=True)
 imp=sub.add_parser('import');imp.add_argument('--source',required=True,choices=list(SOURCE_RANK));imp.add_argument('--player',required=True);imp.add_argument('--season');imp.add_argument('file')
 fetch=sub.add_parser('fetch-espn');fetch.add_argument('--athlete-id',required=True);fetch.add_argument('--season',type=int,required=True);fetch.add_argument('--output')
 audit=sub.add_parser('audit');audit.add_argument('--player',required=True)
 a=p.parse_args()
 if a.command=='fetch-espn':
  result=fetch_espn_json(a.athlete_id,a.season)
  if a.output and 'data' in result:Path(a.output).write_text(json.dumps(result['data'],indent=2));result.pop('data')
  print(json.dumps(result,indent=2));return
 c=connect(a.db);migrate_sources(c)
 if a.command=='import':result=import_records(c,a.source,a.player,read_records(a.file),a.season,a.file)
 else:
  result={'player':a.player,'games':c.execute('SELECT COUNT(*) FROM games WHERE player=?',(a.player,)).fetchone()[0],'by_source':[dict(x) for x in c.execute('SELECT source,COUNT(*) AS games FROM source_games WHERE player=? GROUP BY source',(a.player,))],'conflicts':c.execute('SELECT COUNT(*) FROM source_conflicts WHERE player=?',(a.player,)).fetchone()[0]}
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
