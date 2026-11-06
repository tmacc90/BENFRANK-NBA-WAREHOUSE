import unittest
from scripts.omni_evidence import merge_l52,independent_blind,windows,opponent_evidence
class TestOmni(unittest.TestCase):
    def test_dedup(self):
        a=[{"event_id":str(i),"date":f"2026-10-{i:02d}","points":i,"rebounds":2,"assists":3} for i in range(1,29)]
        self.assertEqual(len(merge_l52([a,a])),28)
    def test_blind(self):
        g=[{"points":i,"rebounds":2,"assists":3} for i in range(30)]
        self.assertEqual(independent_blind(g,"points")["status"],"RESEARCH_BASELINE")
    def test_missing_defense(self):
        self.assertEqual(opponent_evidence({})["status"],"MISSING_VERIFIED_OPPONENT_DATA")
    def test_windows(self):
        g=[{"points":10,"rebounds":2,"assists":3}]*6
        self.assertEqual(windows(g,"points",9)["L5"]["over"],5)
if __name__=="__main__":unittest.main()
