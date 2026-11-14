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
