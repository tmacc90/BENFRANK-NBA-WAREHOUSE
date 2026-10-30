import pathlib
import unittest
from benfrank_v48_readiness import generate

ROOT=pathlib.Path(__file__).resolve().parents[1]
class CertificationReadinessTests(unittest.TestCase):
    def test_frozen_research_cannot_be_reclassified(self):
        r=generate(ROOT)
        self.assertEqual(r["status"],"NOT_CERTIFIED")
        self.assertEqual(r["ticket_authority"],"NO_TICKET")
        self.assertEqual(r["measured_v47"]["new_test_games"],32)
        self.assertEqual(r["measured_v47"]["total_trials"],2575000)
        self.assertEqual(r["measured_v47"]["calibration_parameter_games"],42)
        self.assertEqual(r["measured_v47"]["calibration_conformal_games"],28)
        self.assertGreater(r["measured_v47"]["brier_delta_bootstrap_95pct"][1],0)
    def test_all_nine_gates_have_explicit_blockers(self):
        r=generate(ROOT)
        self.assertEqual(r["required"],9)
        self.assertTrue(all(x["status"]=="BLOCKED" for x in r["gates"].values()))
        self.assertTrue(all(x["reasons"] for x in r["gates"].values()))
    def test_original_data_not_silently_reclassified_production(self):
        r=generate(ROOT)
        self.assertFalse(r["gate_evidence"]["historical_coverage"]["verified"])
        self.assertTrue(r["protected_archive_not_modified"])
        self.assertFalse(r["measured_v47"]["independent_test_certified"])
if __name__=="__main__":
    unittest.main()
