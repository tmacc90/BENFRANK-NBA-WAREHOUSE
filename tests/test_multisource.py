import unittest,sqlite3,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import connect,predict
from multisource import import_records,migrate_sources
class MultiSourceTests(unittest.TestCase):
 def setUp(self):
  self.c=connect(':memory:');migrate_sources(self.c)
  self.row={'date':'2025-11-01','season':'2025-26','team':'MIL','opponent':'BOS','home':1,'starter':1,'minutes':'32:30','pts':31,'reb':14,'ast':8,'stl':0,'blk':0,'tov':1,'fg3m':1}
 def tearDown(self):self.c.close()
 def test_import(self):
  r=import_records(self.c,'espn','Giannis',[self.row]);self.assertEqual(r['accepted'],1);self.assertAlmostEqual(self.c.execute('SELECT minutes FROM games').fetchone()[0],32.5)
 def test_conflict_priority(self):
  import_records(self.c,'fox_sports','Giannis',[dict(self.row,pts=30)])
  r=import_records(self.c,'espn','Giannis',[self.row]);self.assertGreater(r['conflicts'],0);self.assertEqual(self.c.execute('SELECT pts FROM games').fetchone()[0],31)
 def test_reject_bad_row(self):
  r=import_records(self.c,'espn','Giannis',[dict(self.row,minutes=-1)]);self.assertEqual(r['accepted'],0);self.assertEqual(r['rejected'],1)
 def test_line_blind(self):
  rows=[dict(self.row,date=f'2025-11-{d:02d}',pts=25+d) for d in range(1,8)]
  import_records(self.c,'espn','Giannis',rows)
  a=predict(self.c,'Giannis','fantasy_score',40,trials=0)['baseline_projection']
  b=predict(self.c,'Giannis','fantasy_score',60,trials=0)['baseline_projection']
  self.assertEqual(a,b)
if __name__=='__main__':unittest.main()
