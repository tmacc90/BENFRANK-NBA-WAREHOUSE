"""BENFRANK v3.7: explicit-schema, source-attributed Parquet/CSV staging.
No automatic promotion to verified NBA games. Requires permitted local source files.
"""
import argparse, csv, json, pathlib, sqlite3
from warehouse_v36 import stage, audit
from engine import connect

REQUIRED = ('player','date','season','team','opponent','minutes','pts','reb','ast','stl','blk','tov','fg3m')
OPTIONAL = ('home','starter','source_game_id','season_type')

def read_rows(path):
    p=pathlib.Path(path)
    if p.suffix.lower()=='.csv':
        with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    if p.suffix.lower()=='.json':
        with p.open(encoding='utf-8') as f:
            obj=json.load(f)
        if not isinstance(obj,list):raise ValueError('JSON must be an array of game records')
        return obj
    if p.suffix.lower()=='.parquet':
        try:import pyarrow.parquet as pq
        except ImportError as e:raise RuntimeError('Install optional dependency: pip install pyarrow') from e
        return pq.read_table(p).to_pylist()
    raise ValueError('Expected .csv, .json or .parquet')

def normalize(rows,mapping,player=None,season=None):
    result=[]
    for r in rows:
        obj={field:r.get(mapping.get(field,field)) for field in REQUIRED+OPTIONAL}
        if player and not obj['player']:obj['player']=player
        if season and not obj['season']:obj['season']=season
        if hasattr(obj['date'],'isoformat'):obj['date']=obj['date'].isoformat()[:10]
        if obj.get('season_type') is None:obj['season_type']='unknown'
        result.append(obj)
    return result

def ingest(db,path,source,mapping=None,player=None,season=None):
    rows=read_rows(path)
    if not rows:return {'staged':0,'rejected':0,'error':'EMPTY_FILE','status':'FAIL'}
    normalized=normalize(rows,mapping or {},player,season)
    c=connect(db)
    result=stage(c,source,normalized)
    result.update({'input_rows':len(rows),'verified_engine_rows_added':0,'source_file':str(path),'audit':audit(c,player)})
    result['status']='STAGED_NOT_VERIFIED' if result['staged'] and not result['rejected'] else 'FAIL'
    c.close()
    return result

def main():
    p=argparse.ArgumentParser(description='Stage permitted historical NBA CSV/JSON/Parquet with explicit schema map')
    p.add_argument('file');p.add_argument('--db',default='nba_warehouse.sqlite');p.add_argument('--source',default='nba_official');p.add_argument('--mapping',help='JSON file mapping canonical field to source column');p.add_argument('--player');p.add_argument('--season');p.add_argument('--output')
    a=p.parse_args(); mapping=json.load(open(a.mapping,encoding='utf-8')) if a.mapping else {}
    output=ingest(a.db,a.file,a.source,mapping,a.player,a.season)
    payload=json.dumps(output,indent=2,default=str)
    if a.output:pathlib.Path(a.output).write_text(payload,encoding='utf-8')
    print(payload)
    if output.get('status')=='FAIL':raise SystemExit(2)
if __name__=='__main__':main()
