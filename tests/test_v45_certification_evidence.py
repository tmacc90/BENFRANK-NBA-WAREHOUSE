"""Offline synthetic contract tests. No fixture is real historical evidence."""
import copy
import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from benfrank_v44_calibration import fit_isotonic, calibrate
from benfrank_v44_snapshot_ledger import ingest, export
from benfrank_v45_evidence import archive_minutes, digest, readonly, rebuild, shots, SHOT_FIELDS
from benfrank_v45_odds import normalize, capture_matches
from benfrank_v45_readiness import inspect_ledger
from benfrank_v45_backtest import evaluate_predictions, replay, validate_context, outcome_key
from benfrank_v45_pbp import lineup_players, seconds
from test_v44_twon import fixture


def provider_document():
    return {"timestamp": "2026-10-29T12:00:00Z", "data": {
        "id": "fixturegame", "sport_key": "basketball_nba",
        "commence_time": "2026-10-29T23:00:00Z",
        "home_team": "Boston Celtics", "away_team": "New York Knicks",
        "bookmakers": [{"key": "FixturePlatform", "markets": [{"key": "player_points",
            "last_update": "2026-10-29T11:59:00Z", "outcomes": [
                {"name": "Over", "description": "Fixture Player", "point": 20.5},
                {"name": "Under", "description": "Fixture Player", "point": 20.5}]}]}]}}


class SnapshotReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "snapshots.sqlite"
        (self.root / "capture.bin").write_bytes(b"EXPLICIT SYNTHETIC CAPTURE FIXTURE")
        self.row = {"snapshot_id": "fixture-1", "platform": "FixturePlatform", "player": "Fixture Player",
            "market": "points", "line": 20.5, "opponent": "NYK", "game_id": "fixturegame",
            "game_date": "2026-10-29", "captured_at": "2026-10-29T12:00:00Z",
            "tipoff_utc": "2026-10-29T23:00:00Z", "source_type": "SCREENSHOT_CAPTURE",
            "source_file": "capture.bin", "source_sha256": digest(self.root / "capture.bin")}

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, rows):
        with sqlite3.connect(self.ledger) as conn:
            ingest(conn, rows)

    def test_missing_ledger_never_created(self):
        self.assertEqual(inspect_ledger(self.ledger)["status"], "BLOCKED_NO_SNAPSHOT_LEDGER")
        self.assertFalse(self.ledger.exists())

    def test_separate_ledger_read_only_export_and_audit(self):
        self.save([self.row])
        before = digest(self.ledger)
        conn = readonly(self.ledger)
        try:
            self.assertEqual(export(conn)[0]["line"], 20.5)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM exact_line_snapshots")
        finally:
            conn.close()
        r = inspect_ledger(self.ledger, self.root)
        self.assertEqual(r["selected_outcomes"], 1)
        self.assertTrue(r["ledger_unchanged"])
        self.assertEqual(digest(self.ledger), before)
        self.assertEqual(r["certification"], "NOT_CERTIFIED")

    def test_moved_lines_are_not_independent_outcomes(self):
        self.save([self.row, {**self.row, "snapshot_id": "fixture-2", "line": 21.5,
                             "captured_at": "2026-10-29T13:00:00Z"}])
        r = inspect_ledger(self.ledger, self.root)
        self.assertEqual(r["source_linked_snapshots"], 2)
        self.assertEqual(r["selected_outcomes"], 1)
        self.assertEqual(r["eligible_snapshots"][0]["line"], 20.5)

    def test_metadata_without_original_file_is_not_evidence(self):
        self.save([{k: v for k, v in self.row.items() if k != "source_file"}])
        r = inspect_ledger(self.ledger, self.root)
        self.assertEqual(r["eligible_metadata_snapshots"], 1)
        self.assertEqual(r["source_linked_snapshots"], 0)

    def test_modified_original_capture_is_rejected(self):
        self.save([self.row])
        (self.root / "capture.bin").write_bytes(b"changed")
        self.assertEqual(inspect_ledger(self.ledger, self.root)["source_linked_snapshots"], 0)

    def test_ledger_column_and_payload_tampering_rejected(self):
        self.save([self.row])
        with sqlite3.connect(self.ledger) as conn:
            conn.execute("UPDATE exact_line_snapshots SET line=99")
        r = inspect_ledger(self.ledger, self.root)
        self.assertIn("LEDGER_COLUMN_PAYLOAD_CONFLICT", r["rejections"][0]["reason"])

    def test_capture_path_escape_rejected(self):
        self.save([{**self.row, "source_file": "../capture.bin"}])
        r = inspect_ledger(self.ledger, self.root)
        self.assertEqual(r["source_linked_snapshots"], 0)

    def test_no_lines_no_simulation_trials(self):
        r = replay(self.root / "missing-warehouse.sqlite", None, None, None, self.root / "replay")
        self.assertEqual(r["simulation_trials_executed"], 0)
        self.assertTrue(r["status"].startswith("BLOCKED"))


class OddsImportTests(unittest.TestCase):
    def test_provider_sides_deduplicated_and_no_team_guess(self):
        r = normalize(provider_document(), "a"*64, "source.json")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["line"], 20.5)
        self.assertTrue(r[0]["opponent"].startswith("UNRESOLVED_"))

    def test_provider_after_tipoff_never_imported(self):
        doc = provider_document()
        doc["timestamp"] = doc["data"]["commence_time"]
        with self.assertRaises(ValueError):
            normalize(doc, "a"*64, "source.json")

    def test_future_market_update_never_imported(self):
        doc = provider_document()
        doc["data"]["bookmakers"][0]["markets"][0]["last_update"] = "2026-10-29T20:00:00Z"
        with self.assertRaises(ValueError):
            normalize(doc, "a"*64, "source.json")

    def test_same_hash_cannot_attest_different_offered_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw.json"
            path.write_text(json.dumps(provider_document()))
            row = normalize(provider_document(), digest(path), "raw.json")[0]
            self.assertTrue(capture_matches(row, path))
            self.assertFalse(capture_matches({**row, "line": 99}, path))


