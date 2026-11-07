"""Append-only player-specific acquisition and reconciliation for the NBA runner.

ESPN's season argument is the END year. Only regular-season appearances are
normalized. NBA mirror observations are independently attributed, never called
direct NBA responses. Retrieval time is never rewritten as publication time.
"""
import collections
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import sqlite3
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from acquire_history import name_key, team_key
from espn_live_stage import parse_minutes, season_for_date
from benfrank_v44_shots import parse_attempts
from benfrank_v44_calibration import instant

BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
WEB = 'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/'
PP = 'https://api.prizepicks.com/projections?league_id=7&per_page=250&single_stat=true'
HOSTS = {'site.api.espn.com', 'site.web.api.espn.com', 'cdn.nba.com',
         'raw.githubusercontent.com', 'api.prizepicks.com'}
COUNTS = ('pts', 'reb', 'ast', 'stl', 'blk', 'tov', 'fg3m',
          'fgm', 'fga', 'fg3a', 'ftm', 'fta', 'fg2m', 'fg2a', 'oreb', 'dreb')
ET = ZoneInfo('America/New_York')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def encode(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False)


def sha(obj):
    return hashlib.sha256(encode(obj).encode()).hexdigest()


def download(url, timeout=18, limit=25_000_000):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS:
        raise ValueError('UNAPPROVED_SOURCE_URL')
    if parsed.hostname == 'raw.githubusercontent.com' and not parsed.path.startswith(
            '/sportsdataverse/hoopR-nba-stats-data/'):
        raise ValueError('UNAPPROVED_ARCHIVE_PATH')
    request = urllib.request.Request(url, headers={
        'User-Agent': 'BENFRANK-NBA-Research/6.1', 'Accept': 'application/json,*/*'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if urlparse(response.geturl()).hostname != parsed.hostname:
            raise ValueError('SOURCE_REDIRECT_HOST_CONFLICT')
        raw = response.read(limit + 1)
        if response.status != 200 or not raw or len(raw) > limit:
            raise ValueError('SOURCE_HTTP_EMPTY_OR_OVERSIZE')
    return raw


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'raw').mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'acquisition.sqlite')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS documents(
          id TEXT PRIMARY KEY, url TEXT NOT NULL, family TEXT NOT NULL,
          retrieved_utc TEXT NOT NULL, sha256 TEXT NOT NULL, file TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(
          id TEXT PRIMARY KEY, player_key TEXT NOT NULL, game_key TEXT NOT NULL,
          document_id TEXT NOT NULL REFERENCES documents(id), payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS failures(
          id TEXT PRIMARY KEY, url TEXT NOT NULL, observed_utc TEXT NOT NULL, reason TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS observation_player ON observations(player_key,game_key);
        ''')
        for table in ('documents', 'observations', 'failures'):
            for action in ('UPDATE', 'DELETE'):
                self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action}
                  BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_SOURCE_EVIDENCE'); END''')
        self.db.commit()

    def save(self, url, raw, family, retrieved=None):
        retrieved = retrieved or now()
        digest = hashlib.sha256(raw).hexdigest()
        relative = 'raw/' + digest + '.bin'
        path = self.root / relative
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError('CONTENT_ADDRESS_CONFLICT')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
        meta = dict(url=url, family=family, retrieved_utc=retrieved,
                    sha256=digest, file=relative)
        meta['id'] = sha(meta)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?,?)',
                            tuple(meta[k] for k in ('id', 'url', 'family', 'retrieved_utc', 'sha256', 'file')))
        return meta

    def failure(self, url, error):
        record = dict(url=url, observed_utc=now(), reason=type(error).__name__ + ': ' + str(error))
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO failures VALUES(?,?,?,?)',
                            (sha(record), record['url'], record['observed_utc'], record['reason']))

    def fetch(self, url, family, fetcher=download):
        try:
            raw = fetcher(url)
        except Exception as error:
            self.failure(url, error)
            raise ValueError('SOURCE_FETCH_FAILED:' + url + ':' + type(error).__name__ + ': ' + str(error)) from error
        return raw, self.save(url, raw, family)

    def cached(self, url, max_age_hours=6):
        row = self.db.execute('SELECT * FROM documents WHERE url=? ORDER BY retrieved_utc DESC LIMIT 1', (url,)).fetchone()
        if row and 0 <= (instant(now()) - instant(row['retrieved_utc'])).total_seconds() <= max_age_hours * 3600:
            meta = dict(row); raw = (self.root / meta['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != meta['sha256']:
                raise ValueError('CACHED_RAW_SOURCE_HASH_CONFLICT')
            return raw, meta
        return None

    def many(self, jobs, workers=6, fetcher=download):
        """Network parallelism; all SQLite writes stay on the owning thread."""
        result = {}
        def one(item):
            key, (url, family) = item
            return key, url, family, fetcher(url), now()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(one, item): item for item in jobs.items()}
            for future in concurrent.futures.as_completed(pending):
                key, (url, family) = pending[future]
                try:
                    _, _, _, raw, captured = future.result()
                    result[key] = (raw, self.save(url, raw, family, captured))
                except Exception as error:
                    self.failure(url, error)
                if len(result) and len(result) % 20 == 0:
                    print(encode(dict(stage='raw_acquisition_progress', acquired=len(result), requested=len(jobs))), flush=True)
        return result

    def ingest(self, row, document):
        required = ('player', 'date', 'team', 'opponent', 'source_game_id', 'tipoff_utc')
        if any(not row.get(k) for k in required):
            raise ValueError('MISSING_PLAYER_GAME_IDENTITY')
        dt.date.fromisoformat(row['date'])
        if instant(row['tipoff_utc']).astimezone(ET).date().isoformat() != row['date']:
            raise ValueError('GAME_TIMESTAMP_DATE_CONFLICT')
        if row['team'] == row['opponent'] or row.get('home') not in (0, 1):
            raise ValueError('INVALID_TEAM_OR_HOME_IDENTITY')
        for field in COUNTS:
            v = row.get(field)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))
                                  or not math.isfinite(v) or int(v) != v or v < 0):
                raise ValueError('INVALID_COUNTING_STAT:' + field)
        if not isinstance(row.get('minutes'), (int, float)) or not 0 < row['minutes'] <= 70:
            raise ValueError('INVALID_PLAYED_MINUTES')
        if all(row.get(k) is not None for k in ('fgm', 'fg3m', 'ftm', 'pts')):
            if 2 * row['fgm'] + row['fg3m'] + row['ftm'] != row['pts']:
                raise ValueError('SHOOTING_POINT_CONSERVATION_CONFLICT')
        for made, attempted in (('fgm', 'fga'), ('fg3m', 'fg3a'), ('ftm', 'fta'), ('fg2m', 'fg2a')):
            if row.get(made) is not None and row.get(attempted) is not None and row[made] > row[attempted]:
                raise ValueError('SHOT_MAKES_EXCEED_ATTEMPTS')
        if all(row.get(k) is not None for k in ('oreb', 'dreb', 'reb')) and row['oreb'] + row['dreb'] != row['reb']:
            raise ValueError('REBOUND_CONSERVATION_CONFLICT')
        registered = self.db.execute('SELECT * FROM documents WHERE id=?', (document['id'],)).fetchone()
        if not registered or registered['sha256'] != document['sha256']:
            raise ValueError('RAW_SOURCE_RECEIPT_MISSING')
        home, away = (row['team'], row['opponent']) if row['home'] else (row['opponent'], row['team'])
        game_key = row['date'] + '|' + away + '@' + home
        payload = dict(row, document_id=document['id'], source_sha256=document['sha256'],
                       source_url=document['url'], source_family=document['family'],
                       retrieved_utc=document['retrieved_utc'], game_key=game_key)
        identity = sha(payload)
        self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)',
                        (identity, name_key(row['player']), game_key, document['id'], encode(payload)))

    def reconcile(self, cutoff_utc, game_date, strict_observed=False):
        """Cutoff filtering precedes comparisons: future corrections cannot leak in."""
        cutoff = instant(cutoff_utc)
        groups = collections.defaultdict(list)
        excluded = collections.Counter()
        for stored in self.db.execute('SELECT * FROM observations ORDER BY player_key,game_key,id'):
            r = json.loads(stored['payload_json'])
            if r['date'] >= game_date or instant(r['tipoff_utc']) >= cutoff:
                excluded['TARGET_OR_FUTURE_GAME'] += 1
                continue
            if strict_observed and instant(r['retrieved_utc']) > cutoff:
                excluded['RETRIEVED_AFTER_ORIGINAL_CUTOFF'] += 1
                continue
            # Game logs have no reliable final flag. A very recent row must be
            # confirmed by a terminal summary before it can become a feature.
            if (r['source_family'] == 'ESPN' and r.get('completed') is not True
                    and (instant(r['retrieved_utc']) - instant(r['tipoff_utc'])).total_seconds() < 8 * 3600):
                excluded['RECENT_GAMELOG_REQUIRES_FINAL_SUMMARY'] += 1
                continue
            # Neutral-site providers can disagree on nominal home designation.
            # Group by the two teams FIRST, then quarantine that disagreement.
            pair_key = r['date'] + '|' + '~'.join(sorted((r['team'], r['opponent'])))
            groups[(stored['player_key'], pair_key)].append(r)
        accepted, conflicts = [], []
        for (player, game), variants in groups.items():
            mismatch = []
            for field in (*COUNTS, 'home', 'team', 'opponent', 'date'):
                values = {r[field] for r in variants if r.get(field) is not None}
                if len(values) > 1:
                    mismatch.append(field)
            # ESPN season logs round minutes; tolerate that explicit representation only.
            minutes = [r['minutes'] for r in variants]
            if max(minutes) - min(minutes) > 1.01:
                mismatch.append('minutes')
            stamps = [instant(r['tipoff_utc']) for r in variants]
            if (max(stamps) - min(stamps)).total_seconds() > 7200:
                mismatch.append('TIPOFF_TIMESTAMP_DISAGREEMENT_OVER_TWO_HOURS')
            for family in {r['source_family'] for r in variants}:
                ids = {r['source_game_id'] for r in variants if r['source_family'] == family}
                if len(ids) > 1:
                    mismatch.append('AMBIGUOUS_' + family + '_GAME_ID')
                pids = {r['source_player_id'] for r in variants
                        if r['source_family'] == family and r.get('source_player_id')}
                if len(pids) > 1:
                    mismatch.append('AMBIGUOUS_' + family + '_PLAYER_ID')
            if mismatch:
                conflicts.append(dict(player_key=player, game_key=game, fields=mismatch,
                                      variants=variants, disposition='QUARANTINED_ALL_VARIANTS'))
                continue
            # Prefer complete, precise boxes; merge only nonconflicting observed fields.
            ordered = sorted(variants, key=lambda r: (sum(r.get(k) is not None for k in COUNTS),
                              r.get('minutes_precision') == 'seconds', r['retrieved_utc']), reverse=True)
            r = dict(ordered[0])
            for k in (*COUNTS, 'starter'):
                if r.get(k) is None:
                    r[k] = next((v[k] for v in ordered if v.get(k) is not None), None)
            families = sorted({v['source_family'] for v in variants})
            r.update(game_id=game, corroborating_families=families,
                     independent_sources_agree=len(families) >= 2,
                     source_documents=sorted({v['document_id'] for v in variants}),
                     source_game_ids={f: sorted({v['source_game_id'] for v in variants
                                                if v['source_family'] == f}) for f in families},
                     assurance='CROSS_PROVIDER_AGREEMENT' if len(families) >= 2 else 'SINGLE_PROVIDER_VALIDATED_RESEARCH',
                     original_publication_time_verified=False)
            accepted.append(r)
        return dict(records=accepted, conflicts=conflicts, exclusions=dict(excluded),
                    strict_observed_by_cutoff=strict_observed,
                    source_correction_vintage_verified=False)

    def manifest(self):
        return dict(documents=[dict(r) for r in self.db.execute('SELECT * FROM documents ORDER BY retrieved_utc,id')],
                    failures=[dict(r) for r in self.db.execute('SELECT * FROM failures ORDER BY observed_utc,id')],
                    observations=self.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0])


