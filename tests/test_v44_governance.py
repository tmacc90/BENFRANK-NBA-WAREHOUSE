import unittest
from benfrank_v44_governance import STAGES, governing_receipt

PROP={"player":"Sample Player","market":"points","line":20.5,"opponent":"BOS","game_date":"2026-10-29"}

class GoverningTests(unittest.TestCase):
    def test_exact_66_governing_stages(self):
        self.assertEqual(len(STAGES),66)
        self.assertIn("Digital Twon",STAGES[52])
        self.assertIn("Blind AI",STAGES[54])
    def test_fail_closed(self):
        r=governing_receipt(PROP, [], "UNRESOLVED", "NO_TICKET")
        self.assertEqual(len(r["stages"]),66)
        self.assertEqual(r["stages"][52]["status"],"BLOCKED")
        self.assertEqual(r["stages"][54]["status"],"BLOCKED")
        self.assertEqual(r["ticket_authority"],"NO_TICKET")
    def test_direction_does_not_certify(self):
        r=governing_receipt(PROP, [], "MORE", "NO_TICKET")
        self.assertEqual(r["stages"][60]["status"],"PASS")
        self.assertEqual(r["stages"][52]["status"],"BLOCKED")
        self.assertEqual(r["certification"],"NOT_CERTIFIED")

if __name__=='__main__':
    unittest.main()
