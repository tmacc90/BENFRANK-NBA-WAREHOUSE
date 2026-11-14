import os,json,uuid,threading,pathlib,datetime as dt
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
from benfrank_logs import MARKETS,fetch_with_fallback,analyze
from screenshot_intake import extract_image,parse_text
from player_registry import load_roster
from player_registry import discover
from source_verification import compare
from benfrank_logs import fetch_nba
from nba_team_boxscores import fetch_team_boxscores,verify_team_games
from free_source_network import FreeSourceNetwork
from benfrank_numerical_engines import evaluate
from web_paste_intake import parse_pasted_logs

def current_nba_season():
 today=dt.datetime.now(dt.timezone.utc)
 return today.year+1 if today.month>=10 else today.year
TOKEN=os.environ.get('BENFRANK_TOKEN','')
ROOT=pathlib.Path(os.environ.get('BENFRANK_DATA_DIR','/tmp/benfrank_runs'));ROOT.mkdir(parents=True,exist_ok=True)
JOBS={};LOCK=threading.Lock()
def run(jid,props):
 results=[];cache={};team_cache={};network=FreeSourceNetwork(ROOT/'source_cache')
 for p in props:
  rec={'input':p,'status':'BLOCKED'}
  try:
   aid=str(p.get('athlete_id',''));market=p['market'];line=float(p['line'])
   if market not in MARKETS:raise ValueError('Invalid market')
   if aid and not aid.isdigit():raise ValueError('Invalid ESPN ID')
   year=int(p.get('season',current_nba_season()))
   if not p.get('nba_id') and p.get('player_name'):
    p=dict(p);p['nba_id']=discover(p['player_name'],year)['nba_id']
   if not aid and not p.get('nba_id') and not p.get('verified_rows'):raise ValueError('Player name or source ID required')
   seasons={}
   if p.get('verified_rows'):
    rows=p['verified_rows'];engines=evaluate(rows,market,line,p.get('opponent'),p.get('cutoff'))
    rec={'input':{k:v for k,v in p.items() if k!='verified_rows'},'status':'WEB_PASTE_NUMERICAL_EXECUTED_SOURCE_REVIEW_REQUIRED','records':len(rows),'source_url':p.get('source_url'),'engines':engines}
    results.append(rec);continue
   for y in (year-1,year):
    key=(aid,str(p.get('nba_id','')),y)
    if key not in cache:
     collected=network.collect(y,espn_id=aid or None,nba_id=p.get('nba_id'))
     rows=collected['rows'];url=collected.get('url');provider=collected.get('source');diagnostics=collected['attempts']
     if not rows:raise ValueError('NO_VERIFIED_PLAYER_GAME_ROWS_'+str(y)+' '+str(diagnostics)[:300])
     cache[key]=(rows,url,provider,diagnostics)
    rows,url,provider,diagnostics=cache[key]
    verification={'status':'NOT_CHECKED','reason':'NBA_ID_UNAVAILABLE'}
    if p.get('nba_id'):
     try:
      nba_rows,nba_url=fetch_nba(p['nba_id'],y)
      verification=compare(rows,nba_rows) if provider!='NBA_STATS' else {'status':'NOT_INDEPENDENT','reason':'ONLY_NBA_STATS_SOURCE_AVAILABLE'}
      verification['source_url']=nba_url
     except Exception as e:verification={'status':'SOURCE_UNAVAILABLE','reason':str(e)[:200]}
    team_verification={'status':'NOT_CHECKED','reason':'NBA_GAME_ID_REQUIRED'}
    if provider=='NBA_STATS':
     if y not in team_cache:
      try:team_cache[y]=fetch_team_boxscores(y)
      except Exception as e:team_cache[y]=e
     if isinstance(team_cache[y],Exception):team_verification={'status':'SOURCE_UNAVAILABLE','reason':str(team_cache[y])[:200]}
     else:
      team_rows,team_url=team_cache[y]
      team_verification=verify_team_games(rows,team_rows)
      team_verification['source_url']=team_url
    else:team_verification={'status':'NOT_COMPARABLE','reason':'ESPN_EVENT_IDS_ARE_NOT_NBA_GAME_IDS'}
    seasons[str(y)]={'team_boxscore_verification':team_verification,'source_url':url,'source':provider,'fallback_diagnostics':diagnostics,'verification':verification,'records':len(rows),'summary':analyze(rows,market,line,p.get('opponent'),p.get('cutoff')),'rows':rows}
   combined=[]
   for sy in sorted(seasons):combined.extend(seasons[sy]['rows'])
   dedup={ (r.get('date'),r.get('opponent')):r for r in combined }
   engines=evaluate(list(dedup.values()),market,line,p.get('opponent'),p.get('cutoff'))
   rec={'input':p,'status':'NUMERICAL_ENGINES_EXECUTED_CALIBRATION_PENDING','seasons':seasons,'engines':engines}
  except Exception as e:rec['reason']=str(e)
  results.append(rec)
 output={'job_id':jid,'results':results,'complete':all(x['status']!='BLOCKED' for x in results),'full_framework_certified':False}
 (ROOT/(jid+'.json')).write_text(json.dumps(output,indent=2))
 with LOCK:JOBS[jid]={'status':'FINISHED','complete':output['complete']}
