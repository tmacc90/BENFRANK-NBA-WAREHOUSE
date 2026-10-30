import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from benfrank_v44_batch import run_board, run_one
from engine import connect

def player_rows(c, player, pts):
    for i in range(30):
        c.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (player, f'2026-09-{i+1:02d}', '2026-27', 'MIA', 'CHA', 1, 1,
                   30, pts+i%5, 8+i%3, 5, 1, 1, 2, 2))
    c.commit()

class BatchV44Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / 'historic.sqlite')
        c = connect(self.db)
        player_rows(c, 'Example First', 22)
        player_rows(c, 'Example Second', 15)
        c.close()
        self.prop = {'player':'Example First','market':'points','line':20.5,
                     'opponent':'CHA','game_date':'2026-10-29'}
    def tearDown(self):
        self.temp.cleanup()
    def test_multiple_independent_props(self):
        board=[self.prop,{**self.prop,'player':'Example Second','line':18.5}]
        r=run_board(self.db,board,trials=20)
        self.assertEqual(r['input_count'],2)
        self.assertEqual(r['analyzed_count'],2)
        self.assertNotEqual(r['results'][0]['projection'],r['results'][1]['projection'])
        self.assertEqual(r['results'][0]['ticket_authority'],'NO_TICKET')
        self.assertEqual(len(r['results'][0]['audit']['stages']),66)
        self.assertFalse(r['results'][0]['possession_twon_certified'])
        self.assertFalse(r['results'][0]['independent_blind_ai_certified'])
    def test_input_unsupported_blocked_not_skipped(self):
        r=run_board(self.db,[self.prop,{**self.prop,'market':'unsupported'}],trials=10)
        self.assertEqual(r['blocked_count'],1)
        self.assertEqual(r['results'][1]['status'],'BLOCKED')
    def test_fail_missing_database(self):
        with self.assertRaises(FileNotFoundError):
            run_board('/does/not/exist.sqlite',[self.prop],trials=10)
    def test_source_is_not_mutated(self):
        before=Path(self.db).read_bytes()
        run_board(self.db,[self.prop],trials=10)
        self.assertEqual(before,Path(self.db).read_bytes())
    def test_cutoff_after_tipoff_blocked(self):
        p={**self.prop,'captured_at':'2026-10-29T23:00:00Z','tipoff_utc':'2026-10-29T20:00:00Z'}
        r=run_board(self.db,[p],trials=10)
        self.assertEqual(r['blocked_count'],1)
    def test_snapshot_required_to_pass_exact_line(self):
        c=connect(':memory:')
        player_rows(c,'Example First',22)
        r=run_one(c,self.prop,trials=10)
        states={s['id']:s['status'] for s in r['audit']['stages']}
        self.assertEqual(states['exact_line'],'BLOCKED')
        self.assertEqual(states['sequential_twon_25000'],'BLOCKED')
        p={**self.prop,'platform':'PrizePicks','snapshot_id':'test-snapshot',
           'captured_at':'2026-10-29T10:00:00Z','tipoff_utc':'2026-10-29T20:00:00Z'}
        q=run_one(c,p,trials=10)
        states={s['id']:s['status'] for s in q['audit']['stages']}
        self.assertEqual(states['exact_line'],'PASS')
        self.assertEqual(states['asof_timestamp'],'PASS')

if __name__ == '__main__':
    unittest.main()
