"""Retrying free NBA collector. Cache only successfully parsed rows."""
import hashlib,json,time,urllib.request,urllib.error
from pathlib import Path
from benfrank_logs import BASE,parse,fetch_nba
class FreeSourceNetwork:
 def __init__(self,cache_dir,retries=1):
  self.cache=Path(cache_dir);self.cache.mkdir(parents=True,exist_ok=True);self.retries=retries
 def collect(self,season,espn_id=None,nba_id=None):
  attempts=[]
  for source,identifier in [('ESPN',espn_id),('NBA_STATS',nba_id)]:
   if not identifier:continue
   url=BASE.format(identifier,season) if source=='ESPN' else 'https://stats.nba.com/stats/playergamelog?PlayerID={}&Season={}-{}&SeasonType=Regular+Season'.format(identifier,season-1,str(season)[-2:])
   cache=self.cache/(hashlib.sha256(url.encode()).hexdigest()+'.json')
   if cache.exists() and time.time()-cache.stat().st_mtime<21600:
    try:
     rows=json.loads(cache.read_text())['rows']
     if rows:
      attempts.append({'source':source,'status':'SUCCESS','mode':'CACHE','rows':len(rows)})
      return {'rows':rows,'url':url,'source':source,'attempts':attempts}
    except (ValueError,KeyError,OSError):pass
   errors=[]
   for attempt in range(self.retries+1):
    try:
     if source=='ESPN':
      req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
      with urllib.request.urlopen(req,timeout=12) as response:rows=parse(json.load(response),season)
     else:rows,_=fetch_nba(identifier,season)
     if not rows:raise ValueError('EMPTY_OR_UNRECOGNIZED_SCHEMA')
     tmp=cache.with_suffix('.tmp');tmp.write_text(json.dumps({'rows':rows,'source':source,'url':url}));tmp.replace(cache)
     attempts.append({'source':source,'status':'SUCCESS','mode':'LIVE','rows':len(rows),'prior_errors':errors})
     return {'rows':rows,'url':url,'source':source,'attempts':attempts}
    except (urllib.error.URLError,TimeoutError,ValueError,KeyError,OSError) as exc:
     errors.append({'attempt':attempt+1,'error':type(exc).__name__,'detail':str(exc)[:160]})
     if isinstance(exc,urllib.error.HTTPError) and exc.code in (401,403,404,429):break
     if attempt<self.retries:time.sleep(1)
   attempts.append({'source':source,'status':'FAILED','errors':errors})
  return {'rows':[],'source':None,'url':None,'status':'ALL_SOURCES_FAILED','attempts':attempts}
 def capability_report(self):
  return {'implemented':['ESPN','NBA_STATS'],'not_integrated':['BASKETBALL_REFERENCE','FOX_SPORTS','CBS_SPORTS','STATMUSE','PBP_STATS']}
