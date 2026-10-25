import argparse, collections, datetime, hashlib, json, pathlib, sqlite3, time, urllib.request

def main():
 p=argparse.ArgumentParser();p.add_argument('--ledger',required=True);p.add_argument('--db',default=None);p.add_argument('--out',default='refresh_results');p.add_argument('--timeout',type=int,default=20);a=p.parse_args()
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
 ledger=json.loads(pathlib.Path(a.ledger).read_text());bygame=collections.defaultdict(list)
 for x in ledger:bygame[x['nba_game_id']].append(x)
 before=None
 if a.db:
  con=sqlite3.connect(a.db);con.row_factory=sqlite3.Row
  before=con.execute('select count(*) from games').fetchone()[0]
  con.close()
 results=[];resolved=[];unresolved=[]
 for gid,targets in sorted(bygame.items()):
  url=f'https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json'; payload=None;error=None
  for attempt in range(3):
   try:
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=a.timeout) as response: raw=response.read(5000001)
    if len(raw)>5000000:raise ValueError('oversized')
    payload=json.loads(raw);game=payload['game']
    if str(game['gameId'])!=gid or int(game['gameStatus'])!=3:raise ValueError('wrong game or not final')
    (out/(gid+'.json')).write_bytes(raw)
    break
   except Exception as exc:error=str(exc);time.sleep(min(2**attempt,4));payload=None
  results.append({'game_id':gid,'status':'FETCHED_FINAL' if payload else 'UNAVAILABLE','error':None if payload else error,'sha256':hashlib.sha256(raw).hexdigest() if payload else None})
  for target in targets:
   record={**target,'official_cdn_game_id':gid,'cdn_status':'FETCHED_FINAL' if payload else 'UNAVAILABLE'}
   if payload:
    matches=[player for side in ('homeTeam','awayTeam') for player in payload['game'].get(side,{}).get('players',[]) if str(player.get('personId'))==str(target['nba_player_id'])]
    record['player_found']=len(matches)==1
    if len(matches)==1:
     record['cdn_player']={'name':matches[0].get('name'),'statistics':matches[0].get('statistics'),'played':matches[0].get('played'),'starter':matches[0].get('starter')}
     record['evidence_status']='INDEPENDENT_OFFICIAL_EVIDENCE_CAPTURED_REQUIRES_RECONCILIATION'
     resolved.append(record)
    else:record['evidence_status']='PLAYER_NOT_UNIQUELY_FOUND';unresolved.append(record)
   else:record['evidence_status']='FETCH_FAILED';unresolved.append(record)
 summary={'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'requested_games':len(bygame),'requested_records':len(ledger),'fetched_final_games':sum(x['status']=='FETCHED_FINAL' for x in results),'official_player_evidence_captured':len(resolved),'still_unresolved':len(unresolved),'database_rows_before':before,'database_rows_after':before,'database_modified':False,'full_coverage':False,'prediction_certified':False,'notes':'Evidence capture only. No records promoted until independent field-level reconciliation with provenance.'}
 for name,obj in [('fetch_receipt.json',results),('official_player_evidence.json',resolved),('unresolved.json',unresolved),('summary.json',summary)]: (out/name).write_text(json.dumps(obj,indent=2,default=str))
 print(json.dumps(summary));return 0 if len(results) and summary['fetched_final_games']==len(results) else 2
if __name__=='__main__':raise SystemExit(main())
