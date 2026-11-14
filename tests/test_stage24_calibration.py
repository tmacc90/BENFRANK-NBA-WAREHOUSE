import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from benfrank_stage24_calibration import live_maturity, stage24_receipt


class Stage24CalibrationTests(unittest.TestCase):
    def prop(self):
        return {
            "player": "Example Player",
            "market": "points",
            "line": 19.5,
            "platform": "PrizePicks",
        }

    def baseline(self, path):
        path.write_text(json.dumps({
            "model": "EMPIRICAL_PRIOR_20_GAME_BASELINE",
            "status": "EVALUATED_BASELINE_ONLY",
            "stratum_metrics": [{
                "platform": "prizepicks",
                "market": "points",
                "line_band_low": 15,
                "line_band_width": 5,
                "status": "EVALUATED_BASELINE_ONLY",
                "train_n": 100,
                "train_games": 60,
                "holdout_n": 40,
                "holdout_games": 30,
                "raw_holdout": {"n": 40, "brier": 0.26},
                "calibrated_holdout": {"n": 40, "brier": 0.24},
                "brier_delta": {"status": "DESCRIPTIVE_GAME_CLUSTER_BOOTSTRAP"},
            }],
        }))

    def test_historical_baseline_never_calibrates_current_simulator(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.json"
            self.baseline(baseline)
            receipt = stage24_receipt(
                self.prop(), 0.71,
                {
                    "status": "LIVE_COHORT_NOT_STARTED",
                    "predictions_frozen": 0,
                    "settlements": 0,
                    "unique_primary_forecasts": 0,
                    "strata": [],
                    "maturity_threshold": {
                        "settled_nonpush_per_stratum": 50,
                        "unique_games_per_stratum": 30,
                    },
                },
                baseline,
            )
            self.assertEqual(receipt["execution"], "EXECUTED")
            self.assertEqual(receipt["quality"], "LIMITED")
            self.assertFalse(receipt["calibration_applied"])
            self.assertIsNone(receipt["p_over_calibrated"])
            self.assertFalse(receipt["24A_historical_calibration"]["applicable_to_current_simulator"])
            self.assertEqual(receipt["raw_p_over"], 0.71)
            self.assertEqual(receipt["decision_effect"], "NONE")
            self.assertEqual(receipt["direction"], "NEUTRAL")
            self.assertEqual(receipt["source_grade"], "C")
            self.assertEqual(receipt["engine"], "BENFRANK_STAGE24_CALIBRATION_1")
            self.assertEqual(len(receipt["receipt_id"]), 64)
            self.assertIn("CURRENT_SIMULATOR_VALIDATED_CALIBRATION_MODEL", receipt["missing"])

    def test_missing_live_ledger_is_explicit_limited_not_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = live_maturity(Path(tmp) / "missing.sqlite")
            self.assertEqual(result["status"], "LIVE_COHORT_NOT_STARTED")
            self.assertEqual(result["quality"], "LIMITED")
            self.assertEqual(result["predictions_frozen"], 0)
            self.assertEqual(result["settlements"], 0)

    def test_live_maturity_is_read_only_and_requires_both_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite"
            conn = sqlite3.connect(path)
            conn.executescript("""
            CREATE TABLE early_predictions(
              id TEXT PRIMARY KEY,issued_at TEXT NOT NULL,tipoff_utc TEXT NOT NULL,
              receipt_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
            CREATE TABLE early_settlements(
              id TEXT PRIMARY KEY,prediction_id TEXT NOT NULL,observed_at TEXT NOT NULL,
              source_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL);
            """)
            for i in range(50):
                rid = f"p{i}"
                game_id = f"g{i % 30}"
                payload = {
                    "prop": {
                        "game_id": game_id,
                        "player": f"Player {i}",
                        "market": "points",
                        "line": 19.5,
                        "platform": "PrizePicks",
                    },
                    "main_simulation": {"p_over_raw": 0.60},
                }
                settlement = {
                    "prediction_id": rid,
                    "outcome": "OVER" if i % 2 else "UNDER",
                    "correct": bool(i % 2),
                }
                conn.execute("INSERT INTO early_predictions VALUES(?,?,?,?,?)",
                    (rid, "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z", "a"*64,
                     json.dumps(payload, sort_keys=True)))
                conn.execute("INSERT INTO early_settlements VALUES(?,?,?,?,?)",
                    (f"s{i}", rid, "2026-11-03T00:00:00Z", "b"*64,
                     json.dumps(settlement, sort_keys=True)))
            conn.commit()
            conn.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = live_maturity(path)
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(result["status"], "LIVE_COHORT_MATURE_FOR_RESEARCH")
            self.assertEqual(result["predictions_frozen"], 50)
            self.assertEqual(result["settlements"], 50)
            self.assertEqual(result["primary_settlements"], 50)
            self.assertEqual(result["revision_settlements_excluded"], 0)
            self.assertEqual(result["pre_tipoff_revisions_excluded"], 0)
            self.assertEqual(len(result["strata"]), 1)
            self.assertEqual(result["strata"][0]["settled_nonpush_n"], 50)
            self.assertEqual(result["strata"][0]["unique_games"], 30)
            self.assertTrue(result["strata"][0]["mature_for_calibration_research"])


if __name__ == "__main__":
    unittest.main()
