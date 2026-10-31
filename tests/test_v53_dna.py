import unittest
from benfrank_v53_dna import coverage, conditional_dna, matchup_similarity, FAMILIES
class TestV53DNA(unittest.TestCase):
 def setUp(self):
  self.rows=[dict(date="2026-10-%02d"%i,game_id=str(i),played=True,season="2026-27",rebounds=i,minutes=20+i,pace=90+i,source="TEST_FIXTURE") for i in range(1,11)]
 def test_exact_line(self):
  x=coverage(self.rows,"rebounds",5.5,"2026-10-11")
  self.assertEqual((x["windows"]["L5"]["over"],x["windows"]["L5"]["under"]),(5,0))
  self.assertEqual((x["windows"]["L10"]["over"],x["windows"]["L10"]["under"]),(5,5))
 def test_no_future_leak(self):
  x=coverage(self.rows,"rebounds",5.5,"2026-10-06")
  self.assertEqual(x["windows"]["available_career"]["n"],5)
 def test_100_tests(self):
  self.assertEqual(sum(map(len,FAMILIES.values())),100)
  self.assertEqual(len(conditional_dna(self.rows,"rebounds",5.5,"2026-10-11",{"minutes":29})),100)
 def test_similarity(self):
  x=matchup_similarity(self.rows,"rebounds",5.5,"2026-10-11",{"minutes":29,"pace":99})
  self.assertEqual(x["analogues"][0]["game_id"],"9")
if __name__=="__main__":unittest.main()
