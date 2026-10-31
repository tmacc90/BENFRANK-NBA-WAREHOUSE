import unittest
from benfrank_v53_core import report
class CoreTest(unittest.TestCase):
 def test_report_is_research_only(self):
  rows=[{"date":"2026-10-01","game_id":"g1","played":True,"season":"2026-27","rebounds":8,"minutes":32,"pace":99,"source":"TEST"}]
  x=report({"prop":{"player":"Example Player","opponent":"Example Opponent","market":"rebounds","line":7.5,"cutoff":"2026-10-02"},"historical_games":rows,"upcoming_features":{"minutes":32,"pace":99}})
  self.assertEqual(x["exact_line_coverage"]["windows"]["L5"]["over"],1)
  self.assertEqual(x["decision"]["ticket"],"NO_TICKET")
  self.assertEqual(x["peer_role_analogues"]["status"],"NOT_CONNECTED")
if __name__=="__main__":unittest.main()
