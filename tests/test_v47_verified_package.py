"""Regression tests: source package audit cannot fabricate completeness."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from benfrank_v47_verified_package import check_package


class VerifiedArchiveTests(unittest.TestCase):
    def build(self,folder,damage=None):
        root=Path(folder)
        database=root/'nba_warehouse.sqlite'
        c=sqlite3.connect(database)
        c.executescript("""
            CREATE TABLE games (player TEXT,date TEXT,season TEXT,team TEXT,
                opponent TEXT,home INTEGER,starter INTEGER,minutes REAL,pts REAL,
                reb REAL,ast REAL,stl REAL,blk REAL,tov REAL,fg3m REAL);
            CREATE TABLE verified_history (player TEXT,date TEXT,team TEXT,
                nba_game_id TEXT,nba_player_id TEXT,canonical_json TEXT);
            CREATE TABLE source_files (sha256 TEXT,name TEXT);
            CREATE TABLE source_records (file_sha256 TEXT,payload_json TEXT);
        """)
        fields=('player','date','season','team','opponent','home','starter',
                'minutes','pts','reb','ast','stl','blk','tov','fg3m')
        game=('Test Player','2024-10-22','2024-25','BOS','NYK',1,1,
              30.5,15,5,3,1,0,2,1)
        c.execute('INSERT INTO games VALUES ('+','.join('?' for _ in fields)+')',game)
        c.execute('INSERT INTO verified_history VALUES (?,?,?,?,?,?)',(
            game[0],game[1],game[3],'0022400001','123',json.dumps(dict(zip(fields,game)))))
        c.execute('INSERT INTO source_files VALUES (?,?)',
                  ('pinned-schedule-sha','nba_stats_schedule_master.parquet'))
        c.execute('INSERT INTO source_records VALUES (?,?)',
                  ('pinned-schedule-sha',json.dumps({'game_id':'0022400001','is_neutral':False})))
        c.commit();c.close()
        raw=database.read_bytes()
        official={'resultSets':[{'headers':['GAME_ID','PLAYER_ID','GAME_DATE',
                'TEAM_ABBREVIATION','MATCHUP','MIN','PTS','REB','AST','STL',
                'BLK','TOV','FG3M'],
                'rowSet':[['0022400001',123,'2024-10-22','BOS',
                           'BOS vs. NYK',30,15,5,3,1,0,2,1]]}]}
        if damage=='stat':
            official['resultSets'][0]['rowSet'][0][6]=99
        response=json.dumps(official).encode()
        digest=hashlib.sha256(response).hexdigest()
        manifest={'database_rows':1,'seasons':['2024-25'],
                  'database_sha256':hashlib.sha256(raw).hexdigest()}
        if damage=='manifest':manifest['database_sha256']='0'*64
        receipts=[{'name':'league_2024-25','http_status':200,
                   'url':'https://stats.nba.com/stats/leaguegamelog?LeagueID=00',
                   'sha256':digest if damage!='response_hash' else '0'*64}]
        archive=root/'archive.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.write(database,'nba_warehouse.sqlite')
            z.writestr('DELIVERY_MANIFEST.json',json.dumps(manifest))
            z.writestr('official_evidence/fresh_stats/fetch_receipt.json',json.dumps(receipts))
            z.writestr('official_evidence/fresh_stats/league_2024-25.json',response)
        return archive

    def test_source_linked_complete_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            report=check_package(self.build(folder))
            self.assertEqual(report['status'],'PASS_COMPLETE_SELECTED_SEASONS_OFFLINE')
            self.assertEqual(report['warehouse_player_games'],1)
            self.assertFalse(report['source_warehouse_mutated'])
            self.assertEqual(report['ticket_authority'],'NO_TICKET')

    def test_tampered_manifest_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(check_package(self.build(folder,'manifest'))['status'],
                             'FAILED_OFFLINE_ARCHIVE_AUDIT')

    def test_modified_official_stat_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            r=check_package(self.build(folder,'stat'))
            self.assertEqual(r['seasons'][0]['status'],'FAIL')
            self.assertFalse(r['historical_coverage_verified'])

    def test_modified_source_digest_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            r=check_package(self.build(folder,'response_hash'))
            self.assertTrue(any('ORIGINAL_RESPONSE_SHA256_CONFLICT' in x
                                for x in r['errors']))

    def test_missing_archive_cannot_be_marked_passed(self):
        self.assertEqual(check_package('/not/a/real/archive.zip')['status'],
                         'FAILED_OFFLINE_ARCHIVE_AUDIT')


if __name__=='__main__':
    unittest.main()
