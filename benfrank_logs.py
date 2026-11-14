import json,urllib.request,datetime as dt
BASE='https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{}/gamelog?season={}&seasontype=2'
MARKETS={'points':['pts'],'rebounds':['reb'],'assists':['ast'],'pr':['pts','reb'],'pa':['pts','ast'],'ra':['reb','ast'],'pra':['pts','reb','ast']}
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'BENFRANK/1.0','Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
def parse(data,season):
 events=data.get('events',{})
 if isinstance(events,list):events={str(x.get('id')):x for x in events}
 rows={}
 for st in data.get('seasonTypes',[]):
  if str(st.get('id',st.get('type','2')))!='2':continue
  for cat in st.get('categories',[]):
   labels=[str(x).upper() for x in (cat.get('labels') or data.get('labels') or [])]
   for event in cat.get('events',[]):
    eid=str(event.get('eventId',event.get('id','')))
    info=events.get(eid,{})
    values=event.get('stats',[])
    stats={str(k).upper():v for k,v in values.items()} if isinstance(values,dict) else dict(zip(labels,values))
    date=str(info.get('gameDate',info.get('date',event.get('date',''))))[:10]
    if not eid or not date:continue
    opp=info.get('opponent',event.get('opponent',{}))
    if not isinstance(opp,dict):opp={}
    row=rows.setdefault(eid,{'event_id':eid,'date':date,'season':season,'opponent':opp.get('abbreviation','')})
    for label,key in [('PTS','pts'),('REB','reb'),('AST','ast'),('MIN','min')]:
     try:row[key]=float(stats[label])
     except (KeyError,TypeError,ValueError):pass
 return sorted([r for r in rows.values() if all(k in r for k in ('pts','reb','ast'))],key=lambda r:r['date'])
def analyze(rows,market,line,opponent=None,cutoff=None):
 eligible=[r for r in rows if not cutoff or r['date']<cutoff]
 def count(group):
  vals=[sum(r[k] for k in MARKETS[market]) for r in group]
  return {'games':len(vals),'over':sum(x>line for x in vals),'under':sum(x<line for x in vals),'push':sum(x==line for x in vals),'average':sum(vals)/len(vals) if vals else None}
 return {'full':count(eligible),'windows':{'L'+str(n):count(eligible[-n:]) if len(eligible)>=n else {'status':'INSUFFICIENT_GAMES','available':len(eligible)} for n in (5,10,15,20,25,32,52)},'h2h':count([r for r in eligible if r['opponent'].upper()==opponent.upper()]) if opponent else None}

# Independent NBA Stats fallback. IDs differ from ESPN; never substitute one for another.
NBA_URL='https://stats.nba.com/stats/playergamelog?PlayerID={}&Season={}-{}&SeasonType=Regular+Season'
def parse_nba(data,season):
 sets=data.get('resultSets') or data.get('resultSet') or []
 if isinstance(sets,dict):sets=[sets]
 rows=[]
 for s in sets:
  headers=s.get('headers',[])
  for values in s.get('rowSet',[]):
   r=dict(zip(headers,values))
   try:
    from datetime import datetime
    date=datetime.strptime(str(r['GAME_DATE'])[:11],'%b %d, %Y').strftime('%Y-%m-%d')
    match=str(r.get('MATCHUP',''))
    opponent=match.split()[-1]
    rows.append({'event_id':str(r['Game_ID']),'date':date,'season':season,
     'opponent':opponent,'pts':float(r['PTS']),'reb':float(r['REB']),
     'ast':float(r['AST']),'min':float(r['MIN']),'source':'NBA_STATS'})
   except (KeyError,ValueError,TypeError,IndexError):continue
 return sorted(rows,key=lambda r:r['date'])
def fetch_nba(nba_id,season):
 if not str(nba_id).isdigit():raise ValueError('NBA_ID_REQUIRED')
 url=NBA_URL.format(nba_id,season-1,str(season)[-2:])
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36','Referer':'https://www.nba.com/','Origin':'https://www.nba.com','Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=12) as r:data=json.load(r)
 return parse_nba(data,season),url
def fetch_with_fallback(espn_id,season,nba_id=None):
 errors=[]
 if espn_id:
  url=BASE.format(espn_id,season)
  try:
   rows=parse(fetch(url),season)
   if rows:return rows,url,'ESPN',errors
   errors.append('ESPN_EMPTY_OR_SCHEMA_CHANGED')
  except Exception as e:errors.append('ESPN: '+type(e).__name__+': '+str(e)[:160])
 if nba_id:
  try:
   rows,url=fetch_nba(nba_id,season)
   if rows:return rows,url,'NBA_STATS',errors
   errors.append('NBA_STATS_EMPTY_OR_SCHEMA_CHANGED')
  except Exception as e:errors.append('NBA_STATS: '+type(e).__name__+': '+str(e)[:160])
 raise RuntimeError('ALL_AVAILABLE_SOURCES_FAILED: '+'; '.join(errors or ['NO_PLAYER_ID']))