def parse_gamelog(document, player, player_id, end_year):
    labels = document.get('labels') or []
    required = ('MIN', 'FG', '3PT', 'FT', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'TO')
    if not all(k in labels for k in required):
        if not document.get('events') and not document.get('seasonTypes'):
            return [], [dict(reason='NO_PUBLISHED_NBA_GAMELOG_FOR_PLAYER_SEASON')]
        raise ValueError('ESPN_GAMELOG_STAT_SCHEMA_CHANGED')
    rows, rejected, seen = [], [], set()
    for season_type in document.get('seasonTypes') or []:
        # The API has put all-star appearances inside regular-season categories.
        if season_type.get('displayName') != f'{end_year-1}-{str(end_year)[-2:]} Regular Season':
            continue
        for group in season_type.get('categories') or []:
            if group.get('type') != 'event':
                continue
            for entry in group.get('events') or []:
                eid = str(entry.get('eventId', ''))
                try:
                    if eid in seen:
                        raise ValueError('DUPLICATE_SEASON_GAME_ID')
                    seen.add(eid)
                    event = document['events'][eid]
                    if str(event.get('id')) != eid:
                        raise ValueError('GAMELOG_EVENT_ID_CONFLICT')
                    if event.get('team', {}).get('isAllStar') or event.get('opponent', {}).get('isAllStar'):
                        continue
                    stamp = event['gameDate']
                    day = instant(stamp).astimezone(ET).date().isoformat()
                    if season_for_date(day) != f'{end_year-1}-{str(end_year)[-2:]}':
                        raise ValueError('GAMELOG_SEASON_DATE_CONFLICT')
                    stats = entry['stats']
                    if len(stats) != len(labels):
                        raise ValueError('ESPN_GAMELOG_STAT_WIDTH_CONFLICT')
                    values = dict(zip(labels, stats))
                    shots = parse_attempts(values['FG'], values['3PT'], values['FT'], values['PTS'])
                    row = dict(player=player, source_player_id=str(player_id), source_game_id=eid,
                               tipoff_utc=stamp, date=day, season=season_for_date(day),
                               team=team_key(event['team']['abbreviation']),
                               opponent=team_key(event['opponent']['abbreviation']),
                               home=int(event['atVs'] == 'vs'), starter=None,
                               minutes=parse_minutes(values['MIN']),
                               minutes_precision='seconds' if ':' in str(values['MIN']) else 'rounded_minutes',
                               **{key: int(values[label]) for key, label in
                                  (('pts', 'PTS'), ('reb', 'REB'), ('ast', 'AST'), ('stl', 'STL'),
                                   ('blk', 'BLK'), ('tov', 'TO'))}, **shots)
                    if event['atVs'] not in ('vs', '@'):
                        raise ValueError('UNKNOWN_HOME_AWAY_FLAG')
                    if not row['team'].isalpha() or not row['opponent'].isalpha():
                        raise ValueError('NON_NBA_ALL_STAR_TEAM')
                    if row['minutes'] > 0:
                        rows.append(row)
                except (ValueError, KeyError, TypeError) as error:
                    rejected.append(dict(event_id=eid, reason=str(error)))
    return rows, rejected


