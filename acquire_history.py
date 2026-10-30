"""Reproducible v3.7 deployment repair: source import and fail-closed reconciliation.

NBA Stats and ESPN are read through attributed SportsDataverse archives. Mirror
availability is not proof of direct official endpoint availability. Only final
regular-season games with a unique, agreeing cross-source player row are copied
into the legacy engine table. Every discrepancy is retained, without truncation.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import re
import sys
import traceback
import unicodedata
import urllib.request
from pathlib import Path

from engine import FIELDS, connect
from upgrade import migrate as migrate_legacy
from warehouse_v36 import stage

STATS = {'pts': 'points', 'reb': 'rebounds_total', 'ast': 'assists',
         'stl': 'steals', 'blk': 'blocks', 'tov': 'turnovers',
         'fg3m': 'three_pointers_made'}
ESPN_STATS = {'pts': 'points', 'reb': 'rebounds', 'ast': 'assists',
              'stl': 'steals', 'blk': 'blocks', 'tov': 'turnovers',
              'fg3m': 'three_point_field_goals_made'}
TEAMS = {'GS': 'GSW', 'NY': 'NYK', 'SA': 'SAS', 'NO': 'NOP',
         'UTAH': 'UTA', 'WSH': 'WAS', 'PHO': 'PHX', 'BRK': 'BKN'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, default=str, allow_nan=False) + '\n')


def name_key(name):
    # Accent/punctuation normalization only; no fuzzy matching or nickname guesses.
    value = unicodedata.normalize('NFKD', str(name))
    return ''.join(ch for ch in value.casefold() if ch.isalnum() and not unicodedata.combining(ch))


def team_key(name):
    value = str(name).strip().upper()
    return TEAMS.get(value, value)


def flag(value):
    value = str(value).strip().casefold()
    if value in ('true', '1'): return 1
    if value in ('false', '0'): return 0
    raise ValueError('Missing or invalid explicit boolean: ' + value)


def number(value, integral=False):
    if value is None or value == '': raise ValueError('Missing numeric value')
    result = float(value)
    if not math.isfinite(result) or result < 0: raise ValueError('Nonfinite or negative numeric value')
    if integral and not result.is_integer(): raise ValueError('Nonintegral counting stat')
    return int(result) if integral else result


def minutes(value):
    value = str(value).strip()
    if ':' in value:
        a, b = value.split(':')
        secs = number(b)
        # The archived NBA source occasionally rounds seconds to exactly :60.
        # Carry this integer minute instead of rejecting a played appearance;
        # :61 and malformed clocks remain invalid.
        if secs == 60:
            result = number(a) + 1
        elif secs < 60:
            result = number(a) + secs / 60
        else:
            raise ValueError('Invalid seconds')
    else:
        result = number(value)
    if not 0 <= result <= 70: raise ValueError('Minutes outside [0,70]')
    return result


def fetch_source(spec, cache, offline=False):
    path = Path(cache) / spec['name']
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        if offline: raise FileNotFoundError(path)
        req = urllib.request.Request(spec['url'], headers={'User-Agent': 'BENFRANK-NBA/3.7'})
        temp = path.with_suffix(path.suffix + '.partial')
        try:
            with urllib.request.urlopen(req, timeout=45) as response, temp.open('wb') as out:
                if not response.geturl().startswith('https://'): raise ValueError('HTTPS required')
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > 250 * 1024 * 1024: raise ValueError('Source exceeds 250 MiB')
                    out.write(block)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != spec['sha256']: raise ValueError('Source SHA256 mismatch: ' + spec['name'])
    if spec.get('git_blob_sha'):
        git_digest = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
        if git_digest != spec['git_blob_sha']: raise ValueError('Git blob mismatch')
    if path.suffix == '.parquet':
        import pyarrow.parquet as pq
        rows = pq.read_table(path).to_pylist()
    else:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
    return rows, {**spec, 'local_path': str(path.resolve()), 'actual_sha256': digest,
                  'actual_bytes': len(raw), 'input_rows': len(rows), 'retrieved_at': now()}


def migrate(c):
    migrate_legacy(c)
    c.executescript('''
    CREATE TABLE IF NOT EXISTS source_files (
      sha256 TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
      url TEXT NOT NULL, metadata_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS source_records (
      file_sha256 TEXT NOT NULL, row_number INTEGER NOT NULL, payload_json TEXT NOT NULL,
      PRIMARY KEY(file_sha256,row_number));
    CREATE TABLE IF NOT EXISTS game_verifications (
      player TEXT NOT NULL, date TEXT NOT NULL, team TEXT NOT NULL,
      nba_game_id TEXT NOT NULL, nba_player_id TEXT NOT NULL, espn_game_id TEXT NOT NULL,
      espn_player_id TEXT NOT NULL, official_file_sha256 TEXT NOT NULL,
      espn_file_sha256 TEXT NOT NULL, verified_at TEXT NOT NULL,
      canonical_json TEXT NOT NULL, check_detail_json TEXT NOT NULL,
      PRIMARY KEY(player,date,team), UNIQUE(nba_game_id,nba_player_id));
    CREATE TABLE IF NOT EXISTS history_runs (
      id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
      receipt_json TEXT NOT NULL);
    ''')
    c.commit()


def store_source(c, rows, meta):
    c.execute('INSERT OR IGNORE INTO source_files VALUES (?,?,?,?,?)',
              (meta['actual_sha256'],meta['name'],meta['provider'],meta['url'],json.dumps(meta)))
    c.executemany('INSERT OR IGNORE INTO source_records VALUES (?,?,?)',
                  ((meta['actual_sha256'],i,json.dumps(r,default=str,allow_nan=False))
                   for i,r in enumerate(rows,1)))
    c.commit()


def normalize_espn(row, year):
    if int(row['season']) != year: raise ValueError('ESPN season mismatch')
    date = dt.date.fromisoformat(row['game_date']).isoformat()
    if row['season_type'] != '2': return None, 'EXCLUDED_NON_REGULAR'
    if flag(row['did_not_play']): return None, 'EXCLUDED_DNP'
    obj = {'player':row['athlete_display_name'].strip(), 'date':date,
           'season':f'{year-1}-{str(year)[-2:]}', 'team':team_key(row['team_abbreviation']),
           'opponent':team_key(row['opponent_team_abbreviation']),
           'home': {'home':1,'away':0}[row['home_away']], 'starter':flag(row['starter']),
           'minutes':minutes(row['minutes']), 'source_game_id':str(row['game_id']),
           'season_type':'regular', 'espn_player_id':str(row['athlete_id']),
           'team_score':number(row['team_score'],True),
           'opponent_score':number(row['opponent_team_score'],True)}
    obj.update({k:number(row[v],True) for k,v in ESPN_STATS.items()})
    if not obj['player'] or not obj['team'] or not obj['opponent']: raise ValueError('Missing identity')
    return obj, None


def reconcile(c, nba_rows, espn_rows, schedule_rows, year, nba_meta, espn_meta):
    season = f'{year-1}-{str(year)[-2:]}'
    errors = []
    excluded = collections.Counter()
    candidates = collections.defaultdict(list)
    staged_espn = []
    for i, raw in enumerate(espn_rows,1):
        try:
            row, why = normalize_espn(raw,year)
            if why: excluded[why] += 1; continue
            candidates[(row['date'],row['team'],name_key(row['player']))].append(row)
            staged_espn.append(row)
        except Exception as exc:
            errors.append({'source':'espn','row':i,'code':'INVALID_ROW','detail':str(exc)})
    # Source data remains staged even when a different source disagrees.
    staged = stage(c,'espn',staged_espn)
    for error in staged['errors']:
        errors.append({'source':'espn','code':'STAGING_ERROR',**error})
    schedules = collections.defaultdict(list)
    for r in schedule_rows:
        if int(r['season'])==year and str(r['season_type_id'])=='2' and r['game_status']==3:
            schedules[str(r['game_id'])].append(r)
    expected = set(schedules)
    starter_counts = collections.Counter((str(r['game_id']),r['team_id']) for r in nba_rows
                                         if str(r.get('position') or '').strip())
    official_counts = collections.Counter((str(r['game_id']),str(r['person_id'])) for r in nba_rows)
    imported = 0
    seen_games = set()
    official_dnp = 0
    official_eligible = 0
    used_espn = set()
    for i, raw in enumerate(nba_rows,1):
        identity = {'source':'nba_stats_mirror','row':i,'nba_game_id':str(raw.get('game_id')),
                    'nba_player_id':str(raw.get('person_id'))}
        if str(raw.get('season_type_id')) != '2':
            excluded['OFFICIAL_NON_REGULAR'] += 1; continue
        if not str(raw.get('minutes') or '').strip(): official_dnp += 1; continue
        official_eligible += 1
        try:
            game_id = str(raw['game_id'])
            if not re.fullmatch('002[0-9]{7}',game_id): raise ValueError('Invalid official regular game ID')
            if int(raw['season']) != year or game_id[3:5] != str(year-1)[-2:]: raise ValueError('Official season mismatch')
            if official_counts[(game_id,str(raw['person_id']))] != 1: raise ValueError('Duplicate official player/game')
            if len(schedules[game_id]) != 1: raise ValueError('Missing or ambiguous final official schedule')
            g = schedules[game_id][0]
            home = {'home':1,'away':0}[raw['side']]
            side, other = ('home','away') if home else ('away','home')
            if raw['team_id'] != g[side+'_team_id']: raise ValueError('Official team ID/schedule conflict')
            team = team_key(raw['team_tricode'])
            if team != team_key(g[side+'_team_tricode']): raise ValueError('Official team code conflict')
            date = dt.date.fromisoformat(str(g['game_date_est'])[:10]).isoformat()
            player = (str(raw['first_name'])+' '+str(raw['family_name'])).strip()
            obj = {'player':player,'date':date,'season':season,'team':team,
                   'opponent':team_key(g[other+'_team_tricode']),'home':home,
                   'starter':int(bool(str(raw.get('position') or '').strip())),
                   'minutes':minutes(raw['minutes'])}
            if obj['minutes'] <= 0: official_dnp += 1; official_eligible -= 1; continue
            if starter_counts[(game_id,raw['team_id'])] != 5: raise ValueError('Official starting five incomplete')
            obj.update({k:number(raw[v],True) for k,v in STATS.items()})
            matches = candidates.get((date,team,name_key(player)), [])
            if len(matches) != 1: raise ValueError('ESPN_IDENTITY_MATCH_COUNT_'+str(len(matches)))
            match = matches[0]
            conflicts = {k:{'nba':obj[k],'espn':match[k]} for k in ('opponent','home','starter',*STATS)
                         if obj[k] != match[k]}
            if abs(obj['minutes']-match['minutes']) > 1.0:
                conflicts['minutes'] = {'nba':obj['minutes'],'espn':match['minutes']}
            if number(g[side+'_team_score'],True) != match['team_score']:
                conflicts['team_score'] = {'nba':g[side+'_team_score'],'espn':match['team_score']}
            if number(g[other+'_team_score'],True) != match['opponent_score']:
                conflicts['opponent_score'] = {'nba':g[other+'_team_score'],'espn':match['opponent_score']}
            if conflicts:
                errors.append({**identity,'code':'CROSS_SOURCE_CONFLICT','player':player,
                               'date':date,'team':team,'fields':conflicts})
                continue
            values = tuple(obj[k] for k in FIELDS)
            c.execute('INSERT OR REPLACE INTO games VALUES ('+','.join('?' for _ in FIELDS)+')', values)
            detail = {'counting_stats':'EXACT','date_team_opponent_home':'EXACT',
                      'starter':'NBA_POSITION_CONFIRMED_BY_EXPLICIT_ESPN_FLAG',
                      'minutes_tolerance':1.0,'minutes_difference':abs(obj['minutes']-match['minutes']),
                      'scores':'EXACT','neutral_site':bool(g.get('is_neutral')),
                      'home_meaning':'SCHEDULE_DESIGNATED_HOME_NOT_VENUE_ADVANTAGE',
                      'source_access':'THIRD_PARTY_ARCHIVES_NOT_DIRECT_NBA_ACCESS'}
            c.execute('INSERT OR REPLACE INTO game_verifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                      (player,date,team,game_id,str(raw['person_id']),match['source_game_id'],
                       match['espn_player_id'],nba_meta['actual_sha256'],espn_meta['actual_sha256'],
                       now(),json.dumps(obj),json.dumps(detail)))
            c.execute('UPDATE staged_games SET verified=1,issue=NULL WHERE source=? AND player=? AND game_date=? AND team=?',
                      ('espn',match['player'],date,team))
            imported += 1; seen_games.add(game_id)
            used_espn.add((match['date'],match['team'],name_key(match['player'])))
        except Exception as exc:
            errors.append({**identity,'code':'VERIFICATION_REJECTED','detail':str(exc)})
    for key, matches in candidates.items():
        if key not in used_espn:
            errors.append({'source':'espn','code':'NOT_CROSSCHECKED','date':key[0],'team':key[1],
                           'player':matches[0]['player'],'espn_game_id':matches[0]['source_game_id']})
    counts = c.execute('SELECT COUNT(*) FROM games WHERE season=?',(season,)).fetchone()[0]
    c.execute('INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?)',
              ('NBA Stats mirror + ESPN archive','SportsDataverse Player Boxscores and official schedule',
               now(),'*',season,imported,'RECONCILED_PARTIAL' if errors else 'RECONCILED',
               json.dumps({'official_sha256':nba_meta['actual_sha256'],
                           'espn_sha256':espn_meta['actual_sha256'],'failures':len(errors)})))
    c.commit()
    return {'season':season,'official_input_rows':len(nba_rows),'espn_input_rows':len(espn_rows),
            'official_eligible_player_games':official_eligible,'official_dnp_excluded':official_dnp,
            'espn_regular_played_staged':staged['staged'],'crosschecked_player_games':imported,
            'engine_season_rows_after':counts,'official_expected_final_regular_games':len(expected),
            'games_with_at_least_one_crosschecked_player':len(seen_games),
            'official_games_without_any_crosschecked_player':sorted(expected-seen_games),
            'exclusions':dict(excluded),'failure_count':len(errors),'failures':errors,
            'status':'PASS' if not errors and imported>0 and expected==seen_games else 'PARTIAL_OR_FAIL'}


def verification_relation(c):
    """Keep official CDN receipts distinct from the original ESPN verification."""
    return 'verified_history' if c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='verified_history'").fetchone() else 'game_verifications'


def inspect_database(db):
    c = connect(db)
    migrate(c)
    verifications = verification_relation(c)
    unverified = c.execute(f'''SELECT COUNT(*) FROM games g LEFT JOIN {verifications} v
      USING(player,date,team) WHERE v.player IS NULL''').fetchone()[0]
    rows = [dict(r) for r in c.execute(f'''SELECT g.*,v.nba_game_id,v.nba_player_id,v.espn_game_id,
      v.official_file_sha256,v.espn_file_sha256 FROM games g JOIN {verifications} v
      USING(player,date,team) ORDER BY g.date,g.player''')]
    invalid = []
    for r in rows:
        for k in ('minutes',*STATS):
            if r[k] is None or not math.isfinite(r[k]) or r[k]<0: invalid.append({'row':r,'field':k})
    disagreement = 0
    for r in c.execute(f'SELECT g.*,v.canonical_json FROM games g JOIN {verifications} v USING(player,date,team)'):
        original = json.loads(r['canonical_json'])
        if any(r[k]!=original[k] for k in FIELDS): disagreement += 1
    season_counts = [dict(r) for r in c.execute('''SELECT season,COUNT(*) player_games,
      COUNT(DISTINCT player) players,MIN(date) first_date,MAX(date) last_date
      FROM games GROUP BY season''')]
    game_counts = c.execute(f'SELECT COUNT(DISTINCT nba_game_id) FROM {verifications}').fetchone()[0]
    integrity = c.execute('PRAGMA integrity_check').fetchone()[0]
    duplicates = c.execute(f'''SELECT COUNT(*) FROM (SELECT nba_game_id,nba_player_id,COUNT(*) n
      FROM {verifications} GROUP BY nba_game_id,nba_player_id HAVING n>1)''').fetchone()[0]
    representative = [dict(r) for r in c.execute(f'''SELECT g.*,v.nba_game_id,v.nba_player_id,v.espn_game_id
      FROM games g JOIN {verifications} v USING(player,date,team)
      WHERE g.player IN ('Giannis Antetokounmpo','Jayson Tatum','LeBron James')
      ORDER BY g.date DESC LIMIT 12''')]
    result = {'sqlite_integrity':integrity,'engine_rows':len(rows),'distinct_nba_games':game_counts,
              'season_counts':season_counts,'unverified_engine_rows':unverified,'invalid_rows':len(invalid),
              'duplicate_official_identities':duplicates,'stored_receipt_disagreements':disagreement,
              'source_rows':c.execute('SELECT COUNT(*) FROM source_records').fetchone()[0],
              'source_files':c.execute('SELECT COUNT(*) FROM source_files').fetchone()[0],
              'representative_records':representative,
              'prediction_certification':'NOT_EXECUTED_NO_TICKET',
              'direct_official_access':'SEE_OFFICIAL_REFRESH_RECEIPTS' if verifications=='verified_history' else 'NOT_ESTABLISHED_BY_MIRROR_IMPORT'}
    result['integrity_status'] = 'PASS' if integrity=='ok' and not any((unverified,invalid,duplicates,disagreement)) and rows else 'FAIL'
    c.close()
    return result


def run(db, directory, manifest, seasons, offline=False):
    start = now()
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    specs = json.loads(Path(manifest).read_text())['sources']
    years = {int(s[:4])+1 for s in seasons}
    selected = [s for s in specs if s['kind']=='schedule' or s.get('year') in years]
    c = connect(db); migrate(c)
    loaded, metadata, download_errors = {}, [], []
    for spec in selected:
        try:
            rows, meta = fetch_source(spec,directory/'source',offline)
            loaded[(spec['kind'],spec.get('year'))] = (rows,meta)
            store_source(c,rows,meta); metadata.append(meta)
            print(json.dumps({'source':spec['name'],'rows':len(rows),'sha256':meta['actual_sha256']}),flush=True)
        except Exception as exc:
            download_errors.append({'source':spec['name'],'code':'SOURCE_UNAVAILABLE','detail':str(exc)})
    results = []
    for year in sorted(years):
        required = [('schedule',None),('nba_box',year),('espn_box',year)]
        if any(k not in loaded for k in required):
            results.append({'season':f'{year-1}-{str(year)[-2:]}','status':'FAIL_MISSING_SOURCES'});continue
        nba, nm = loaded[('nba_box',year)]; espn, em = loaded[('espn_box',year)]
        schedules, _ = loaded[('schedule',None)]
        result = reconcile(c,nba,espn,schedules,year,nm,em)
        write_json(directory/f'failures_{year}.json',result['failures'])
        summary = {k:v for k,v in result.items() if k!='failures'}
        results.append(summary)
        print(json.dumps(summary),flush=True)
    c.close()
    audit = inspect_database(db)
    write_json(directory/'database_audit.json',audit)
    status = 'PASS' if results and all(r['status']=='PASS' for r in results) and not download_errors and audit['integrity_status']=='PASS' else 'PARTIAL_OR_FAIL'
    receipt = {'version':'3.7-deployment-repair','started_at':start,'finished_at':now(),
               'status':status,'seasons':results,'sources':metadata,'download_failures':download_errors,
               'database_audit':audit,'complete_historical_coverage':status=='PASS',
               'production_prediction_certification':'NOT_EXECUTED_NO_TICKET'}
    write_json(directory/'import_receipt.json',receipt)
    c=connect(db);migrate(c)
    c.execute('INSERT INTO history_runs(started_at,finished_at,receipt_json) VALUES (?,?,?)',
              (start,receipt['finished_at'],json.dumps(receipt)));c.commit();c.close()
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='acquisition/nba_warehouse.sqlite')
    p.add_argument('--output-dir',default='acquisition')
    p.add_argument('--manifest',default='sources.json')
    p.add_argument('--seasons',nargs='+',default=['2024-25','2025-26'])
    p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    for s in a.seasons:
        if not re.fullmatch(r'20\d\d-\d\d',s) or int(s[-2:])!=(int(s[:4])+1)%100:
            p.error('Expected season like 2024-25')
    Path(a.db).parent.mkdir(parents=True,exist_ok=True)
    try:
        result=run(a.db,a.output_dir,a.manifest,a.seasons,a.offline)
    except Exception as exc:
        write_json(Path(a.output_dir)/'fatal_error.json',
                   {'status':'FAIL','finished_at':now(),'error':str(exc),
                    'exception':type(exc).__name__,'traceback':traceback.format_exc()})
        raise
    print(json.dumps({'status':result['status'],'engine_rows':result['database_audit']['engine_rows'],
                      'full_receipt':str(Path(a.output_dir)/'import_receipt.json')}))
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__': sys.exit(main())
