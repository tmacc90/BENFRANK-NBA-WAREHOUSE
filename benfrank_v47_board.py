"""Resolve published pregame captures using schedule identity, not future results."""
import argparse
import collections
import csv
import json
import sqlite3
from pathlib import Path

from acquire_history import name_key, team_key, flag
from benfrank_v44_calibration import instant
from benfrank_v44_snapshot_ledger import ingest
from benfrank_v45_evidence import digest, write_json
from benfrank_v46_public_lines import normalize


def normalize_scheduled(root, history, ledger):
    root=Path(root).resolve();rows=[];rejected=[];documents={}
    for receipt_path in sorted(root.rglob('*.receipt.json')):
        receipt=json.loads(receipt_path.read_text())
        raw_path=receipt_path.with_name(receipt_path.name.replace('.receipt.json','.json'))
        if digest(raw_path)!=receipt['raw_sha256']:raise ValueError('PINNED_PUBLIC_CAPTURE_HASH_CONFLICT')
        source=str(raw_path.relative_to(root));receipt_file=str(receipt_path.relative_to(root))
        document=json.loads(raw_path.read_text());documents[source]=document
        normalized,_=normalize(document,receipt,source,receipt_file,digest(receipt_path))
        for s in normalized:
            candidates=[]
            for home,away in ((s['team'],s['opponent']),(s['opponent'],s['team'])):
                candidates.extend(history.schedule_keys.get((s['game_date'],home,away),[]))
            if len(candidates)!=1:
                rejected.append({'snapshot_id':s['snapshot_id'],'reason':'NO_UNIQUE_OFFICIAL_SCHEDULE'});continue
            gid=candidates[0];game=history.schedule[gid]
            tipoff=instant(game['game_date_time_utc'])
            if (instant(s['captured_at'])>=tipoff or abs((tipoff-instant(s['provider_tipoff_utc'])).total_seconds())>1800):
                rejected.append({'snapshot_id':s['snapshot_id'],'reason':'PREGAME_OFFICIAL_TIME_CONFLICT'});continue
            rows.append({**s,'source_snapshot_id':s['snapshot_id'],'snapshot_id':s['snapshot_id']+'-nba',
                'player':history.canonical(s['player']),'game_id':gid,'tipoff_utc':tipoff.isoformat(),
                'identity_mapping_policy':'OFFICIAL_SCHEDULE_PLUS_PUBLISHED_PREGAME_TEAM_NO_POSTGAME_PLAYER_LOOKUP',
                'official_schedule_sha256':history.source_hashes.get('schedule'),'historical_pick_backdated':False})
    with sqlite3.connect(ledger) as conn:
        if rows:ingest(conn,rows)
    return rows,documents,rejected


def cohort(rows,low,high,maximum=60):
    chosen={}
    for s in sorted(rows,key=lambda s:(s['captured_at'],s['snapshot_id'])):
        if low<=s['game_date']<=high and s['market']=='points' and 25<=s['line']<30:
            identity=(s['game_id'],name_key(s['player']))
            chosen.setdefault(identity,s)
    by_game={}
    for s in sorted(chosen.values(),key=lambda s:(s['tipoff_utc'],name_key(s['player']),s['snapshot_id'])):
        by_game.setdefault(s['game_id'],s)
    return sorted(by_game.values(),key=lambda s:(s['tipoff_utc'],s['snapshot_id']))[:maximum]


def season_aggregate_check(espn_csv,nba_aggregate):
    """Secondary per-game labels are not misrepresented as individually NBA verified."""
    import pyarrow.parquet as pq
    official=pq.read_table(nba_aggregate).to_pylist();totals=collections.defaultdict(collections.Counter)
    fields={'pts':'points','reb':'rebounds','ast':'assists','stl':'steals','blk':'blocks','tov':'turnovers','fg3_m':'three_point_field_goals_made'}
    with Path(espn_csv).open() as f:
        for r in csv.DictReader(f):
            if str(r['season_type'])!='2' or flag(r['did_not_play']):continue
            total=totals[name_key(r['athlete_display_name'])];total['gp']+=1
            for k,v in fields.items():total[k]+=float(r[v])
    matched,missing,conflicts=0,[],[]
    for r in official:
        if r['per_mode']!='Totals':raise ValueError('TOTALS_MODE_REQUIRED_FOR_AGGREGATE_CHECK')
        key=name_key(r['player_name']);other=totals.get(key)
        if other is None:missing.append(r['player_name']);continue
        mismatch=[k for k in ('gp',*fields) if other[k]!=float(r[k])]
        if mismatch:conflicts.append({'player':r['player_name'],'fields':mismatch})
        else:matched+=1
    return {'source':'NBA_STATS_MIRROR_SEASON_TOTALS_VS_ESPN_PLAYER_GAME_SUMS','matched_player_totals':matched,
            'official_players':len(official),'missing_identity_matches':missing,'aggregate_conflicts':conflicts,
            'nba_aggregate_sha256':digest(nba_aggregate),'espn_csv_sha256':digest(espn_csv),
            'individual_current_game_stats_direct_official_verified':False,
            'warning':'Season totals validate aggregate consistency, not the distribution across individual games. Current-game labels retain ESPN secondary assurance.'}
