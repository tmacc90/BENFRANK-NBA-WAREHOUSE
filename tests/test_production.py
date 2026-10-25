import unittest,tempfile,csv,os
from engine import connect
from production import init,blind_model,sequential_proxy,report,import_evidence,evidence,backtest
class ProductionTests(unittest.TestCase):
 def setUp(self):
  self.c=connect(':memory:');init(self.c)
  for i in range(35):
   day=f'2026-09-{i+1:02d}' if i<30 else f'2026-10-{i-29:02d}'
   self.c.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('Sample',day,'2026-27','MIA','CHA',1,1,30,20+i%8,8+i%3,5,1,1,2,2))
  self.c.commit()
 def test_blind_line_independent(self):
  a=report(self.c,'Sample','points',10,'CHA','2026-10-06',100,cutoff='2026-10-06T12:00:00+00:00')
  b=report(self.c,'Sample','points',35,'CHA','2026-10-06',100,cutoff='2026-10-06T12:00:00+00:00')
  self.assertEqual(a['blind_statistical_model']['projection'],b['blind_statistical_model']['projection'])
  self.assertEqual(a['baseline_projection'],b['baseline_projection'])
 def test_trials(self):
  r=report(self.c,'Sample','points',20,'CHA','2026-10-06',250)
  self.assertEqual(r['sequential_minute_proxy']['trials'],250)
  self.assertEqual(r['ticket_authority'],'NO_TICKET')
 def test_evidence_cutoff(self):
  with tempfile.NamedTemporaryFile(mode='w',suffix='.csv',delete=False) as f:
   f.write('player,game_date,kind,metric,value,source,observed_at\nSample,2026-10-06,injury,status,available,official,2026-10-06T10:00:00+00:00\nSample,2026-10-06,injury,status,out,official,2026-10-06T20:00:00+00:00\n');path=f.name
  try:import_evidence(self.c,path)
  finally:os.unlink(path)
  v=evidence(self.c,'Sample','2026-10-06','2026-10-06T12:00:00+00:00')
  self.assertEqual(len(v),1);self.assertEqual(v[0]['value'],'available')
 def test_backtest(self):
  r=backtest(self.c,'Sample','points');self.assertGreater(r['n'],0)
if __name__=='__main__':unittest.main()
