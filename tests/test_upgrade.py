import unittest,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import connect
from upgrade import migrate,market_components,independent_model,hell_tests,enriched,walkforward
class UpgradeTests(unittest.TestCase):
 def setUp(self):
  self.c=connect(':memory:');migrate(self.c)
  for i in range(35):
   self.c.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('Demo',(__import__('datetime').date(2026,1,1)+__import__('datetime').timedelta(days=i)).isoformat(),'2025-26','MIA','CHA',1,1,30,20+i%10,8,5,1,1,2,2))
  self.c.commit()
 def test_enriched(self):
  a=enriched(self.c,'Demo','fantasy_score',40,'CHA','2026-03-01',200)
  self.assertEqual(len(a['windows']),24);self.assertEqual(a['hell_tests']['scenario_count'],16)
  self.assertEqual(a['simulation']['trials'],200)
 def test_line_blind(self):
  a=enriched(self.c,'Demo','points',10,asof='2026-03-01',trials=10)
  b=enriched(self.c,'Demo','points',30,asof='2026-03-01',trials=10)
  self.assertEqual(a['baseline_projection'],b['baseline_projection'])
  self.assertEqual(a['alternative_line_blind_model']['projection'],b['alternative_line_blind_model']['projection'])
 def test_walkforward(self):
  a=walkforward(self.c,'Demo','points',25)
  self.assertGreater(a['n'],0)
if __name__=='__main__':unittest.main()
