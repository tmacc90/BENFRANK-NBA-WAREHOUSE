"""Public collector is useful secondary history, never a native signed book feed."""
import json
import tempfile
import unittest
from benfrank_v51_secondary_lines import collect,recent_commit
COMMIT="a"*40
def commitstamp(stamp="2026-10-30T16:00:00Z"):
    return json.dumps([{"sha":COMMIT,"commit":{"committer":{"date":stamp}}}]).encode()
def source(tipoff="2026-10-31T00:00:00Z"):
    return json.dumps({"sport":"NBA","source":"PrizePicks API",
         "scrapedAt":"2026-10-30T15:45:00Z",
         "props":[{"sport":"NBA","oddsType":"standard","status":"pre_game",
                   "stat":"Points","line":25.5,"player":"Nikola Jokic",
                   "teamCode":"DEN","opponentCode":"PHX",
                   "startTimeIso":tipoff,"gameId":"abc"}]}).encode()
class PublicCollectorTests(unittest.TestCase):
    def test_commit_sha_and_time_required(self):
        sha,t=recent_commit(fetch=lambda url:commitstamp())
        self.assertEqual(sha,COMMIT)
        self.assertTrue(t.endswith("Z"))
    def test_current_exact_line_not_native_verified(self):
        with tempfile.TemporaryDirectory() as d:
            r=collect("2026-10-30",d,commit_fetch=lambda url:commitstamp(),
                      raw_fetch=lambda url:source())
            self.assertEqual(r["status"],"SECONDARY_PREGAME_ROWS_CAPTURED")
            self.assertEqual(r["current_date_pregame_rows"],1)
            self.assertFalse(r["native_platform_attestation"])
            self.assertEqual(r["ticket_authority"],"NO_TICKET")
    def test_same_data_after_source_tipoff_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            r=collect("2026-10-30",d,commit_fetch=lambda url:commitstamp(),
                      raw_fetch=lambda url:source("2026-10-30T15:00:00Z"))
            self.assertEqual(r["current_date_pregame_rows"],0)
            self.assertFalse(r["native_platform_attestation"])
    def test_invalid_commit_cannot_create_bet_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            r=collect("2026-10-30",d,
               commit_fetch=lambda url:b'[{"sha":"broken","commit":{"committer":{"date":"2026-10-30T16:00:00Z"}}}]')
            self.assertEqual(r["status"],"BLOCKED")
            self.assertEqual(r["current_date_pregame_rows"],0)
if __name__=="__main__":
    unittest.main()
