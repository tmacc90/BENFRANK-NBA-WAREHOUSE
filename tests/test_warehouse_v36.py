import unittest
from engine import connect
from warehouse_v36 import stage,audit
class WarehouseV36Tests(unittest.TestCase):
 def test_unknown_starter_is_staged_not_fabricated(self):
  c=connect(':memory:')
  row={'player':'Example','date':'2025-11-01','team':'MIA','opponent':'CHA','season':'2025-26','minutes':30,'pts':20,'reb':10,'ast':5,'stl':1,'blk':1,'tov':2,'fg3m':1}
  r=stage(c,'espn',[row]);self.assertEqual(r['staged'],1)
  self.assertEqual(audit(c,'Example')['verified_engine_rows'],0)
  self.assertIn('STARTER_UNVERIFIED',c.execute('SELECT issue FROM staged_games').fetchone()[0])
 def test_negative_stat_rejected(self):
  c=connect(':memory:');r=stage(c,'espn',[{'player':'X','date':'2025-11-01','team':'MIA','pts':-1}]);self.assertEqual(r['rejected'],1)
 def test_empty_audit(self):
  c=connect(':memory:');self.assertEqual(audit(c)['verified_engine_rows'],0)
if __name__=='__main__':unittest.main()
