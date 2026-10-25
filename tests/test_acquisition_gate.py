import os,sqlite3,tempfile,unittest
from acquisition_gate import audit
from engine import connect
from upgrade import migrate

class AcquisitionGateTests(unittest.TestCase):
 def test_missing_warehouse_fails(self):
  self.assertEqual(audit('/nonexistent/warehouse.sqlite','X',['2025-26'],1)['status'],'FAIL')
 def test_empty_warehouse_fails(self):
  with tempfile.TemporaryDirectory() as d:
   p=os.path.join(d,'nba.sqlite');c=connect(p);migrate(c);c.close()
   result=audit(p,'Giannis Antetokounmpo',['2025-26'],1)
   self.assertEqual(result['status'],'FAIL')
   self.assertEqual(result['season_counts']['2025-26'],0)
if __name__=='__main__':unittest.main()
