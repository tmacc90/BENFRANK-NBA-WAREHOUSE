import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benfrank_v47_live_official_injuries import collect

UTC=dt.timezone.utc

class LiveOfficialInjuryTests(unittest.TestCase):
    def now(self):
        return dt.datetime.now(UTC).isoformat()

    def official_receipt(self):
        return {"status":"PRESERVED_ORIGINAL_OFFICIAL_PREGAME_REPORT",
                "file":"test.pdf","text_file":"test.txt",
                "sha256":"a"*64,
                "report_time_utc":"2026-10-30T15:00:00+00:00",
                "retrieved_at":self.now(),
                "url":"https://ak-static.cms.nba.com/referee/injury/example.pdf"}

    def test_missing_pdf_does_not_infer_healthy(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "benfrank_v47_live_official_injuries.capture_before",
            return_value={"status":"BLOCKED_NO_VERIFIED_OFFICIAL_REPORT","attempts":[{"http_status":404}]}):
            result=collect(self.now(),temp)
            self.assertEqual(result["status"],"BLOCKED_OFFICIAL_REPORT_UNAVAILABLE")
            self.assertEqual(result["unlisted_player_status"],"UNKNOWN_NOT_CLEARED")
            self.assertFalse(result["official_starter_confirmation"])
            self.assertTrue((Path(temp)/"official-injury-captures.json").exists())

    def test_verified_doc_observations_have_actual_retrieval_asof(self):
        group={"submission_status":"SUBMITTED_WITH_LISTED_PLAYERS",
               "players":{"p":{"player":"Test Player","status":"Out"}}}
        parsed={"game_team_reports":{"2026-10-30|NYK@BOS|BOS":group},
                "issues":[]}
        with tempfile.TemporaryDirectory() as temp, patch(
            "benfrank_v47_live_official_injuries.capture_before",
            return_value=self.official_receipt()), patch(
            "benfrank_v47_live_official_injuries.parse_pdf",return_value=parsed):
            result=collect(self.now(),temp)
            self.assertEqual(result["status"],"OFFICIAL_PDF_PARSED")
            self.assertEqual(result["listed_player_status_counts"]["Out"],1)
            self.assertEqual(result["availability_asof_not_before"],result["retrieved_at"])
            self.assertEqual(result["ticket_authority"],"NO_TICKET")

    def test_parser_issues_remain_visible(self):
        parsed={"game_team_reports":{},
                "issues":[{"reason":"UNPARSED_PLAYER_STATUS_ROW"}]}
        with tempfile.TemporaryDirectory() as temp, patch(
            "benfrank_v47_live_official_injuries.capture_before",
            return_value=self.official_receipt()), patch(
            "benfrank_v47_live_official_injuries.parse_pdf",return_value=parsed):
            result=collect(self.now(),temp)
            self.assertEqual(result["status"],"OFFICIAL_PDF_PARSED_WITH_ISSUES")
            self.assertEqual(len(result["parser_issues"]),1)

    def test_future_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                collect((dt.datetime.now(UTC)+dt.timedelta(hours=2)).isoformat(),temp)

    def test_backdating_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                collect((dt.datetime.now(UTC)-dt.timedelta(days=2)).isoformat(),temp)

if __name__=="__main__":
    unittest.main()
