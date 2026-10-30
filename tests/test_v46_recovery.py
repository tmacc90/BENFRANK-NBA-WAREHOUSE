"""Synthetic offline contracts; fixtures are never counted as NBA evidence."""
import copy
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from engine import connect, FIELDS
from benfrank_v44_calibration import scores
from benfrank_v44_snapshot_ledger import ingest
from benfrank_v45_evidence import digest, write_json
from benfrank_v45_readiness import inspect_ledger
from benfrank_v46_public_lines import normalize, source_url, capture_matches, SOURCE_TIER, REPOSITORY, SOURCE_PATH
from benfrank_v46_saved_history import audit_saved_history
from benfrank_v46_baseline import evaluate_rows
from benfrank_v46_reconstructed_replay import allocate_minutes, build_context
from benfrank_v46_official_injuries import report_url, report_times, validate_header, collection_status


class OfficialInjuryTimestampTests(unittest.TestCase):
    def test_original_printed_time_matches_url_and_precedes_line(self):
        self.assertEqual(validate_header('Injury Report: 02/01/26 06:00 AM',
            '2026-02-01T11:00:00Z','2026-02-01T12:00:00Z'), '2026-02-01T11:00:00+00:00')

    def test_newer_or_wrong_report_never_replaces_pregame_evidence(self):
        with self.assertRaisesRegex(ValueError, 'DIFFERS_FROM_URL'):
            validate_header('Injury Report: 02/01/26 07:00 AM','2026-02-01T11:00:00Z','2026-02-01T13:00:00Z')
        with self.assertRaisesRegex(ValueError, 'NOT_AVAILABLE'):
            validate_header('Injury Report: 02/01/26 06:00 AM','2026-02-01T11:00:00Z','2026-02-01T10:00:00Z')

    def test_eastern_daylight_time_and_fixed_official_host(self):
        times = report_times('2026-03-08T12:10:00Z')
        self.assertEqual(report_url(times[0]),
            'https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-08_07_45AM.pdf')

    def test_empty_or_partial_archive_cannot_claim_complete_capture(self):
        self.assertEqual(collection_status(10, 0), 'BLOCKED_NO_VERIFIED_OFFICIAL_REPORTS')
        self.assertEqual(collection_status(10, 9), 'PARTIAL_OFFICIAL_PREGAME_DOCUMENTS')
        self.assertEqual(collection_status(10, 10), 'PRESERVED_OFFICIAL_PREGAME_DOCUMENTS')


class PublicArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.doc = {"sport": "NBA", "source": "PrizePicks API", "scrapedAt": "2026-02-01T12:00:00Z",
            "props": [{"player": "Fixture Player", "sport": "NBA", "stat": "Points", "line": 25.5,
                "oddsType": "standard", "teamCode": "BOS", "opponentCode": "NYK", "gameId": "fixture",
                "startTimeIso": "2026-02-01T23:00:00Z"}]}
        self.commit = "a" * 40
        self.raw = self.root / "capture.json"
        write_json(self.raw, self.doc)
        self.receipt = {"repository": REPOSITORY, "path": SOURCE_PATH, "commit_sha": self.commit,
                        "committed_at": "2026-02-01T12:00:05Z", "raw_sha256": digest(self.raw),
                        "source_url": source_url(self.commit)}
        write_json(self.root / "receipt.json", self.receipt)
        self.row = self.make_rows()[0]
        self.row.update(source_snapshot_id=self.row["snapshot_id"], snapshot_id=self.row["snapshot_id"] + "-nba",
                        game_id="0022500001")

    def make_rows(self, doc=None, receipt=None):
        return normalize(doc or self.doc, receipt or self.receipt, "capture.json", "receipt.json",
                         digest(self.root / "receipt.json"))[0]

    def tearDown(self):
        self.tmp.cleanup()

    def test_frozen_capture_preserves_secondary_authority(self):
        self.assertEqual(self.row["captured_at"], "2026-02-01T12:00:05+00:00")
        self.assertEqual(self.row["source_tier"], SOURCE_TIER)
        self.assertFalse(self.row["platform_authenticity_independently_attested"])
        self.assertTrue(capture_matches(self.row, self.raw, self.root))

    def test_commit_after_tipoff_is_not_pregame_evidence(self):
        receipt = {**self.receipt, "committed_at": "2026-02-02T12:00:00Z"}
        self.assertEqual(self.make_rows(receipt=receipt), [])

    def test_commit_before_collector_time_rejected(self):
        with self.assertRaisesRegex(ValueError, "COMMIT_PRECEDES"):
            self.make_rows(receipt={**self.receipt, "committed_at": "2026-02-01T11:59:00Z"})

    def test_unpinned_source_url_rejected(self):
        with self.assertRaises(ValueError):
            source_url("main")
        with self.assertRaises(ValueError):
            self.make_rows(receipt={**self.receipt, "source_url": "https://example.invalid/data"})

    def test_nonstandard_and_fantasy_contracts_not_invented(self):
        doc = copy.deepcopy(self.doc)
        doc["props"][0]["stat"] = "Fantasy Score"
        self.assertEqual(self.make_rows(doc=doc), [])
        doc["props"][0]["stat"] = "Points"
        doc["props"][0]["oddsType"] = "demon"
        self.assertEqual(self.make_rows(doc=doc), [])

    def test_changed_line_cannot_reuse_original_capture(self):
        self.assertFalse(capture_matches({**self.row, "line": 27.5}, self.raw, self.root))

    def test_secondary_capture_cannot_claim_native_authentication(self):
        self.assertFalse(capture_matches({**self.row, "platform_authenticity_independently_attested": True}, self.raw, self.root))

    def test_receipt_path_escape_or_mutation_rejected(self):
        self.assertFalse(capture_matches({**self.row, "source_receipt_file": "../receipt.json"}, self.raw, self.root))
        (self.root / "receipt.json").write_text("{}")
        self.assertFalse(capture_matches(self.row, self.raw, self.root))

    def test_separate_ledger_readiness_does_not_promote_full(self):
        path = self.root / "lines.sqlite"
        with sqlite3.connect(path) as conn:
            ingest(conn, [self.row])
        r = inspect_ledger(path, self.root, minimum=1)
        self.assertEqual(r["source_linked_snapshots"], 1)
        self.assertEqual(r["source_tiers"], {SOURCE_TIER: 1})
        self.assertEqual(r["certification"], "NOT_CERTIFIED")
        self.assertTrue(r["ledger_unchanged"])


class BaselineEvaluationTests(unittest.TestCase):
    def rows(self):
        return [{"game_id": "fixture-" + str(i), "platform": "Fixture", "market": "points", "line": 26.5,
                 "tipoff_utc": (dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)).isoformat(),
                 "p_over_raw": .3 if i % 2 else .7, "over_result": i % 2} for i in range(60)]

    def test_calibration_is_prior_only_game_grouped_and_not_twon(self):
        rows = self.rows()
        r = evaluate_rows(rows)
        self.assertEqual(r["evaluated_strata"], 1)
        s = r["strata"][0]
        self.assertEqual((s["train_n"], s["holdout_n"]), (36, 24))
        self.assertTrue(all(x["tipoff_utc"] >= r["global_holdout_cutoff_utc"] for x in s["holdout_results"]))
        self.assertFalse(r["simulator_calibrated"])
        self.assertEqual(r["simulation_trials_executed"], 0)
        self.assertEqual(r["certification"], "NOT_CERTIFIED")

    def test_strata_cannot_pool_distinct_markets_to_pass(self):
        rows = self.rows()
        for i, r in enumerate(rows):
            r["market"] = "assists" if i % 2 else "points"
        self.assertEqual(evaluate_rows(rows)["evaluated_strata"], 0)

    def test_same_game_conflicting_times_fail(self):
        rows = self.rows()
        rows[1]["game_id"] = rows[0]["game_id"]
        with self.assertRaisesRegex(ValueError, "CONFLICTING_CANONICAL"):
            evaluate_rows(rows)

    def test_probability_ties_use_explicit_binary_direction(self):
        r = scores([{"p": .5, "over_result": 0}, {"p": .5, "over_result": 1}], "p")
        self.assertEqual(r["directional_accuracy"], .5)
        self.assertEqual(r["probability_ties_n"], 2)
        self.assertEqual(r["brier"], .25)


class SavedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "nba_warehouse.sqlite"
        row = dict(zip(FIELDS, ["Fixture Player", "2026-02-01", "2025-26", "BOS", "NYK", 1, 1, 30, 20, 5, 5, 1, 0, 2, 2]))
        conn = connect(self.db)
        conn.execute("INSERT INTO games VALUES (" + ",".join("?" for _ in FIELDS) + ")", tuple(row.values()))
        conn.executescript("CREATE TABLE game_verifications(player,date,team,nba_game_id,nba_player_id,canonical_json);"
                           "CREATE TABLE source_files(name,sha256); CREATE TABLE source_records(file_sha256,payload_json);")
        conn.execute("INSERT INTO game_verifications VALUES (?,?,?,?,?,?)", (row["player"], row["date"], row["team"], "fixture", "1", json.dumps(row)))
        conn.execute("INSERT INTO source_files VALUES (?,?)", ("nba_stats_schedule_master.parquet", "fixture-schedule"))
        conn.execute("INSERT INTO source_records VALUES (?,?)", ("fixture-schedule", json.dumps({"game_id": "fixture", "is_neutral": False})))
        conn.commit()
        conn.close()
        folder = self.root / "official_evidence/fresh_stats"
        folder.mkdir(parents=True)
        self.source = folder / "league_2025-26.json"
        headers = ["GAME_ID", "PLAYER_ID", "PLAYER_NAME", "GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M"]
        values = ["fixture", "1", "Fixture Player", "2026-02-01", "BOS", "BOS vs. NYK", 30, 20, 5, 5, 1, 0, 2, 2]
        write_json(self.source, {"resultSets": [{"headers": headers, "rowSet": [values]}]})
        write_json(folder / "fetch_receipt.json", [{"name": "league_2025-26", "http_status": 200,
            "url": "https://stats.nba.com/stats/leaguegamelog?Season=2025-26", "sha256": digest(self.source),
            "started_utc": "2026-02-03T12:00:00Z"}])
        write_json(self.root / "DELIVERY_MANIFEST.json", {"database_sha256": digest(self.db)})

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_official_proof_works_without_new_network_requests(self):
        before = digest(self.db)
        r = audit_saved_history(self.root)
        self.assertEqual(r["status"], "PASS_COMPLETE_SELECTED_SEASONS")
        self.assertEqual(r["seasons"][0]["official_records_missing"], 0)
        self.assertEqual(digest(self.db), before)
        self.assertEqual(r["certification"], "NOT_CERTIFIED")

    def test_altered_official_response_fails_and_preserves_input(self):
        before = digest(self.db)
        self.source.write_text("{}")
        r = audit_saved_history(self.root)
        self.assertEqual(r["status"], "FAILED_SAVED_HISTORY_AUDIT")
        self.assertTrue(r["database_unchanged"])
        self.assertEqual(digest(self.db), before)

    def test_missing_warehouse_row_does_not_inherit_prior_pass(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM games")
        r = audit_saved_history(self.root)
        self.assertEqual(r["status"], "FAILED_SAVED_HISTORY_AUDIT")


class ReconstructionTests(unittest.TestCase):
    def test_target_results_and_future_players_cannot_change_forecast_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            warehouse, shot_db = root / "warehouse.sqlite", root / "shots.sqlite"
            conn = connect(warehouse)
            conn.executescript("CREATE TABLE verified_history(player,date,team,nba_game_id);"
                "CREATE TABLE source_files(name,sha256); CREATE TABLE source_records(file_sha256,payload_json);")
            conn.execute("INSERT INTO source_files VALUES ('player_boxscores_2026.parquet','fixture-source')")
            shots = sqlite3.connect(shot_db)
            shots.execute("CREATE TABLE verified_shooting(player,game_date,team,fg2m,fg2a,fg3m,fg3a,ftm,fta)")
            for day in range(1, 13):
                date = f"2026-01-{day:02d}"
                gid = "fixture-" + str(day)
                for team, opponent, home in (("BOS", "NYK", 1), ("NYK", "BOS", 0)):
                    for i in range(10):
                        name = team + " Fixture " + str(i)
                        values = [name,date,"2025-26",team,opponent,home,1,24,14,4,2,1,1,1,2]
                        conn.execute("INSERT INTO games VALUES (" + ",".join("?" for _ in FIELDS) + ")", values)
                        conn.execute("INSERT INTO verified_history VALUES (?,?,?,?)", (name,date,team,gid))
                        raw = {"game_id":gid,"team_tricode":team,"minutes":"24:00","field_goals_made":5,
                               "field_goals_attempted":10,"free_throws_attempted":2,"rebounds_offensive":1,
                               "rebounds_defensive":3,"turnovers":1,"assists":2,"blocks":1}
                        conn.execute("INSERT INTO source_records VALUES ('fixture-source',?)", (json.dumps(raw),))
                        shots.execute("INSERT INTO verified_shooting VALUES (?,?,?,?,?,?,?,?,?)", (name,date,team,3,6,2,4,2,2))
            target = ["BOS Fixture 0","2026-02-01","2025-26","BOS","NYK",1,1,40,9999,99,99,9,9,9,9]
            conn.execute("INSERT INTO games VALUES (" + ",".join("?" for _ in FIELDS) + ")", target)
            conn.commit()
            shots.commit()
            shots.close()
            snapshot = {"player":"BOS Fixture 0","team":"BOS","opponent":"NYK","game_date":"2026-02-01",
                        "tipoff_utc":"2026-02-01T23:00:00Z","game_id":"fixture-target"}
            before = build_context(warehouse, shot_db, snapshot)
            conn.execute("UPDATE games SET pts=0,minutes=0 WHERE date='2026-02-01'")
            future = ["Future Fixture","2026-02-10","2025-26","BOS","NYK",1,1,48,100,20,20,0,0,0,10]
            conn.execute("INSERT INTO games VALUES (" + ",".join("?" for _ in FIELDS) + ")", future)
            conn.commit()
            conn.close()
            after = build_context(warehouse, shot_db, snapshot)
            for key in ("rosters", "pace_per_team", "team_rates", "max_feature_game_date", "prior_team_dates"):
                self.assertEqual(before[key], after[key])
            self.assertEqual(before["input_mode"], "RETROSPECTIVE_PRIOR_HISTORY_RECONSTRUCTION")
            self.assertFalse(before["historical_availability_verified"])
            self.assertLessEqual(before["max_feature_game_date"], "2026-01-30")
            self.assertEqual({t:sum(p["minutes_target"] for p in r) for t,r in before["rosters"].items()}, {"BOS":240,"NYK":240})

    def test_minutes_conserve_with_outsize_weight_and_legal_caps(self):
        targets = allocate_minutes({"star": 1000, **{"fixture-" + str(i): 1 for i in range(7)}})
        self.assertEqual(sum(targets.values()), 240)
        self.assertTrue(all(0 <= v <= 48 for v in targets.values()))
        self.assertEqual(targets["star"], 48)

    def test_invalid_or_nonfinite_rotation_rejected(self):
        for weights in ({str(i): 1 for i in range(6)}, {str(i): float("nan") for i in range(7)}):
            with self.assertRaises(ValueError):
                allocate_minutes(weights)


if __name__ == "__main__":
    unittest.main()
