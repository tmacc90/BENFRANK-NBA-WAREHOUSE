"""Audit saved records against direct official NBA league logs; not calibration."""
import argparse, collections, hashlib, json, sqlite3
from pathlib import Path
from acquire_history import now, team_key, write_json, fetch_source, flag, verification_relation
FIELDS={'pts':'PTS','reb':'REB','ast':'AST','stl':'STL','blk':'BLK','tov':'TOV','fg3m':'FG3M'}
def compare(row,direct,season,neutral_site=False):
 expected={k:direct[v] for k,v in FIELDS.items()}
 expected.update(season=season,date=str(direct['GAME_DATE'])[:10],team=team_key(direct['TEAM_ABBREVIATION']),opponent=team_key(direct['MATCHUP'].split()[-1]),home=int('vs.' in direct['MATCHUP']))
 if neutral_site:expected.pop('home')
 conflicts={k:{'warehouse':row[k],'direct_nba':v} for k,v in expected.items() if row[k]!=v}
 if abs(row['minutes']-float(direct['MIN']))>1:conflicts['minutes']={'warehouse':row['minutes'],'direct_nba':direct['MIN']}
 return conflicts

def run(db,directory,seasons,use_cache=False):
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);results=[]
 if not Path(db).exists():
  report={'status':'FAIL','reason':'WAREHOUSE_MISSING','checked_at':now()};write_json(directory/'direct_nba_verification.json',report);return report
 try:
  manifest=json.loads(Path(__file__).with_name('sources.json').read_text())
  spec=next(s for s in manifest['sources'] if s['kind']=='schedule')
  schedules,_=fetch_source(spec,directory/'source',offline=True)
  neutral_ids={str(r['game_id']) for r in schedules if r.get('is_neutral') in (True,'true','1',1)}
 except Exception as exc:
  report={'status':'FAIL','reason':'NEUTRAL_SITE_EVIDENCE_UNAVAILABLE','error':str(exc)};write_json(directory/'direct_nba_verification.json',report);return report
 c=sqlite3.connect(db);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS direct_nba_checks (nba_game_id TEXT,nba_player_id TEXT,season TEXT,source_sha256 TEXT,checked_at TEXT,result TEXT,detail_json TEXT,PRIMARY KEY(nba_game_id,nba_player_id))')
 for season in seasons:
  path=directory/f'direct_league_{season}.json'
  try:
   method='CACHED_DIRECT_RESPONSE'
   if not use_cache or not path.exists():
    from nba_api.stats.endpoints import leaguegamelog
    response=leaguegamelog.LeagueGameLog(player_or_team_abbreviation='P',season=season,season_type_all_star='Regular Season',timeout=25)
    path.write_text(json.dumps(response.get_dict()));method='FETCHED_DIRECT_NBA_STATS'
   raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();dataset=json.loads(raw)['resultSets'][0];direct=collections.defaultdict(list)
   for values in dataset['rowSet']:
    r=dict(zip(dataset['headers'],values));direct[(str(r['GAME_ID']),str(r['PLAYER_ID']))].append(r)
   relation=verification_relation(c)
   rows=c.execute(f'SELECT g.*,v.nba_game_id,v.nba_player_id FROM games g JOIN {relation} v USING(player,date,team) WHERE g.season=?',(season,)).fetchall()
   matches=0;failures=[];seen=set()
   for row in rows:
    key=(row['nba_game_id'],row['nba_player_id']);seen.add(key);options=direct.get(key,[])
    detail=compare(row,options[0],season,key[0] in neutral_ids) if len(options)==1 else {'identity_match_count':len(options)}
    if detail:failures.append({'nba_game_id':key[0],'nba_player_id':key[1],'player':row['player'],'detail':detail})
    else:matches+=1
    c.execute('INSERT OR REPLACE INTO direct_nba_checks VALUES (?,?,?,?,?,?,?)',(*key,season,digest,now(),'PASS' if not detail else 'FAIL',json.dumps(detail)))
   unimported=[{'nba_game_id':k[0],'nba_player_id':k[1],'player':v[0]['PLAYER_NAME'],'date':v[0]['GAME_DATE']} for k,v in direct.items() if k not in seen]
   result={'season':season,'status':'PASS' if rows and not failures else 'FAIL','method':method,'official_endpoint':'https://stats.nba.com/stats/leaguegamelog','raw_response_sha256':digest,'direct_official_player_games':len(dataset['rowSet']),'warehouse_player_games':len(rows),'matched_warehouse_records':matches,'failed_warehouse_records':len(failures),'failures':failures,'official_records_not_imported':len(unimported),'not_imported_records':unimported,'neutral_site_rows':sum(r['nba_game_id'] in neutral_ids for r in rows)}
  except Exception as exc:result={'season':season,'status':'FAIL','error':type(exc).__name__+': '+str(exc)}
  results.append(result);print(json.dumps({k:v for k,v in result.items() if k not in ('failures','not_imported_records')}),flush=True)
 c.commit();c.close()
 report={'status':'PASS' if results and all(r['status']=='PASS' for r in results) else 'FAIL','checked_at':now(),'seasons':results,'scope':'Imported-row verification only. Missing official records are separately enumerated; no full coverage or predictive certification.','starter_verification':'LeagueGameLog omits starter; see game_verifications boxscore checks','neutral_site_home':'Direct matchup home check excluded only for explicitly neutral games in pinned official schedule. Designated home is verified separately against NBA schedule and ESPN.','minutes_tolerance':1.0}
 write_json(directory/'direct_nba_verification.json',report);return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',default='acquisition/nba_warehouse.sqlite');p.add_argument('--output-dir',default='acquisition');p.add_argument('--seasons',nargs='+',default=['2024-25','2025-26']);p.add_argument('--use-cache',action='store_true');a=p.parse_args()
 return 0 if run(a.db,a.output_dir,a.seasons,a.use_cache)['status']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
