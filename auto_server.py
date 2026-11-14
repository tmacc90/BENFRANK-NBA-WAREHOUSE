import os,json,uuid,threading,pathlib,datetime as dt
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
from benfrank_logs import MARKETS,fetch_with_fallback,analyze
from screenshot_intake import extract_image,parse_text
from player_registry import discover
from source_verification import compare
from benfrank_logs import fetch_nba
TOKEN=os.environ.get('BENFRANK_TOKEN','')
ROOT=pathlib.Path(os.environ.get('BENFRANK_DATA_DIR','/tmp/benfrank_runs'));ROOT.mkdir(parents=True,exist_ok=True)
JOBS={};LOCK=threading.Lock()
def run(jid,props):
 results=[];cache={}
 for p in props:
  rec={'input':p,'status':'BLOCKED'}
  try:
   aid=str(p.get('athlete_id',''));market=p['market'];line=float(p['line'])
   if market not in MARKETS:raise ValueError('Invalid market')
   if aid and not aid.isdigit():raise ValueError('Invalid ESPN ID')
   year=int(p.get('season',dt.datetime.now().year))
   if not p.get('nba_id') and p.get('player_name'):
    p=dict(p);p['nba_id']=discover(p['player_name'],year)['nba_id']
   if not aid and not p.get('nba_id'):raise ValueError('Player name or source ID required')
   seasons={}
   for y in (year-1,year):
    key=(aid,str(p.get('nba_id','')),y)
    if key not in cache:
     rows,url,provider,diagnostics=fetch_with_fallback(aid,y,p.get('nba_id'))
     if not rows:raise ValueError('ESPN schema returned no verified rows for '+str(y))
     cache[key]=(rows,url,provider,diagnostics)
    rows,url,provider,diagnostics=cache[key]
    verification={'status':'NOT_CHECKED','reason':'NBA_ID_UNAVAILABLE'}
    if p.get('nba_id'):
     try:
      nba_rows,nba_url=fetch_nba(p['nba_id'],y)
      verification=compare(rows,nba_rows) if provider!='NBA_STATS' else {'status':'NOT_INDEPENDENT','reason':'ONLY_NBA_STATS_SOURCE_AVAILABLE'}
      verification['source_url']=nba_url
     except Exception as e:verification={'status':'SOURCE_UNAVAILABLE','reason':str(e)[:200]}
    seasons[str(y)]={'source_url':url,'source':provider,'fallback_diagnostics':diagnostics,'verification':verification,'records':len(rows),'summary':analyze(rows,market,line,p.get('opponent'),p.get('cutoff')),'rows':rows}
   rec={'input':p,'status':'DATA_PARSED_NOT_INDEPENDENTLY_VERIFIED','seasons':seasons}
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
  if path not in ('/run-framework','/screenshot-batch'):return self.send(404,{'error':'Not found'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=1000000:raise ValueError('Invalid payload size')
   payload=json.loads(self.rfile.read(size))
   if path=='/screenshot-batch':
    images=payload.get('images',[])
    if not isinstance(images,list) or not 1<=len(images)<=20:raise ValueError('1-20 images required')
    props=[];errors=[]
    for i,img in enumerate(images):
     try:props.append(parse_text(extract_image(img)))
     except Exception as e:errors.append({'index':i,'reason':str(e)})
    if errors:return self.send(422,{'status':'REVIEW_REQUIRED','errors':errors,'recognized':props,'message':'No job started; confirm all recognized props'})
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
