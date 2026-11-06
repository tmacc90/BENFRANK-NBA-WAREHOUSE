import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benfrank_omni.contracts import canonical, sha, validate_prop
from benfrank_omni.ledger import apply_calibration, calibrate, connect, fit_rows, isotonic, record, settle, stratum
from benfrank_omni.model import blind, simulate
from benfrank_omni.runner import run, verify_run
from test_omni_contracts import CUTOFF, games, prop


class ExecutionTest(unittest.TestCase):
    def test_batch_executes_two_sports_and_independent_receipt_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            props = []
            for sport, market in (("NBA", "points"), ("NFL", "passing_yards")):
                path = root / (sport + ".json")
                path.write_bytes(canonical({"sport": sport, "captured_at_utc": "2025-11-30T18:00:00Z", "games": games(sport, market)}))
                p = prop(sport, market)
                p["history_sources"] = [{"provider": "normalized_json", "file": str(path), "sha256": sha(path.read_bytes())}]
                props.append(p)
            source = root / "batch.json"
            source.write_bytes(canonical({"mode": "SOFTWARE_TEST", "cutoff_utc": CUTOFF, "collect_opponent_context": False, "props": props}))
            result, code = run(source, root / "out", root / "state")
            self.assertEqual(code, 0)
            self.assertEqual(result["completed_props"], 2)
            self.assertEqual(result["verification"]["verified_statistic_draws"], 150000)
            reports = json.loads((root / "out/batch_results.json").read_text())
            self.assertTrue(all(r["blind_model"]["line_received"] is False for r in reports))
            self.assertTrue(all(r["calibration"]["applied"] is False for r in reports))
            for sport in ("nba", "nfl"):
                self.assertTrue((root / "state" / sport / "forecast_ledger.sqlite").exists())
            self.assertTrue((root / "out/report.html").exists())
            target = root / "out/props/000/traces/baseline.jsonl.gz"
            target.write_bytes(target.read_bytes() + b"tampering")
            with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
                verify_run(root / "out")
            with self.assertRaises(FileExistsError):
                run(source, root / "out", root / "state")

    def test_one_bad_prop_never_hides_successful_siblings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "batch.json"
            source.write_bytes(canonical({"mode": "SOFTWARE_TEST", "cutoff_utc": CUTOFF, "props": [{**prop(), "sport": "UNKNOWN"}, {**prop("COD", "kills"), "player_id": "cdl-player"}]}))
            summary, code = run(source, root / "out", root / "state")
            self.assertEqual(code, 2)
            self.assertEqual(summary["blocked_props"], 2)
            errors = json.loads((root / "out/batch_results.json").read_text())
            self.assertIn("UNKNOWN_SPORT", errors[0]["blocker"])
            self.assertIn("SPECIALIST_SOURCE_REQUIRED", errors[1]["blocker"])
            self.assertTrue((root / "out/execution_receipt.json").exists())

    def test_same_seed_is_reproducible_and_line_cannot_change_draws(self):
        with tempfile.TemporaryDirectory() as temp:
            p = validate_prop(prop(), CUTOFF, "SOFTWARE_TEST")
            rows = [{**g, "value": g["stats"]["points"]} for g in games()]
            a = simulate(rows, p, Path(temp) / "a")
            b = simulate(rows, {**p, "line": 12.5}, Path(temp) / "b")
            self.assertEqual(a["scenarios"]["BASELINE"]["draws_sha256"], b["scenarios"]["BASELINE"]["draws_sha256"])
            self.assertGreater(a["scenarios"]["BASELINE"]["p_over"], b["scenarios"]["BASELINE"]["p_over"])
            for rung in a["sensitivity"]:
                self.assertAlmostEqual(rung["p_over"] + rung["p_under"] + rung["p_push"], 1)

    def test_insufficient_blind_history_does_not_invent_training(self):
        rows = [{**g, "value": g["stats"]["points"]} for g in games(n=8)]
        result = blind(rows)
        self.assertEqual(result["training_n"], 3)
        self.assertEqual(result["status"], "INSUFFICIENT_CHRONOLOGICAL_TRAINING")


