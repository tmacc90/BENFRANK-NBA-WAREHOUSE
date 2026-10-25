import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import reconcile_refresh as repair


def fixture():
    target={'nba_game_id':'0022400001','nba_player_id':'999','season':'2024-25','date':'2024-11-01'}
    archive={'game_id':target['nba_game_id'],'person_id':999,'season':2025,'season_type_id':2,
             'side':'home','team_id':100,'team_tricode':'AAA','position':'',
             'first_name':'Test','family_name':'Player','minutes':'1:07'}
    for key,_ in repair.STATS.values():
        archive[key]=0
    schedule={'game_id':target['nba_game_id'],'season_type_id':2,'game_status':3,
              'game_date_est':target['date'],'home_team_id':100,'away_team_id':200,
              'home_team_tricode':'AAA','away_team_tricode':'BBB','home_team_score':10,'away_team_score':9}
    player={'personId':999,'starter':'0','played':'1',
            'statistics':{'minutes':'PT01M07.00S',**{b:0 for a,b in repair.STATS.values()}}}
    payload={'game':{'gameId':target['nba_game_id'],'gameStatus':3,'gameEt':target['date']+'T20:00:00-04:00',
       'homeTeam':{'teamId':100,'teamTricode':'AAA','score':10,
                   'players':[player]+[{'personId':n,'starter':'1'} for n in range(1,6)]},
       'awayTeam':{'teamId':200,'teamTricode':'BBB','score':9,
                   'players':[{'personId':n,'starter':'1'} for n in range(6,11)]}}}
    return target,archive,schedule,payload


def make_baseline(path, archive, schedule):
    conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE games(player TEXT,date TEXT,season TEXT,team TEXT,opponent TEXT,home INTEGER,starter INTEGER,minutes REAL,pts REAL,reb REAL,ast REAL,stl REAL,blk REAL,tov REAL,fg3m REAL,PRIMARY KEY(player,date,team))')
    conn.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('Existing Player','2024-10-30','2024-25','AAA','BBB',1,0,10,2,1,0,0,0,0,0))
    conn.execute('''CREATE TABLE game_verifications(player TEXT,date TEXT,team TEXT,nba_game_id TEXT,nba_player_id TEXT,espn_game_id TEXT,espn_player_id TEXT,official_file_sha256 TEXT,espn_file_sha256 TEXT,verified_at TEXT,canonical_json TEXT,check_detail_json TEXT)''')
    conn.execute('CREATE TABLE source_files(sha256 TEXT PRIMARY KEY,name TEXT,provider TEXT,url TEXT,metadata_json TEXT)')
    conn.execute('CREATE TABLE source_records(file_sha256 TEXT,row_number INTEGER,payload_json TEXT,PRIMARY KEY(file_sha256,row_number))')
    for h,name in (('archive','player_boxscores_2025.parquet'),('schedule','nba_stats_schedule_master.parquet')):
        conn.execute('INSERT INTO source_files VALUES (?,?,?,?,?)',(h,name,'test fixture','','{}'))
    conn.execute('INSERT INTO source_records VALUES (?,?,?)',('archive',0,json.dumps(archive)))
    for n in range(1,6):
        conn.execute('INSERT INTO source_records VALUES (?,?,?)',('archive',n,json.dumps({**archive,'person_id':n,'position':'G'})))
    conn.execute('INSERT INTO source_records VALUES (?,?,?)',('schedule',0,json.dumps(schedule)))
    conn.commit();conn.close()