class Handler(BaseHTTPRequestHandler):
 def send(self,code,obj):
  b=json.dumps(obj).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def auth(self):return bool(TOKEN) and self.headers.get('Authorization')=='Bearer '+TOKEN
 def do_GET(self):
  path=urlparse(self.path).path
  if path=='/health':return self.send(200,{'status':'READY','internet_verified':False})
  if not self.auth():return self.send(401,{'error':'Unauthorized'})
  jid=path.split('/')[-1]
  if path.startswith('/jobs/') and jid in JOBS:
   if JOBS[jid]['status']=='FINISHED':return self.send(200,json.loads((ROOT/(jid+'.json')).read_text()))
   return self.send(200,JOBS[jid])
  return self.send(404,{'error':'Not found'})
 def do_POST(self):
  if not self.auth():return self.send(401,{'error':'Unauthorized'})
  path=urlparse(self.path).path
  if path not in ('/run-framework','/screenshot-batch','/web-paste-batch'):return self.send(404,{'error':'Not found'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=20000000:raise ValueError('Invalid payload size')
   payload=json.loads(self.rfile.read(size))
   if path=='/web-paste-batch':
    props=payload.get('props',[])
    if not isinstance(props,list) or not 1<=len(props)<=100:raise ValueError('1-100 props required')
    for p in props:
     p['verified_rows']=parse_pasted_logs(p.get('game_log_text',''),p.get('source_url',''),p.get('season'))
   elif path=='/screenshot-batch':
    images=payload.get('images',[])
    if not isinstance(images,list) or not 1<=len(images)<=20:raise ValueError('1-20 images required')
    props=[];errors=[]
    try:roster=load_roster(int(payload.get('season',dt.datetime.now().year)))
    except Exception as e:return self.send(503,{'error':'ROSTER_UNAVAILABLE','detail':str(e)[:200]})
    for i,img in enumerate(images):
     try:props.append(parse_text(extract_image(img),roster))
     except Exception as e:errors.append({'index':i,'reason':str(e)})
    if errors:return self.send(422,{'status':'REVIEW_REQUIRED','errors':errors,'recognized':props,'message':'No job started; correct failed screenshot recognition'})
    if not payload.get('confirmed',False):return self.send(422,{'status':'CONFIRM_EXACT_LINES','recognized':props,'message':'Confirm OCR-derived names, markets, and lines; resubmit with confirmed=true'})
   else:props=payload['props']
   if not isinstance(props,list) or not 1<=len(props)<=100:raise ValueError('1-100 props required')
   for p in props:
    if not isinstance(p,dict) or not {'market','line'}<=p.keys() or not any(p.get(k) for k in ('athlete_id','nba_id','player_name')):raise ValueError('Missing player identity, market or line')
   jid=uuid.uuid4().hex
   with LOCK:JOBS[jid]={'status':'RUNNING'}
   threading.Thread(target=run,args=(jid,props),daemon=True).start()
   return self.send(202,{'job_id':jid,'status':'RUNNING','check':'/jobs/'+jid})
  except Exception as e:return self.send(400,{'error':str(e)})
if __name__=='__main__':
 if not TOKEN:raise SystemExit('BENFRANK_TOKEN required')
 ThreadingHTTPServer((os.environ.get('BENFRANK_HOST','127.0.0.1'),int(os.environ.get('PORT','10000'))),Handler).serve_forever()