class CalibrationTest(unittest.TestCase):
    def test_full_grading_calibration_apply_and_replay_exclusion(self):
        import datetime as dt
        from benfrank_omni import VERSION
        with tempfile.TemporaryDirectory() as temp:
            outcomes = []
            template = None
            for i in range(200):
                start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
                cutoff = (start - dt.timedelta(hours=2)).isoformat()
                p = {**prop(), "prop_id": str(i), "event_id": str(i), "event_start_utc": start.isoformat(), "cutoff_utc": cutoff}
                f = {"prop": p, "mode": "PREGAME", "version": VERSION, "simulation": {"scenarios": {"BASELINE": {"p_over": .7 if i%2 else .3, "p_under": .3 if i%2 else .7, "p_push": 0}}}}
                with patch("benfrank_omni.ledger.now", return_value=(start-dt.timedelta(hours=1)).isoformat()):
                    record(temp, f)
                outcomes.append({"prop_id": str(i), "sport": "NBA", "event_id": str(i), "player_id": "123", "market": "points", "completed": True, "status": "SETTLED", "value": 20 if i%2 else 1, "source_url": "https://example.org/test", "source_sha256": "a"*64, "retrieved_at_utc": (start+dt.timedelta(hours=4)).isoformat()})
                template = p
            # A retrospective forecast is explicitly excluded even after grading.
            replay = {**f, "mode": "RESEARCH_REPLAY", "prop": {**template, "prop_id": "replay", "event_id": "replay"}}
            record(temp, replay)
            outcomes.append({**outcomes[-1], "prop_id": "replay", "event_id": "replay"})
            result = settle(temp, "NBA", outcomes)
            self.assertEqual(result["settled"], 201)
            models = calibrate(temp, "NBA", "points")
            self.assertEqual(models[0]["eligible_rows"], 200)
            self.assertEqual(models[0]["status"], "VALIDATED_HOLDOUT")
            future = (dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=2)).isoformat()
            applied = apply_calibration(temp, {**template, "cutoff_utc": future}, {"p_over": .7, "p_under": .3, "p_push": 0})
            self.assertTrue(applied["applied"])
            self.assertGreater(applied["p_over"], .7)
            self.assertFalse(applied["accuracy_certified"])

    def test_postgame_forecast_cannot_enter_pregame_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            p = {**prop(), "prop_id": "late", "cutoff_utc": CUTOFF}
            with self.assertRaisesRegex(ValueError, "POSTGAME"):
                record(temp, {"prop": p, "mode": "PREGAME"})

    def test_calibration_requires_forward_ledger_and_cannot_claim_success_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            reports = calibrate(temp, "NBA", "points")
            self.assertEqual(reports[0]["eligible_rows"], 0)
            self.assertEqual(reports[0]["status"], "INSUFFICIENT_GRADED_PREGAME_FORECASTS")
            self.assertFalse(reports[0]["accuracy_certified"])

    def test_holdout_results_never_change_fitted_bins_and_events_never_overlap(self):
        import datetime as dt
        rows = []
        for i in range(200):
            stamp = (dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)).isoformat()
            rows.append({"p": .7 if i%2 else .3, "y": i%2, "event_start_utc": stamp, "event_id": str(i), "prop_id": str(i)})
        result = fit_rows(rows, sport="NBA", market="points", key="test")
        self.assertEqual(result["status"], "VALIDATED_HOLDOUT")
        self.assertFalse(set(result["trained_event_ids"]) & set(result["evaluated_event_ids"]))
        changed = [{**r, "y": 1-r["y"]} if r["event_id"] in result["evaluated_event_ids"] else r for r in rows]
        rechecked = fit_rows(changed, sport="NBA", market="points", key="test")
        self.assertEqual(result["blocks"], rechecked["blocks"])
        self.assertEqual(rechecked["status"], "REJECTED_HOLDOUT")

    def test_append_only_database_and_sport_rule_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            c = connect(temp, "NBA")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "APPEND_ONLY"):
                c.execute("UPDATE identity SET sport='NFL'")
            c.close()
            a, b = prop(), prop("NFL", "passing_yards")
            self.assertNotEqual(stratum(a), stratum(b))
            a2 = copy.deepcopy(a)
            a2["rules"]["scoring_weights"] = {"points": 2}
            self.assertNotEqual(stratum(a), stratum(a2))


if __name__ == "__main__":
    unittest.main()