def acquire_logs(store, players, day, seasons=3, fetcher=download):
    """Acquire at least L52 when records exist, cascading to earlier seasons."""
    end = dt.date.fromisoformat(day).year + (dt.date.fromisoformat(day).month >= 7)
    audit = []
    jobs = {pid + '|' + str(year): (WEB + pid + '/gamelog?season=' + str(year), 'ESPN')
            for pid in players for year in range(end, end - seasons, -1)}
    responses = {k: cached for k, (url, _) in jobs.items() if (cached := store.cached(url)) is not None}
    responses.update(store.many({k: v for k, v in jobs.items() if k not in responses}, fetcher=fetcher))
    for key, (raw, meta) in responses.items():
        pid, year = key.split('|')
        try:
            rows, rejects = parse_gamelog(json.loads(raw), players[pid], pid, int(year))
            for row in rows:
                store.ingest(row, meta)
            store.db.commit()
            audit.append(dict(player=players[pid], espn_player_id=pid, season_end_year=int(year),
                              parsed=len(rows), rejected=rejects, source_document=meta))
        except Exception as error:
            store.db.rollback()
            store.failure(meta['url'], error)
    return audit


def acquire_mirror(store, players, source_config, fetcher=download):
    """Pinned NBA Stats mirror: independent upstream from ESPN, archived vintage."""
    import pyarrow.parquet as pq
    import pyarrow as pa
    wanted = {name_key(n) for n in players}
    sources = json.loads(Path(source_config).read_text())['sources']
    sources = [s for s in sources if s['kind'] in ('schedule', 'nba_box')]
    responses = {s['name']: cached for s in sources if (cached := store.cached(s['url'], 24 * 365)) is not None}
    responses.update(store.many({s['name']: (s['url'], 'NBA_STATS_ARCHIVE') for s in sources
                                if s['name'] not in responses}, fetcher=fetcher))
    tables, metas, audit = {}, {}, []
    for s in sources:
        if s['name'] not in responses:
            continue
        raw, meta = responses[s['name']]
        if hashlib.sha256(raw).hexdigest() != s['sha256']:
            store.failure(s['url'], ValueError('PINNED_ARCHIVE_HASH_CONFLICT'))
            continue
        tables[s['name']] = pq.read_table(pa.BufferReader(raw)).to_pylist()
        metas[s['name']] = meta
    schedule_name = next((s['name'] for s in sources if s['kind'] == 'schedule'), None)
    schedule = {str(g['game_id']): g for g in tables.get(schedule_name, [])
                if str(g.get('season_type_id')) == '2'}
    for s in sources:
        if s['kind'] != 'nba_box' or s['name'] not in tables:
            continue
        count = 0
        for raw in tables[s['name']]:
            name = raw['first_name'] + ' ' + raw['family_name']
            if name_key(name) not in wanted or not raw.get('minutes') or str(raw.get('season_type_id')) != '2':
                continue
            game = schedule.get(str(raw['game_id']))
            if not game:
                continue
            try:
                stamp = game['game_date_time_utc']
                day = instant(stamp).astimezone(ET).date().isoformat()
                home, away = team_key(game['home_team_tricode']), team_key(game['away_team_tricode'])
                team = team_key(raw['team_tricode'])
                if team not in (home, away):
                    raise ValueError('ARCHIVE_SCHEDULE_TEAM_CONFLICT')
                row = dict(player=name, source_player_id=str(raw['person_id']),
                           source_game_id=str(raw['game_id']), tipoff_utc=stamp,
                           date=day, season=season_for_date(day), team=team,
                           opponent=away if team == home else home, home=int(team == home),
                           starter=int(bool(raw.get('position'))), minutes=parse_minutes(raw['minutes']),
                           minutes_precision='seconds',
                           **{k: raw[field] for k, field in (
                               ('pts', 'points'), ('reb', 'rebounds_total'), ('ast', 'assists'),
                               ('stl', 'steals'), ('blk', 'blocks'), ('tov', 'turnovers'),
                               ('fgm', 'field_goals_made'), ('fga', 'field_goals_attempted'),
                               ('fg3m', 'three_pointers_made'), ('fg3a', 'three_pointers_attempted'),
                               ('ftm', 'free_throws_made'), ('fta', 'free_throws_attempted'),
                               ('oreb', 'rebounds_offensive'), ('dreb', 'rebounds_defensive'))})
                row.update(fg2m=row['fgm'] - row['fg3m'], fg2a=row['fga'] - row['fg3a'])
                if row['minutes'] > 0:
                    store.ingest(row, metas[s['name']]); count += 1
            except (ValueError, KeyError, TypeError) as error:
                audit.append(dict(player=name, game_id=raw['game_id'], reason=str(error)))
        store.db.commit()
        audit.append(dict(source=s['name'], observations=count, sha256=metas[s['name']]['sha256'],
                          authority='PINNED_NBA_STATS_MIRROR_NOT_DIRECT_NBA_RESPONSE'))
    return audit


def write_history(records, path):
    """New derived read model only; never opens an existing warehouse for writing."""
    from engine import connect, FIELDS
    path = Path(path)
    if path.exists():
        raise FileExistsError('DERIVED_HISTORY_ALREADY_EXISTS')
    conn = connect(path)
    try:
        for row in records:
            if any(row.get(k) is None for k in FIELDS if k != 'starter'):
                continue
            conn.execute('INSERT INTO games VALUES(' + ','.join('?' for _ in FIELDS) + ')',
                         tuple(row.get(k) for k in FIELDS))
        conn.commit()
    finally:
        conn.close()
