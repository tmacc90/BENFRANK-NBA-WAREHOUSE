import unittest
from benfrank_v44_audit import STAGES, build_receipt

PROP = {"player":"Example Player","market":"points","line":19.5,"opponent":"BOS","game_date":"2026-10-29"}

class V44AuditTests(unittest.TestCase):
    def test_66_stages(self):
        self.assertEqual(len(STAGES), 66)
        self.assertEqual(len({s["id"] for s in STAGES}), 66)
    def test_fail_closed(self):
        r = build_receipt(PROP)
        self.assertEqual(r["counts"]["BLOCKED"], 66)
        self.assertEqual(r["ticket_authority"], "NO_TICKET")
        self.assertEqual(r["direction"], "UNRESOLVED")
    def test_no_unsupported_pass(self):
        with self.assertRaises(ValueError):
            build_receipt(PROP, {"exact_line":{"status":"PASS"}})
    def test_evidenced_pass_does_not_certify(self):
        r = build_receipt(PROP, {"exact_line":{"status":"PASS","source":"board snapshot","asof":"2026-10-29T12:00:00Z"}})
        self.assertEqual(r["counts"]["PASS"], 1)
        self.assertEqual(r["ticket_authority"], "NO_TICKET")
    def test_unknown_stage_rejected(self):
        with self.assertRaises(ValueError):
            build_receipt(PROP, {"invented":{"status":"PASS"}})

if __name__ == "__main__":
    unittest.main()
