"""Synthetic unit fixtures; these never enter production acquisition artifacts."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import connect
from upgrade import acquire
from acquire_history import (fetch_source, flag, migrate, minutes, name_key,
                             normalize_espn, number, reconcile, inspect_database)
from acquisition_gate import audit
from verify_direct_nba import compare


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.c=connect(':memory:');migrate(self.c)
        self.nba=[];self.espn=[]
        for i in range(5):
            self.nba.append(dict(game_id='0022400001',season=2025,season_type_id='2',
                team_id=1610612738,team_tricode='BOS',person_id=100+i,first_name='Test',
                family_name=str(i),position='F',side='home',minutes='30:30',
                points=10,rebounds_total=4,assists=2,steals=1,blocks=0,turnovers=2,
                three_pointers_made=1))
            self.espn.append(dict(game_id='401000001',season='2025',season_type='2',
                game_date='2024-11-12',athlete_id=str(1000+i),athlete_display_name='Test '+str(i),
                team_abbreviation='BOS',opponent_team_abbreviation='ATL',home_away='home',
                starter='true',did_not_play='false',minutes='31',points='10',rebounds='4',
                assists='2',steals='1',blocks='0',turnovers='2',three_point_field_goals_made='1',
                team_score='116',opponent_team_score='117'))
        self.schedule=[dict(game_id='0022400001',season=2025,season_type_id='2',game_status=3,
            home_team_id=1610612738,away_team_id=1610612737,home_team_tricode='BOS',
            away_team_tricode='ATL',game_date_est='2024-11-12T00:00:00Z',
            home_team_score=116,away_team_score=117)]
        self.nm={'actual_sha256':'a'*64};self.em={'actual_sha256':'b'*64}

    def tearDown(self):self.c.close()

    def run_import(self):
        return reconcile(self.c,self.nba,self.espn,self.schedule,2025,self.nm,self.em)

    def test_matching_records_and_idempotence(self):
        r=self.run_import();self.assertEqual(r['crosschecked_player_games'],5)
        self.run_import();self.assertEqual(self.c.execute('SELECT COUNT(*) FROM games').fetchone()[0],5)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM game_verifications').fetchone()[0],5)

    def test_counting_stat_conflict_quarantines_record(self):
        self.espn[0]['points']='999'
        r=self.run_import();self.assertEqual(r['crosschecked_player_games'],4)
        self.assertTrue(any(x['code']=='CROSS_SOURCE_CONFLICT' for x in r['failures']))

    def test_missing_name_match_is_reported_without_crashing(self):
        self.espn[0]['athlete_display_name']='Different player'
        r=self.run_import();self.assertEqual(r['crosschecked_player_games'],4)
        self.assertTrue(any(x['code']=='VERIFICATION_REJECTED' for x in r['failures']))

    def test_duplicate_match_is_not_guessed(self):
        self.espn.append(copy.deepcopy(self.espn[0]))
        self.assertEqual(self.run_import()['crosschecked_player_games'],4)

    def test_starter_flag_conflict_quarantined(self):
        self.espn[0]['starter']='false'
        self.assertEqual(self.run_import()['crosschecked_player_games'],4)

    def test_missing_starter_not_fabricated_by_old_official_adapter(self):
        raw=dict(GAME_DATE='Nov 12, 2024',MATCHUP='BOS vs. ATL',MIN=30,PTS=10,REB=4,
                 AST=2,STL=1,BLK=0,TOV=2,FG3M=1,Game_ID='0022400001')
        with patch('upgrade.fetch_nba',return_value=([raw],'OK')):
            out=acquire(self.c,'Test 0',100,'2024-25')
        self.assertEqual(out['records_imported'],0)
        self.assertIsNone(self.c.execute('SELECT starter FROM staged_games').fetchone()[0])

    def test_playoffs_and_dnp_excluded(self):
        self.espn[0]['did_not_play']='true'
        self.espn[1]['season_type']='3'
        self.assertEqual(self.run_import()['crosschecked_player_games'],3)

    def test_bad_minutes_and_nonfinite_stats_rejected(self):
        for value in ['nan','inf','-1']:
            with self.assertRaises(ValueError):number(value)
        with self.assertRaises(ValueError):minutes('30:80')
        with self.assertRaises(ValueError):flag('')

    def test_source_checksum_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'source.csv').write_text('a\n1\n')
            with self.assertRaises(ValueError):
                fetch_source({'name':'source.csv','sha256':'0'*64},d,True)

    def test_direct_official_stat_conflict_detected(self):
        row={'season':'2024-25','date':'2024-11-12','team':'BOS','opponent':'ATL',
             'home':1,'minutes':30.5,'pts':10,'reb':4,'ast':2,'stl':1,'blk':0,'tov':2,'fg3m':1}
        official={'GAME_DATE':'2024-11-12','TEAM_ABBREVIATION':'BOS','MATCHUP':'BOS vs. ATL',
                  'MIN':31,'PTS':11,'REB':4,'AST':2,'STL':1,'BLK':0,'TOV':2,'FG3M':1}
        self.assertIn('pts',compare(row,official,'2024-25'))
        official['PTS']=10
        self.assertEqual(compare(row,official,'2024-25'),{})
        official['MATCHUP']='BOS @ ATL'
        self.assertIn('home',compare(row,official,'2024-25'))
        self.assertEqual(compare(row,official,'2024-25',neutral_site=True),{})

    def test_gate_rejects_manually_inserted_games_without_identities(self):
        with tempfile.TemporaryDirectory() as d:
            db=str(Path(d,'db.sqlite'));c=connect(db);migrate(c)
            c.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('Test','2024-11-12','2024-25','BOS','ATL',1,1,30,10,4,2,1,0,2,1))
            c.execute('INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?)',
                ('demo','demo','2024-11-12','Test','2024-25',1,'test','test'))
            c.commit();c.close()
            self.assertEqual(audit(db,'Test',['2024-25'],1)['status'],'FAIL')


if __name__=='__main__':unittest.main()
