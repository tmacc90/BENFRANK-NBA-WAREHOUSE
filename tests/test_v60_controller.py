import unittest
from benfrank_v60_controller import execute, STAGES

class ControllerTests(unittest.TestCase):
    def test_missing_executors_fail_closed(self):
        r = execute("sample","2026-10-31T20:00:00Z",{})
        self.assertEqual(r["status"],"INCOMPLETE")
        self.assertFalse(r["certified"])
        self.assertIsNone(r["side"])
        self.assertEqual(len(r["receipts"]),len(STAGES))

    def test_no_evidence_cannot_pass(self):
        r = execute("sample","2026-10-31T20:00:00Z",{
            s: lambda context: {"verified":True} for s in STAGES
        })
        self.assertEqual(r["status"],"INCOMPLETE")

    def test_post_cutoff_source_rejected(self):
        r = execute("sample","2026-10-31T20:00:00Z",{
            "validate_prop":lambda context: {
                "verified":True,"evidence":{"ok":True},
                "source_asof_utc":"2026-11-01T00:00:00Z"}
        })
        self.assertEqual(r["receipts"][0]["status"],"BLOCKED")

    def test_all_evidence_is_not_accuracy_certification(self):
        fns = {s:(lambda context: {"verified":True,"evidence":{"ok":True}}) for s in STAGES}
        fns["prediction"] = lambda context: {"verified":True,"evidence":{"side":"UNDER"}}
        r = execute("sample","2026-10-31T20:00:00Z",fns)
        self.assertEqual(r["status"],"FULLY_EXECUTED")
        self.assertFalse(r["certified"])
        self.assertEqual(r["side"],"UNDER")

if __name__ == "__main__":
    unittest.main()