class ReconcileRefreshTests(unittest.TestCase):
    def test_valid_exact_ids_ignore_name_alias(self):
        target,archive,schedule,payload=fixture()
        obj,detail=repair.reconcile_player(target,archive,schedule,payload,'Existing Alias')
        self.assertEqual(obj['player'],'Existing Alias')
        self.assertFalse(detail['espn_verified'])
        self.assertFalse(detail['independent_statistical_providers'])
        self.assertEqual(obj['minutes'],1+7/60)

    def test_each_counting_stat_conflict_quarantined(self):
        for field,(a,b) in repair.STATS.items():
            with self.subTest(field=field):
                target,archive,schedule,payload=fixture()
                payload['game']['homeTeam']['players'][0]['statistics'][b]=1
                with self.assertRaisesRegex(ValueError,'STAT_CONFLICT_'+field):
                    repair.reconcile_player(target,archive,schedule,payload)

    def test_wrong_game_date_season_scores_and_role_rejected(self):
        changes=[lambda t,a,s,p:p['game'].update(gameId='0022400999'),
                 lambda t,a,s,p:p['game'].update(gameEt='2024-11-02T01:00:00Z'),
                 lambda t,a,s,p:a.update(season_type_id=4),
                 lambda t,a,s,p:p['game']['awayTeam'].update(score=20),
                 lambda t,a,s,p:a.update(side='away'),
                 lambda t,a,s,p:p['game']['homeTeam']['players'][0].update(starter='1')]
        for change in changes:
            target,archive,schedule,payload=fixture();change(target,archive,schedule,payload)
            with self.assertRaises(ValueError):
                repair.reconcile_player(target,archive,schedule,payload)

    def test_dnp_and_ambiguous_player_rejected(self):
        target,archive,schedule,payload=fixture()
        payload['game']['homeTeam']['players'][0]['played']='0'
        with self.assertRaisesRegex(ValueError,'DID_NOT_PLAY'):
            repair.reconcile_player(target,archive,schedule,payload)
        target,archive,schedule,payload=fixture()
        payload['game']['awayTeam']['players'].append(copy.deepcopy(payload['game']['homeTeam']['players'][0]))
        with self.assertRaisesRegex(ValueError,'MATCH_COUNT_2'):
            repair.reconcile_player(target,archive,schedule,payload)

    def test_zero_minutes_requires_explicit_played(self):
        target,archive,schedule,payload=fixture();archive['minutes']='0:00'
        payload['game']['homeTeam']['players'][0]['statistics']['minutes']='PT00M00.00S'
        obj,detail=repair.reconcile_player(target,archive,schedule,payload)
        self.assertEqual(obj['minutes'],0)
        self.assertTrue(detail['zero_minute_appearance'])

    def test_invalid_or_missing_minutes_never_invented(self):
        for value in (None,'','nan','PT00M60S','PT71M00S'):
            target,archive,schedule,payload=fixture()
            payload['game']['homeTeam']['players'][0]['statistics']['minutes']=value
            with self.assertRaises(ValueError):
                repair.reconcile_player(target,archive,schedule,payload)

    def test_archive_rounded_seconds_carry_matches_precise_official_time(self):
        target,archive,schedule,payload=fixture();archive['minutes']='21:60'
        payload['game']['homeTeam']['players'][0]['statistics']['minutes']='PT21M59.95S'
        obj,detail=repair.reconcile_player(target,archive,schedule,payload)
        self.assertLess(detail['minutes_difference_seconds'],0.051)
        self.assertEqual(detail['archive_minutes_input'],'21:60')

    def test_cdn_disagreement_remains_explicit_after_official_confirmation(self):
        target,archive,schedule,payload=fixture()
        payload['game']['homeTeam']['players'][0]['statistics']['assists']=1
        with self.assertRaisesRegex(ValueError,'STAT_CONFLICT_ast'):
            repair.reconcile_player(target,archive,schedule,payload,confirmation={'ast':1})
        obj,detail=repair.reconcile_player(target,archive,schedule,payload,confirmation={'ast':0})
        self.assertEqual(obj['ast'],0)
        self.assertEqual(detail['cdn_counting_stat_disagreements']['ast']['cdn'],1)
        self.assertFalse(detail['espn_verified'])

    def test_confirmation_requires_saved_response_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);target,archive,schedule,payload=fixture()
            receipts=[]
            for name in ('boxscore_'+target['nba_game_id'],'league_'+target['season']):
                (p/(name+'.json')).write_text('{}')
                receipts.append({'name':name,'status':'FETCHED_JSON','sha256':'bad hash'})
            (p/'fetch_receipt.json').write_text(json.dumps(receipts))
            with self.assertRaisesRegex(ValueError,'SOURCE_HASH_OR_FETCH_FAILED'):
                repair.confirm_stats(target,archive,schedule,p)

    def test_import_preserves_baseline_and_distinguishes_official_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);target,archive,schedule,payload=fixture()
            make_baseline(p/'baseline.sqlite',archive,schedule)
            h=repair.digest(p/'baseline.sqlite')
            (p/'ledger.json').write_text(json.dumps([target]));(p/'evidence').mkdir()
            raw=json.dumps(payload).encode();gid=target['nba_game_id']
            (p/'evidence'/(gid+'.json')).write_bytes(raw)
            (p/'evidence/fetch_receipt.json').write_text(json.dumps([{'game_id':gid,'status':'FETCHED_FINAL','sha256':hashlib.sha256(raw).hexdigest()}]))
            self.assertEqual(repair.run(p/'baseline.sqlite',p/'ledger.json',p/'evidence',p/'out',h),0)
            self.assertEqual(repair.digest(p/'baseline.sqlite'),h)
            with sqlite3.connect(p/'out/nba_warehouse.sqlite') as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM games').fetchone()[0],2)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM official_refresh_verifications').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM game_verifications').fetchone()[0],0)
                self.assertIsNone(c.execute('SELECT espn_file_sha256 FROM verified_history').fetchone()[0])

    def test_no_evidence_keeps_database_byte_identical_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);target,archive,schedule,payload=fixture()
            make_baseline(p/'baseline.sqlite',archive,schedule)
            h=repair.digest(p/'baseline.sqlite')
            (p/'ledger.json').write_text(json.dumps([target]));(p/'evidence').mkdir()
            (p/'evidence/fetch_receipt.json').write_text(json.dumps([{'game_id':target['nba_game_id'],'status':'UNAVAILABLE','error':'403 Forbidden'}]))
            self.assertEqual(repair.run(p/'baseline.sqlite',p/'ledger.json',p/'evidence',p/'out',h),2)
            self.assertEqual(repair.digest(p/'out/nba_warehouse.sqlite'),h)

    def test_baseline_hash_guard_prevents_any_output(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'baseline.sqlite').write_bytes(b'wrong database')
            with self.assertRaisesRegex(ValueError,'BASELINE_SHA256_MISMATCH'):
                repair.run(p/'baseline.sqlite',p/'ledger.json',p/'evidence',p/'out','0'*64)
            self.assertFalse((p/'out').exists())


if __name__=='__main__':
    unittest.main()
