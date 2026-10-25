"""Capture official NBA evidence with bounded requests and durable failure receipts.

This command never changes SQLite and does not equate a successful fetch with
reconciliation. Use reconcile_refresh.py with the preserved baseline afterward.
"""
import argparse
import collections
import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.request

MAX_BYTES = 5_000_000


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read_ledger(path):
    ledger = json.loads(Path(path).read_text())
    if not isinstance(ledger, list) or not ledger:
        raise ValueError('EMPTY_OR_INVALID_LEDGER')
    identities = set()
    for row in ledger:
        gid, pid = row['nba_game_id'], row['nba_player_id']
        if not isinstance(gid, str) or not re.fullmatch(r'002\d{7}', gid):
            raise ValueError('INVALID_REGULAR_SEASON_GAME_ID')
        if not isinstance(pid, str) or not re.fullmatch(r'[1-9]\d*', pid):
            raise ValueError('INVALID_PLAYER_ID')
        if (gid, pid) in identities:
            raise ValueError('DUPLICATE_LEDGER_IDENTITY')
        identities.add((gid, pid))
    return ledger


def fetch_game(gid, timeout, attempts, opener=urllib.request.urlopen, sleeper=time.sleep):
    url = f'https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gid}.json'
    receipt = {'game_id': gid, 'url': url, 'status': 'UNAVAILABLE',
               'started_utc': now(), 'attempts': [], 'sha256': None}
    payload = None
    success_raw = None
    for number in range(1, attempts + 1):
        attempt = {'number': number, 'started_utc': now()}
        raw = None
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                'Referer': 'https://www.nba.com/'})
            with opener(request, timeout=timeout) as response:
                attempt['http_status'] = response.status
                raw = response.read(MAX_BYTES + 1)
            attempt['bytes'] = len(raw)
            attempt['sha256'] = hashlib.sha256(raw).hexdigest()
            if len(raw) > MAX_BYTES:
                raise ValueError('OVERSIZED_RESPONSE')
            data = json.loads(raw)
            game = data['game']
            if str(game['gameId']) != gid:
                raise ValueError('WRONG_GAME_ID')
            if game['gameStatus'] != 3:
                raise ValueError('GAME_NOT_FINAL')
            for side in ('homeTeam', 'awayTeam'):
                if not isinstance(game[side]['players'], list):
                    raise ValueError('INVALID_PLAYER_LIST')
            payload, success_raw = data, raw
            receipt.update(status='FETCHED_FINAL', sha256=attempt['sha256'])
            attempt['status'] = 'FETCHED_FINAL'
        except Exception as exc:
            attempt.update(status='FAILED', error_type=type(exc).__name__, error=str(exc))
            if isinstance(exc, urllib.error.HTTPError):
                attempt['http_status'] = exc.code
        attempt['finished_utc'] = now()
        receipt['attempts'].append(attempt)
        if payload is not None:
            break
        if attempt.get('http_status') in (400, 401, 403, 404):
            break
        if number < attempts:
            sleeper(min(number, 2))
    receipt['finished_utc'] = now()
    receipt['error'] = None if payload is not None else receipt['attempts'][-1]['error']
    return receipt, payload, success_raw


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
    temporary.replace(path)


def snapshot(out, ledger, receipts, payloads, database_rows=None):
    resolved, unresolved = [], []
    for target in ledger:
        gid, pid = target['nba_game_id'], target['nba_player_id']
        receipt = receipts.get(gid)
        record = dict(target, official_cdn_game_id=gid,
                      cdn_status=receipt['status'] if receipt else 'NOT_ATTEMPTED')
        if gid not in payloads:
            record['evidence_status'] = 'FETCH_FAILED' if receipt else 'NOT_ATTEMPTED'
            if receipt:
                record['fetch_error'] = receipt['error']
            unresolved.append(record)
            continue
        game = payloads[gid]['game']
        matches = [(side, player) for side in ('homeTeam', 'awayTeam')
                   for player in game[side]['players'] if str(player.get('personId')) == pid]
        record['player_match_count'] = len(matches)
        if len(matches) != 1:
            record['evidence_status'] = 'PLAYER_NOT_UNIQUELY_FOUND'
            unresolved.append(record)
            continue
        side, player = matches[0]
        record.update(player_found=True, cdn_side=side, cdn_player=player,
                      evidence_status='OFFICIAL_EVIDENCE_CAPTURED_REQUIRES_RECONCILIATION')
        resolved.append(record)
    games = {row['nba_game_id'] for row in ledger}
    summary = {
        'generated_utc': now(), 'requested_games': len(games),
        'requested_records': len(ledger), 'completed_games': len(receipts),
        'fetched_final_games': len(payloads),
        'official_player_evidence_captured': len(resolved),
        'still_unresolved': len(unresolved),
        'database_rows_before': database_rows, 'database_rows_after': database_rows,
        'database_modified': False, 'full_coverage': False, 'prediction_certified': False,
        'capture_complete': len(receipts) == len(games) and not unresolved,
        'notes': 'Evidence capture only. Player presence is not proof of an eligible appearance.'}
    for name, data in [('fetch_receipt.json', [receipts[k] for k in sorted(receipts)]),
                       ('official_player_evidence.json', resolved),
                       ('unresolved.json', unresolved), ('summary.json', summary)]:
        atomic_json(out / name, data)
    return summary


def run(ledger, out, timeout=10, attempts=2, workers=4, db=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    database_rows = None
    if db:
        with sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True) as conn:
            database_rows = conn.execute('SELECT COUNT(*) FROM games').fetchone()[0]
    receipts, payloads = {}, {}
    snapshot(out, ledger, receipts, payloads, database_rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_game, gid, timeout, attempts): gid
                   for gid in sorted({row['nba_game_id'] for row in ledger})}
        for future in concurrent.futures.as_completed(futures):
            gid = futures[future]
            receipt, payload, raw = future.result()
            if payload is not None:
                (out / (gid + '.json')).write_bytes(raw)
                payloads[gid] = payload
            receipts[gid] = receipt
            summary = snapshot(out, ledger, receipts, payloads, database_rows)
            print(json.dumps({'completed': len(receipts), **receipt}), flush=True)
    print(json.dumps(summary), flush=True)
    return 0 if summary['capture_complete'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--db')
    parser.add_argument('--out', default='refresh_results')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--attempts', type=int, default=2)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if not (0 < args.timeout <= 30 and 1 <= args.attempts <= 3 and 1 <= args.workers <= 4):
        parser.error('timeout must be (0,30], attempts 1..3, workers 1..4')
    return run(read_ledger(args.ledger), args.out, args.timeout, args.attempts,
               args.workers, args.db)


if __name__ == '__main__':
    raise SystemExit(main())