class EvidenceMathTests(unittest.TestCase):
    def test_duplicate_or_incomplete_lineups_are_rejected(self):
        for value in ("1-2-3-4", "1-2-3-4-4", "0-1-2-3-4", "1-2-3-4-5-6"):
            with self.assertRaises(ValueError):
                lineup_players(value)
        self.assertEqual(len(lineup_players("1-2-3-4-5")), 5)

    def test_malformed_possession_clocks_are_rejected(self):
        for value in ("12:99", "unknown", "-1:00"):
            with self.assertRaises(ValueError):
                seconds(value)
        self.assertEqual(seconds("12:00"), 720)

    def test_missing_minutes_not_imputed_and_rounding_carry_explicit(self):
        self.assertEqual(archive_minutes("21:60"), 22)
        for x in ("", "21:61", "nan", "-1"):
            with self.assertRaises(ValueError):
                archive_minutes(x)

    def test_invalid_shooting_ledger_rejected(self):
        row = dict(field_goals_made=5, field_goals_attempted=10, three_pointers_made=2,
                   three_pointers_attempted=5, free_throws_made=3, free_throws_attempted=4, points=15)
        self.assertEqual(shots(row, SHOT_FIELDS)["fg2m"], 3)
        with self.assertRaises(ValueError):
            shots({**row, "points": 16}, SHOT_FIELDS)

    def test_failed_input_audit_preserves_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            archive.mkdir()
            with sqlite3.connect(archive / "nba_warehouse.sqlite") as conn:
                conn.execute("CREATE TABLE incomplete (value)")
            before = digest(archive / "nba_warehouse.sqlite")
            r = rebuild(archive, Path(tmp) / "output")
            self.assertEqual(r["status"], "FAILED_INTEGRITY_OR_SOURCE_GATE")
            self.assertEqual(before, digest(archive / "nba_warehouse.sqlite"))

    def test_isotonic_ties_and_varying_bin_counts_remain_monotone(self):
        rows = [(.2, 1), (.2, 0)] + [(.3, 0)]*25 + [(.4, 1)]*30
        model = fit_isotonic(rows)
        rates = [calibrate(p, model) for p in (.1, .2, .3, .4, .9)]
        self.assertEqual(rates, sorted(rates))
        self.assertEqual(sum(b["n"] for b in model), len(rows))


class SimulatorBacktestTests(unittest.TestCase):
    def test_provider_game_ids_and_platform_case_do_not_duplicate_outcomes(self):
        row = {"platform": "PrizePicks", "player": "Fixture Player", "market": "points",
               "game_id": "vendor-id", "line": 20.5}
        other = {**row, "platform": "prizepicks", "game_id": "different-provider-id", "line": 21.5}
        self.assertEqual(outcome_key(row, "0022400001"), outcome_key(other, "0022400001"))

    def predictions(self):
        date = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        return [{"platform": "FixturePlatform", "market": "points", "scoring_contract": "",
                 "line": 20.5, "game_id": str(i), "tipoff_utc": (date+dt.timedelta(days=i)).isoformat(),
                 "p_over_raw": .8, "p_over_baseline": .2, "over_result": int(i % 3 != 0),
                 "q05": 10, "q95": 40, "actual": 25 if i % 3 else 15, "mean": 22,
                 "blind_prediction": 21} for i in range(80)]

    def test_actual_simulator_probabilities_are_scored_separately(self):
        r = evaluate_predictions(self.predictions())
        self.assertEqual(r["status"], "EVALUATED_UNCERTIFIED")
        a = r["strata"][0]
        self.assertNotEqual(a["raw_holdout"]["brier"], a["historical_baseline_holdout"]["brier"])
        self.assertEqual(r["certification"], "NOT_CERTIFIED")
        self.assertFalse(r["promotion_policy_applied"])
        self.assertEqual(a["blind_challenger"]["evaluated"], a["holdout_n"])

    def test_market_and_platform_bins_are_not_pooled(self):
        rows = self.predictions()
        for i in range(0, 80, 2):
            rows[i]["platform"] = "OtherFixturePlatform"
        r = evaluate_predictions(rows)
        self.assertEqual(len(r["strata"]), 2)
        self.assertTrue(all(s["status"] == "INSUFFICIENT_STRATUM_SAMPLE" for s in r["strata"]))

    def test_same_game_cannot_have_conflicting_tipoffs(self):
        rows = self.predictions()
        rows[1]["game_id"] = rows[0]["game_id"]
        with self.assertRaises(ValueError):
            evaluate_predictions(rows)

    def test_realized_rotations_are_rejected_as_forecasts(self):
        c = fixture()
        snapshot = {"player": "BOS Player 0", "market": "points", "line": 20.5,
                    "opponent": "NYK", "platform": "FixturePlatform", "snapshot_id": "x",
                    "game_date": c["game_date"], "captured_at": "2026-10-29T13:00:00Z",
                    "tipoff_utc": c["tipoff_utc"]}
        c["game_id"] = "fixturegame"
        with self.assertRaisesRegex(ValueError, "PREGAME_FORECAST_REQUIRED"):
            validate_context(c, snapshot, "fixturegame", Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
