"""Reconcile the v4.1 targets on a copy of a SHA-256 pinned v3.9 warehouse.

NBA CDN and the archived NBA Stats box score must agree at field level. They
are deliveries from the same statistical authority, not independent providers.
ESPN disagreements are retained in the original ledger, never relabeled as
ESPN verification. A dedicated receipt table records this verification method.
"""
import argparse
import collections
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3

from refresh_and_audit import atomic_json, read_ledger

BASELINE_SHA256 = 'e64f50b037f027fb6b8d1629bdfa739b4d73be99e207e01d9392f5692a4d5a76'
FIELDS = ('player','date','season','team','opponent','home','starter','minutes',
          'pts','reb','ast','stl','blk','tov','fg3m')
STATS = {'pts':('points','points'), 'reb':('rebounds_total','reboundsTotal'),
         'ast':('assists','assists'), 'stl':('steals','steals'),
         'blk':('blocks','blocks'), 'tov':('turnovers','turnovers'),
         'fg3m':('three_pointers_made','threePointersMade')}
ALIASES = {'SA':'SAS','GS':'GSW','NY':'NYK','NO':'NOP','UTAH':'UTA',
           'WSH':'WAS','PHO':'PHX','BRK':'BKN'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def team(value):
    value = str(value)
    return ALIASES.get(value, value)


def integer(value):
    if value is None or isinstance(value, bool):
        raise ValueError('INVALID_STAT')
    n = float(value)
    if not math.isfinite(n) or n < 0 or not n.is_integer():
        raise ValueError('INVALID_STAT')
    return int(n)


def minutes(value, iso=False):
    if iso:
        match = re.fullmatch(r'PT(\d+)M(\d+(?:\.\d+)?)S', str(value))
        if not match:
            raise ValueError('INVALID_CDN_MINUTES')
        m, s = map(float, match.groups())
    else:
        match = re.fullmatch(r'(\d+):(\d+(?:\.\d+)?)', str(value))
        if not match:
            raise ValueError('INVALID_ARCHIVE_MINUTES')
        m, s = map(float, match.groups())
    n = m + s/60
    # NBA Stats rounds seconds, occasionally yielding e.g. 21:60 for 22:00.
    # Accept that carry only in the archive format, then compare with exact CDN time.
    valid_seconds = 0 <= s < 60 or (not iso and s == 60)
    if not (valid_seconds and 0 <= n <= 70):
        raise ValueError('INVALID_MINUTES_RANGE')
    return n


def reconcile_player(target, archive, schedule, payload, canonical_name=None, confirmation=None):
    gid, pid = target['nba_game_id'], target['nba_player_id']
    game = payload['game']
    if str(game['gameId']) != gid or game['gameStatus'] != 3:
        raise ValueError('CDN_GAME_ID_OR_FINAL_STATUS')
    season = f"{int(archive['season'])-1}-{str(archive['season'])[-2:]}"
    if str(archive['game_id']) != gid or str(archive['person_id']) != pid:
        raise ValueError('ARCHIVE_IDENTITY_MISMATCH')
    if str(archive['season_type_id']) != '2' or str(schedule['season_type_id']) != '2':
        raise ValueError('NON_REGULAR_SEASON')
    if schedule['game_status'] != 3 or str(schedule['game_id']) != gid:
        raise ValueError('SCHEDULE_ID_OR_FINAL_STATUS')
    date = str(schedule['game_date_est'])[:10]
    if target['season'] != season or target['date'] != date:
        raise ValueError('LEDGER_DATE_OR_SEASON_CONFLICT')
    # NBA gameEt is local league date; UTC date can roll over at midnight.
    if str(game['gameEt'])[:10] != date:
        raise ValueError('CDN_GAME_DATE_CONFLICT')
    matches = [(side,p) for side in ('homeTeam','awayTeam')
               for p in game[side]['players'] if str(p.get('personId')) == pid]
    if len(matches) != 1:
        raise ValueError('CDN_PLAYER_MATCH_COUNT_' + str(len(matches)))
    side, player = matches[0]
    if str(player['played']) != '1':
        raise ValueError('CDN_DID_NOT_PLAY')
    official_side = 'home' if side == 'homeTeam' else 'away'
    other = 'away' if official_side == 'home' else 'home'
    if archive['side'] != official_side:
        raise ValueError('HOME_AWAY_CONFLICT')
    for side_name, prefix in (('homeTeam','home'),('awayTeam','away')):
        cdn_team = game[side_name]
        if str(cdn_team['teamId']) != str(schedule[prefix+'_team_id']):
            raise ValueError('TEAM_ID_CONFLICT')
        if team(cdn_team['teamTricode']) != team(schedule[prefix+'_team_tricode']):
            raise ValueError('TEAM_CODE_CONFLICT')
        if integer(cdn_team['score']) != integer(schedule[prefix+'_team_score']):
            raise ValueError('TEAM_SCORE_CONFLICT')
        starters = [p for p in cdn_team['players'] if str(p.get('starter')) == '1']
        if len(starters) != 5:
            raise ValueError('CDN_STARTER_COUNT_NOT_FIVE')
    if str(archive['team_id']) != str(game[side]['teamId']):
        raise ValueError('ARCHIVE_TEAM_ID_CONFLICT')
    if team(archive['team_tricode']) != team(game[side]['teamTricode']):
        raise ValueError('ARCHIVE_TEAM_CODE_CONFLICT')
    if str(player['starter']) not in ('0','1'):
        raise ValueError('UNKNOWN_STARTER')
    starter = int(str(player['starter']))
    if starter != int(bool(str(archive.get('position') or '').strip())):
        raise ValueError('STARTER_CONFLICT')
    cdn_minutes = minutes(player['statistics']['minutes'], iso=True)
    archive_minutes = minutes(archive['minutes'])
    if abs(cdn_minutes-archive_minutes)*60 > 1.001:
        raise ValueError('MINUTES_CONFLICT')
    obj = {'player':canonical_name or (archive['first_name']+' '+archive['family_name']).strip(),
           'date':date, 'season':season, 'team':team(archive['team_tricode']),
           'opponent':team(schedule[other+'_team_tricode']),
           'home':int(official_side=='home'), 'starter':starter, 'minutes':cdn_minutes}
    conflicts = {}
    for field, (archive_key, cdn_key) in STATS.items():
        a, b = integer(archive[archive_key]), integer(player['statistics'][cdn_key])
        if a != b:
            if confirmation is None or confirmation.get(field) != a:
                raise ValueError('STAT_CONFLICT_' + field)
            conflicts[field] = {'cdn':b,'archived_nba_stats':a,'fresh_stats_v3_and_league_log':a}
        obj[field] = a
    return obj, {'seven_stats':'ARCHIVE_AND_CDN_EXACT' if not conflicts else 'ARCHIVE_FRESH_STATS_V3_AND_LEAGUE_EXACT', 'date_teams_scores_role':'EXACT',
                 'minutes_difference_seconds':abs(cdn_minutes-archive_minutes)*60,
                 'explicit_played':True, 'zero_minute_appearance':cdn_minutes==0,
                 'archive_minutes_input':archive['minutes'],
                 'cdn_counting_stat_disagreements':conflicts,
                 'method':'ARCHIVED_NBA_STATS_AND_OFFICIAL_CDN' if not conflicts else 'ARCHIVED_NBA_STATS_AND_FRESH_STATS_V3_AND_LEAGUE_LOG',
                 'independent_statistical_providers':False, 'espn_verified':False}


def confirm_stats(target, archive, schedule, directory):
    """Resolve a CDN stat disagreement only with two current official responses."""
    directory=Path(directory);gid,pid=target['nba_game_id'],target['nba_player_id']
    records=json.loads((directory/'fetch_receipt.json').read_text())
    receipts={r['name']:r for r in records}
    if len(receipts)!=len(records):
        raise ValueError('DUPLICATE_CONFIRMATION_RECEIPT')
    source_data=[];datasets=[]
    for name in ('boxscore_'+gid,'league_'+target['season']):
        path=directory/(name+'.json');receipt=receipts[name]
        if receipt['status']!='FETCHED_JSON' or digest(path)!=receipt['sha256']:
            raise ValueError('CONFIRMATION_SOURCE_HASH_OR_FETCH_FAILED')
        raw=path.read_text();datasets.append(json.loads(raw));source_data.append((path,receipt,raw))
    box=datasets[0]['boxScoreTraditional']
    if str(box['gameId'])!=gid:
        raise ValueError('FRESH_STATS_GAME_ID_CONFLICT')
    found=[]
    for side in ('home','away'):
        t=box[side+'Team']
        if str(t['teamId'])!=str(schedule[side+'_team_id']) or team(t['teamTricode'])!=team(schedule[side+'_team_tricode']):
            raise ValueError('FRESH_STATS_TEAM_CONFLICT')
        if integer(t['statistics']['points'])!=integer(schedule[side+'_team_score']):
            raise ValueError('FRESH_STATS_SCORE_CONFLICT')
        if len([p for p in t['players'] if str(p.get('position') or '').strip()])!=5:
            raise ValueError('FRESH_STATS_STARTER_COUNT_NOT_FIVE')
        found.extend((side,p) for p in t['players'] if str(p['personId'])==pid)
    if len(found)!=1 or found[0][0]!=archive['side']:
        raise ValueError('FRESH_STATS_PLAYER_ID_OR_SIDE_CONFLICT')
    p=found[0][1]
    if bool(str(p.get('position') or '').strip())!=bool(str(archive.get('position') or '').strip()):
        raise ValueError('FRESH_STATS_STARTER_CONFLICT')
    if abs(minutes(p['statistics']['minutes'])-minutes(archive['minutes']))*60>1.001:
        raise ValueError('FRESH_STATS_MINUTES_CONFLICT')
    league=datasets[1]
    if league['parameters']['Season']!=target['season']:
        raise ValueError('FRESH_LEAGUE_SEASON_CONFLICT')
    result=league['resultSets'][0]
    rows=[dict(zip(result['headers'],r)) for r in result['rowSet']]
    matches=[r for r in rows if str(r['GAME_ID'])==gid and str(r['PLAYER_ID'])==pid]
    if len(matches)!=1:
        raise ValueError('FRESH_LEAGUE_IDENTITY_NOT_UNIQUE')
    row=matches[0]
    other='away' if archive['side']=='home' else 'home'
    if (row['GAME_DATE']!=target['date'] or str(row['TEAM_ID'])!=str(archive['team_id'])
        or team(row['TEAM_ABBREVIATION'])!=team(archive['team_tricode'])
        or team(row['MATCHUP'].split()[-1])!=team(schedule[other+'_team_tricode'])
        or ('vs.' in row['MATCHUP'])!=(archive['side']=='home')):
        raise ValueError('FRESH_LEAGUE_DATE_TEAM_OR_ROLE_CONFLICT')
    if abs(float(row['MIN'])-minutes(archive['minutes']))>1:
        raise ValueError('FRESH_LEAGUE_MINUTES_CONFLICT')
    stats={}
    for field,(a,b) in STATS.items():
        stats[field]=integer(archive[a])
        if stats[field]!=integer(p['statistics'][b]) or stats[field]!=integer(row[field.upper()]):
            raise ValueError('FRESH_OFFICIAL_STAT_CONFLICT_'+field)
    return stats,source_data


def migrate(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS official_refresh_verifications (
      player TEXT, date TEXT, team TEXT, nba_game_id TEXT, nba_player_id TEXT,
      official_file_sha256 TEXT, cdn_file_sha256 TEXT, verified_at TEXT,
      canonical_json TEXT, check_detail_json TEXT,
      PRIMARY KEY(player,date,team), UNIQUE(nba_game_id,nba_player_id))''')
    conn.execute('''CREATE VIEW IF NOT EXISTS verified_history AS
      SELECT player,date,team,nba_game_id,nba_player_id,espn_game_id,espn_player_id,
        official_file_sha256,espn_file_sha256,verified_at,canonical_json,check_detail_json
        FROM game_verifications
      UNION ALL
      SELECT player,date,team,nba_game_id,nba_player_id,NULL,NULL,
        official_file_sha256,NULL,verified_at,canonical_json,check_detail_json
        FROM official_refresh_verifications''')


def run(baseline, ledger_path, evidence, output, expected_sha256=BASELINE_SHA256, confirmation_dir=None):
    baseline, evidence, output = Path(baseline), Path(evidence), Path(output)
    if digest(baseline) != expected_sha256:
        raise ValueError('BASELINE_SHA256_MISMATCH')
    if output.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    ledger = read_ledger(ledger_path)
    receipts_list = json.loads((evidence/'fetch_receipt.json').read_text())
    receipts = {r['game_id']:r for r in receipts_list}
    if len(receipts) != len(receipts_list):
        raise ValueError('DUPLICATE_GAME_RECEIPT')
    output.mkdir(parents=True)
    db = output/'nba_warehouse.sqlite'
    shutil.copy2(baseline, db)
    if digest(db) != expected_sha256:
        raise RuntimeError('BASELINE_COPY_SHA256_MISMATCH')
    conn = sqlite3.connect(db.resolve().as_uri(), uri=True); conn.row_factory = sqlite3.Row
    before = conn.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    targets = {(r['nba_game_id'],r['nba_player_id']) for r in ledger}
    game_ids = {k[0] for k in targets}
    sources = {r['sha256']:r['name'] for r in conn.execute('SELECT sha256,name FROM source_files')}
    archives, schedules = collections.defaultdict(list), collections.defaultdict(list)
    starter_counts = collections.Counter()
    for h, raw in conn.execute('SELECT file_sha256,payload_json FROM source_records'):
        name = sources[h]
        if not (name.startswith('player_boxscores_') or name.startswith('nba_stats_schedule')):
            continue
        row = json.loads(raw); gid = str(row.get('game_id'))
        if gid not in game_ids:
            continue
        if name.startswith('nba_stats_schedule'):
            schedules[gid].append(row)
        else:
            if str(row.get('position') or '').strip():
                starter_counts[(gid,str(row['team_id']))] += 1
            key = gid, str(row.get('person_id'))
            if key in targets:
                archives[key].append((row,h))
    recovered, unresolved = [], []
    conn.execute('BEGIN')
    migrate(conn)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for target in ledger:
        gid, pid = target['nba_game_id'], target['nba_player_id']
        try:
            receipt = receipts.get(gid)
            if not receipt or receipt['status'] != 'FETCHED_FINAL':
                raise ValueError('OFFICIAL_FETCH_FAILED: ' + str((receipt or {}).get('error','NOT_ATTEMPTED')))
            path = evidence/(gid+'.json')
            cdn_hash = digest(path)
            if cdn_hash != receipt['sha256']:
                raise ValueError('CDN_FILE_SHA256_MISMATCH')
            if len(archives[(gid,pid)]) != 1 or len(schedules[gid]) != 1:
                raise ValueError('ARCHIVE_OR_SCHEDULE_NOT_UNIQUE')
            archive, archive_hash = archives[(gid,pid)][0]
            if starter_counts[(gid,str(archive['team_id']))] != 5:
                raise ValueError('ARCHIVE_STARTER_COUNT_NOT_FIVE')
            names = {r[0] for r in conn.execute('SELECT DISTINCT player FROM game_verifications WHERE nba_player_id=?',(pid,))}
            if len(names) > 1:
                raise ValueError('AMBIGUOUS_CANONICAL_PLAYER_NAME')
            additional_sources=[]
            try:
                obj, detail = reconcile_player(target, archive, schedules[gid][0],
                                               json.loads(path.read_text()), next(iter(names),None))
            except ValueError as exc:
                if confirmation_dir is None or not str(exc).startswith('STAT_CONFLICT_'):
                    raise
                confirmed,additional_sources=confirm_stats(target,archive,schedules[gid][0],confirmation_dir)
                obj, detail = reconcile_player(target, archive, schedules[gid][0],
                                               json.loads(path.read_text()), next(iter(names),None),confirmed)
                detail['confirmation_sources']=[r for p,r,raw in additional_sources]
            if conn.execute('SELECT 1 FROM verified_history WHERE nba_game_id=? AND nba_player_id=?',(gid,pid)).fetchone():
                raise ValueError('DUPLICATE_OFFICIAL_IDENTITY')
            if conn.execute('SELECT 1 FROM games WHERE player=? AND date=? AND team=?',(obj['player'],obj['date'],obj['team'])).fetchone():
                raise ValueError('DUPLICATE_ENGINE_KEY')
            # All validation precedes the savepoint; each promotion is atomic.
            conn.execute('SAVEPOINT promote')
            try:
                conn.execute('INSERT INTO games VALUES ('+','.join('?' for _ in FIELDS)+')',tuple(obj[k] for k in FIELDS))
                detail.update(original_ledger=target, cdn_file_sha256=cdn_hash)
                conn.execute('INSERT INTO official_refresh_verifications VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (obj['player'],obj['date'],obj['team'],gid,pid,archive_hash,cdn_hash,timestamp,
                   json.dumps(obj),json.dumps(detail)))
                conn.execute('INSERT OR IGNORE INTO source_files VALUES (?,?,?,?,?)',
                  (cdn_hash,path.name,'NBA official CDN',receipt.get('url',f'https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json'),json.dumps(receipt)))
                conn.execute('INSERT OR IGNORE INTO source_records VALUES (?,?,?)',(cdn_hash,0,path.read_text()))
                for extra_path,extra_receipt,extra_raw in additional_sources:
                    h=extra_receipt['sha256']
                    conn.execute('INSERT OR IGNORE INTO source_files VALUES (?,?,?,?,?)',
                      (h,extra_path.name,'NBA official Stats API',extra_receipt['url'],json.dumps(extra_receipt)))
                    conn.execute('INSERT OR IGNORE INTO source_records VALUES (?,?,?)',(h,0,extra_raw))
                conn.execute('RELEASE promote')
            except Exception:
                conn.execute('ROLLBACK TO promote'); conn.execute('RELEASE promote'); raise
            recovered.append({**target,'canonical':obj,'checks':detail})
        except Exception as exc:
            unresolved.append({**target,'v41_error_type':type(exc).__name__,'v41_reason':str(exc)})
    if recovered:
        conn.commit()
    else:
        conn.rollback()
    conn.execute('ATTACH DATABASE ? AS baseline',(baseline.resolve().as_uri()+'?mode=ro',))
    changed = conn.execute('SELECT COUNT(*) FROM (SELECT * FROM baseline.games EXCEPT SELECT * FROM main.games)').fetchone()[0]
    after = conn.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if changed or after != before+len(recovered) or integrity != 'ok':
        raise RuntimeError('POST_IMPORT_DATABASE_INVARIANT_FAILED')
    summary = {'baseline_sha256':expected_sha256,'database_sha256':digest(db),
       'database_rows_before':before,'database_rows_after':after,'recovered':len(recovered),
       'remaining':len(unresolved),'baseline_rows_changed_or_removed':changed,
       'sqlite_integrity':integrity,'target_scope_complete':not unresolved,
       'full_historical_coverage_certified':False,'prediction_certification':'NO_TICKET',
       'verification_method':'Archived NBA Stats plus official CDN; discrepant CDN stats require fresh Stats V3 and league logs; no ESPN verification inferred',
       'remaining_reasons':dict(collections.Counter(r['v41_reason'] for r in unresolved))}
    conn.close()
    if digest(baseline) != expected_sha256:
        raise RuntimeError('BASELINE_CHANGED')
    for name,data in [('recovered.json',recovered),('unresolved.json',unresolved),('reconciliation_summary.json',summary)]:
        atomic_json(output/name,data)
    print(json.dumps(summary,indent=2))
    return 0 if not unresolved else 2


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',required=True);p.add_argument('--ledger',required=True)
    p.add_argument('--evidence',required=True);p.add_argument('--out',required=True)
    p.add_argument('--expected-sha256',default=BASELINE_SHA256)
    p.add_argument('--confirmation-dir')
    a=p.parse_args()
    return run(a.baseline,a.ledger,a.evidence,a.out,a.expected_sha256,a.confirmation_dir)


if __name__=='__main__':
    raise SystemExit(main())
