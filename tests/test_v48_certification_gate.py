import unittest
from benfrank_v48_certification_gate import evaluate,check_receipt
class CertificationGateTests(unittest.TestCase):
    def test_empty_fails_all_nine(self):
        r=evaluate({})
        self.assertEqual(r["passed"],0)
        self.assertEqual(r["required"],9)
        self.assertEqual(r["ticket_authority"],"NO_TICKET")
    def test_unit_test_simulator_cannot_certify(self):
        item={"execution_receipt":"x","real_game_trials":25000,
              "engine_sha256":"a"*64,"simulation_granularity":"possession_with_rotations",
              "verified":True,"evidence_kind":"synthetic"}
        self.assertIn("NON_PRODUCTION_EVIDENCE",check_receipt("possession_simulator",item))
    def test_minute_proxy_cannot_certify(self):
        item={"execution_receipt":"x","real_game_trials":25000,
              "engine_sha256":"a"*64,"simulation_granularity":"minute_bootstrap","verified":True}
        self.assertIn("NOT_POSSESSION_ROTATION_SIMULATOR",check_receipt("possession_simulator",item))
    def test_uncalibrated_model_fails(self):
        item={"evaluation_receipt":"x","n_out_of_sample":600,
              "baseline_brier":.24,"model_brier":.25,"bootstrap_ci_upper":.01,
              "chronological_holdout":True,"verified":True}
        self.assertIn("NO_BASELINE_BRIER_IMPROVEMENT",check_receipt("walk_forward_calibration",item))
    def test_stages_must_be_executed(self):
        item={"execution_receipt":"x","executed_stage_ids":["1"],
              "required_stage_ids":["1","2"],"verified":True}
        self.assertIn("GOVERNING_STAGES_NOT_ALL_EXECUTED",check_receipt("governing_stage_audit",item))
    def test_no_ticket_even_when_all_receipts_exist(self):
        from benfrank_v48_certification_gate import REQUIRED
        r=evaluate({key:{"verified":True} for key in REQUIRED})
        self.assertEqual(r["ticket_authority"],"NO_TICKET")
        self.assertEqual(r["status"],"NOT_CERTIFIED")
if __name__=="__main__":
    unittest.main()
