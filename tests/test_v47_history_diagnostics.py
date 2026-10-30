import json
import tempfile
import unittest
from pathlib import Path
from benfrank_v47_history_diagnostics import audit,classify

class HistoryDiagnosticTests(unittest.TestCase):
    def test_classifies_real_failure_codes(self):
        self.assertEqual(classify({"code":"VERIFICATION_REJECTED",
                         "detail":"ESPN_IDENTITY_MATCH_COUNT_0"}),"ESPN_IDENTITY_MISSING")
        self.assertEqual(classify({"code":"CROSS_SOURCE_CONFLICT"}),"CROSS_SOURCE_CONFLICT")
    def test_no_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(audit(folder)["status"],"MISSING_IMPORT_RECEIPT")
    def test_preserves_discrepancy_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            (p/"import_receipt.json").write_text(json.dumps({
                "status":"PARTIAL_OR_FAIL",
                "seasons":[{"season":"2025-26","failure_count":2,
                            "crosschecked_player_games":26497}]}))
            (p/"failures_2026.json").write_text(json.dumps([
                {"source":"nba_stats_mirror","code":"VERIFICATION_REJECTED",
                 "detail":"ESPN_IDENTITY_MATCH_COUNT_0"},
                {"source":"espn","code":"NOT_CROSSCHECKED"}]))
            report=audit(p)
            self.assertEqual(report["status"],"INCOMPLETE_RECONCILIATION")
            self.assertEqual(report["seasons"][0]["actual_failures"],2)
            self.assertFalse(report["historical_certification"])
    def test_missing_detail_never_certifies(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            (p/"import_receipt.json").write_text(json.dumps({
                "seasons":[{"season":"2024-25","failure_count":0}]}))
            self.assertEqual(audit(p)["status"],"INVALID_OR_MISSING_FAILURE_EVIDENCE")

if __name__=="__main__":
    unittest.main()
