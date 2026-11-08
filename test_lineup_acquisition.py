import unittest
from benfrank_lineup_acquisition import sec, elapsed, summarize

class TestLineupAcquisition(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(sec("PT12M00.00S"),720)
        self.assertEqual(elapsed(1,"PT11M00.00S"),60)
        self.assertEqual(elapsed(4,"PT0M00.00S"),2880)
    def test_summary(self):
        st=[{"period":4,"start":2520,"end":2580,"lineups":{"1":[1,2,3,4,5],"2":[6,7,8,9,10]}}]
        players=[{"team_id":1,"player_id":i} for i in range(1,6)]+[{"team_id":2,"player_id":i} for i in range(6,11)]
        x=summarize(st,players)
        self.assertEqual(x["player_minutes"][1],1)
        self.assertEqual(x["closing_share"]["1"],1)
if __name__=="__main__": unittest.main()
