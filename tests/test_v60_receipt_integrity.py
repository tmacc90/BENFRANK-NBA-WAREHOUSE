"""Regression tests for v6 receipt proof gates."""
import unittest
from pathlib import Path

class ReceiptIntegrityTests(unittest.TestCase):
    def test_runner_requires_simulation_provenance(self):
        source = Path(__file__).resolve().parents[1].joinpath("benfrank_v60_run.py").read_text()
        self.assertIn('sim_proof.get("trials_sha256")', source)
        self.assertIn('sim_proof.get("input_sha256")', source)
        self.assertIn('sim_proof.get("seed")', source)
        self.assertIn('"sequential_25000": bool(sim_verified)', source)

    def test_runner_requires_blind_independence(self):
        source = Path(__file__).resolve().parents[1].joinpath("benfrank_v60_run.py").read_text()
        self.assertIn('blind_proof.get("feature_manifest_sha256")', source)
        self.assertIn('blind_proof.get("line_excluded") is True', source)
        self.assertIn('blind_proof.get("primary_prediction_excluded") is True', source)
        self.assertIn('"blind_model": bool(blind_verified)', source)

if __name__ == "__main__":
    unittest.main()
