import unittest,sqlite3,sys
sys.path.insert(0,'..')
from engine import connect,predict
class EngineTests(unittest.TestCase):
 def setUp(self):
  self.c=connect(':memory:')
  for i in range(30):
   self.c.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('Sample Player',f'2026-10-{i+1:02d}' if i<30 else '', '2026-27','MIA','CHA',1,1,30,20+i%4,8+i%3,5,1,1,2,2))
  self.c.commit()
 def test_windows(self):
  r=predict(self.c,'Sample Player','fantasy_score',45,'CHA',trials=100)
  self.assertEqual(len(r['windows']),24);self.assertEqual(r['windows']['L5']['n'],5)
  self.assertEqual(r['simulation']['trials'],100)
 def test_no_future_leak(self):
  r=predict(self.c,'Sample Player','points',20,'CHA',asof='2026-10-10',trials=100)
  self.assertEqual(r['games_available'],9)
 def test_independent_projection(self):
  a=predict(self.c,'Sample Player','points',10,trials=100)
  b=predict(self.c,'Sample Player','points',40,trials=100)
  self.assertEqual(a['baseline_projection'],b['baseline_projection'])
if __name__=='__main__':unittest.main()
