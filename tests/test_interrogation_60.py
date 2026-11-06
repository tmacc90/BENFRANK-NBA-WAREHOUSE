import json
import tempfile
import unittest
from pathlib import Path
from benfrank_interrogation_60 import evaluate, QUESTIONS
from benfrank_six_prop_batch import run

class InterrogationTests(unittest.TestCase):
    def test_sixty_questions(self):
        self.assertEqual(len(QUESTIONS), 60)
        self.assertEqual(len(set(k for k, _ in QUESTIONS)), 60)

    def test_missing_results_never_certified(self):
        report = evaluate({}, sport="NBA", player="Luka Doncic",
                          market="3PM", line=4.5, cutoff_utc="")
        self.assertFalse(report["certified"])
        self.assertEqual(report["verified_count"], 0)
        self.assertTrue(all(q["status"] == "pending" for q in report["questions"]))

    def test_claim_without_receipt_is_not_verified(self):
        report = evaluate({"simulation": {"status": "verified",
                          "answer": "25K trials"}}, sport="NBA",
                          player="Luka Doncic", market="3PM",
                          line=4.5, cutoff_utc="")
        self.assertEqual(report["questions"][51]["status"], "pending")

    def test_six_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = run({"props": []}, folder)
            self.assertEqual(len(summary), 6)
            self.assertFalse(any(x["certified"] for x in summary))
            self.assertEqual(len(list(Path(folder).glob("prop_*.json"))), 6)
            self.assertTrue((Path(folder) / "batch_summary.json").exists())

if __name__ == "__main__":
    unittest.main()
