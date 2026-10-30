"""Read-only audit of saved NBA v4.1 originals; no live endpoint or betting certification.

Accepts a user-owned archive provided locally or on a private runner, verifies
the original NBA LeagueGameLog response hashes and every warehouse player-game,
and never writes back to the package or production database.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

STAT_FIELDS={'pts':'PTS','reb':'REB','ast':'AST','stl':'STL','blk':'BLK','tov':'TOV','fg3m':'FG3M'}
REQUIRED=('DELIVERY_MANIFEST.json','nba_warehouse.sqlite',
          'official_evidence/fresh_stats/fetch_receipt.json')

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def member(archive,name,limit=25_000_000):
    info=archive.getinfo(name)
    if info.file_size>limit:
        raise ValueError('OVERSIZED_ORIGINAL_EVIDENCE:'+name)
    with archive.open(info) as source:
        return source.read(limit+1)

def safe_archive(archive):
    seen=set()
    for item in archive.infolist():
        name=item.filename
        if not name or name.startswith('/') or '\\' in name or '..' in Path(name).parts:
            raise ValueError('UNSAFE_ARCHIVE_MEMBER')
        if name in seen:
            raise ValueError('DUPLICATE_ARCHIVE_MEMBER')
        seen.add(name)
    if sum(item.file_size for item in archive.infolist())>900_000_000:
        raise ValueError('ARCHIVE_UNPACKED_TOO_LARGE')
    for name in REQUIRED:
        if name not in seen:
            raise ValueError('ORIGINAL_EVIDENCE_MISSING:'+name)

def neutrals(c):
    rows=c.execute('SELECT sha256 FROM source_files WHERE name=?',
                   ('nba_stats_schedule_master.parquet',)).fetchall()
    if len(rows)!=1:raise ValueError('OFFICIAL_SCHEDULE_MISSING')
    out=set()
    for (payload,) in c.execute('SELECT payload_json FROM source_records WHERE file_sha256=?',
                              (rows[0][0],)):
        row=json.loads(payload)
        if row.get('is_neutral') in ('true','1',True,1):
            out.add(str(row['game_id']))
    return out

def check_package(archive_path,expected_sha256=None):
    result={'status':'FAILED_OFFLINE_ARCHIVE_AUDIT',
            'scope':'OFFLINE_SAVED_ORIGINAL_NBA_RESPONSES',
            'current_official_endpoint_access':'NOT_TESTED_OFFLINE_MODE',
            'prediction_certification':'NOT_CERTIFIED','ticket_authority':'NO_TICKET',
            'source_warehouse_mutated':False,'seasons':[],'errors':[],
            'checked_at':dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        path=Path(archive_path)
        if not path.is_file():raise ValueError('ARCHIVE_NOT_FOUND')
        with zipfile.ZipFile(path) as archive:
            safe_archive(archive)
            manifest=json.loads(member(archive,'DELIVERY_MANIFEST.json'))
            receipts=json.loads(member(archive,'official_evidence/fresh_stats/fetch_receipt.json'))
            evidence=collections.defaultdict(list)
            for r in receipts:evidence[r.get('name')].append(r)
            with tempfile.TemporaryDirectory(prefix='benfrank-offline-history-') as tmp:
                db=Path(tmp)/'verified.sqlite'
                info=archive.getinfo('nba_warehouse.sqlite')
                if info.file_size>450_000_000:raise ValueError('DATABASE_TOO_LARGE')
                with archive.open(info) as source, db.open('wb') as target:
                    shutil.copyfileobj(source,target,length=1_048_576)
                digest=sha256(db.read_bytes())
                result['database_sha256']=digest
                if digest!=manifest.get('database_sha256'):
                    raise ValueError('ORIGINAL_DELIVERY_MANIFEST_HASH_MISMATCH')
                if expected_sha256 and digest!=expected_sha256:
                    raise ValueError('EXPECTED_WAREHOUSE_HASH_MISMATCH')
                c=sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True)
                c.row_factory=sqlite3.Row
                try:
                    result['database_integrity']=c.execute('PRAGMA integrity_check').fetchone()[0]
                    if result['database_integrity']!='ok':
                        raise ValueError('SQLITE_INTEGRITY_FAILED')
                    duplicates=c.execute('''SELECT COUNT(*) FROM (
                        SELECT nba_game_id,nba_player_id,COUNT(*) n
                        FROM verified_history GROUP BY nba_game_id,nba_player_id HAVING n>1)''').fetchone()[0]
                    if duplicates:raise ValueError('DUPLICATE_OFFICIAL_GAME_PLAYER_ID')
                    neutral_ids=neutrals(c)
                    n=c.execute('SELECT COUNT(*) FROM games').fetchone()[0]
                    result['warehouse_player_games']=n
                    if n!=manifest.get('database_rows'):
                        raise ValueError('MANIFEST_DATABASE_COUNT_MISMATCH')
                    seasons=[r[0] for r in c.execute('SELECT DISTINCT season FROM games ORDER BY season')]
                    if seasons!=sorted(manifest.get('seasons',[])):
                        raise ValueError('SEASON_SCOPE_CONFLICT')
                    for season in seasons:
                        raw=member(archive,'official_evidence/fresh_stats/league_'+season+'.json')
                        digest=sha256(raw)
                        receipts=evidence['league_'+season]
                        if len(receipts)!=1 or receipts[0].get('http_status')!=200:
                            raise ValueError('NO_HASHED_HTTP200_ORIGINAL_RESPONSE:'+season)
                        if not receipts[0].get('url','').startswith(
                              'https://stats.nba.com/stats/leaguegamelog?'):
                            raise ValueError('OFFICIAL_ORIGIN_CONFLICT:'+season)
                        if receipts[0]['sha256']!=digest:
                            raise ValueError('ORIGINAL_RESPONSE_SHA256_CONFLICT:'+season)
                        dataset=json.loads(raw)['resultSets'][0]
                        direct=collections.defaultdict(list)
                        for v in dataset['rowSet']:
                            rec=dict(zip(dataset['headers'],v))
                            direct[(str(rec['GAME_ID']),str(rec['PLAYER_ID']))].append(rec)
                        rows=c.execute('''SELECT g.*,v.nba_game_id,v.nba_player_id,
                            v.canonical_json FROM games g JOIN verified_history v
                            USING(player,date,team) WHERE g.season=?''',(season,))
                        bad=[];seen=set();checked=0
                        for row in rows:
                            checked+=1
                            key=(str(row['nba_game_id']),str(row['nba_player_id']))
                            seen.add(key)
                            choices=direct.get(key,[])
                            if len(choices)!=1:
                                if len(bad)<15:bad.append({'identity':key,'reason':'IDENTITY_NOT_UNIQUE'})
                                continue
                            original=choices[0]
                            canonical=json.loads(row['canonical_json'])
                            problems=[]
                            for field in ('player','date','season','team','opponent',
                                          'home','starter','minutes',*STAT_FIELDS):
                                if row[field]!=canonical.get(field):
                                    problems.append('CANONICAL_'+field)
                            for field,key_name in STAT_FIELDS.items():
                                if float(row[field])!=float(original[key_name]):
                                    problems.append('OFFICIAL_'+field)
                            if row['date']!=str(original['GAME_DATE'])[:10]:
                                problems.append('GAME_DATE')
                            if row['team']!=original['TEAM_ABBREVIATION']:
                                problems.append('TEAM')
                            if row['opponent']!=str(original['MATCHUP']).split()[-1]:
                                problems.append('OPPONENT')
                            if key[0] not in neutral_ids and row['home']!=int('vs.' in original['MATCHUP']):
                                problems.append('HOME')
                            if abs(float(row['minutes'])-float(original['MIN']))>1:
                                problems.append('MINUTES')
                            if problems and len(bad)<15:
                                bad.append({'identity':key,'fields':problems})
                        missing=len(set(direct)-seen)
                        status=('PASS' if checked>0 and len(direct)==checked
                                and missing==0 and not bad else 'FAIL')
                        result['seasons'].append({
                            'season':season,'warehouse_records':checked,
                            'official_records':len(dataset['rowSet']),
                            'official_unique_identities':len(direct),
                            'missing_official_records':missing,
                            'original_source_sha256':digest,
                            'conflict_examples':bad,'status':status})
                        if status!='PASS':result['errors'].append('SEASON_INCOMPLETE:'+season)
                finally:c.close()
                if sha256(db.read_bytes())!=result['database_sha256']:
                    raise ValueError('ORIGINAL_COPY_MUTATED')
        if result['seasons'] and not result['errors']:
            result['status']='PASS_COMPLETE_SELECTED_SEASONS_OFFLINE'
            result['historical_coverage_verified']=True
        else:result['historical_coverage_verified']=False
    except (ValueError,KeyError,TypeError,IndexError,OSError,zipfile.BadZipFile,
            sqlite3.DatabaseError,json.JSONDecodeError) as exc:
        result['errors'].append(type(exc).__name__+': '+str(exc)[:300])
        result['historical_coverage_verified']=False
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--expected-db-sha256')
    args=p.parse_args()
    result=check_package(args.archive,args.expected_db_sha256)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='errors'},indent=2))
    return 0 if result['status']=='PASS_COMPLETE_SELECTED_SEASONS_OFFLINE' else 2

if __name__=='__main__':raise SystemExit(main())
