"""Verify bounded ESPN final-summary recovery cannot fabricate extra games."""
import unittest
from unittest.mock import patch
from benfrank_v50_recover_espn_gap import checked_summary
class GapRecoveryTests(unittest.TestCase):
    def body(self,complete=True,date="2026-10-26T23:30:00Z"):
        return {"header":{"competitions":[{
            "id":"401909868","date":date,"status":{"type":{"completed":complete}},
            "competitors":[{"homeAway":"home","team":{"abbreviation":"MIA"}},
                           {"homeAway":"away","team":{"abbreviation":"DAL"}}]}]}}
    def fetch(self,body):
        return lambda u:(body,{"sha256":"a"*64,"retrieved_at":"2026-10-30T22:00:00+00:00"})
    def test_unfinished_game_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"NOT_COMPLETED"):
            checked_summary(401909868,"2026-10-30",["2026-10-26"],self.fetch(self.body(False)))
    def test_game_from_target_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"DATE_NOT_EXPLICITLY_ALLOWED"):
            checked_summary(401909868,"2026-10-30",["2026-10-26"],self.fetch(self.body(True,"2026-10-30T23:30:00Z")))
    def test_event_id_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,"SUMMARY_EVENT_ID_CONFLICT"):
            checked_summary(401909869,"2026-10-30",["2026-10-26"],self.fetch(self.body()))
    def test_summary_requires_both_teams(self):
        b=self.body()
        b["header"]["competitions"][0]["competitors"][1]["homeAway"]="home"
        with self.assertRaisesRegex(ValueError,"NO_VERIFIED_BOTH_TEAMS"):
            checked_summary(401909868,"2026-10-30",["2026-10-26"],self.fetch(b))
    def test_success_requires_twelve_observed_player_rows(self):
        with patch("benfrank_v50_recover_espn_gap.rows_from_summary",return_value=[]):
            with self.assertRaisesRegex(ValueError,"COVERAGE_TOO_LOW"):
                checked_summary(401909868,"2026-10-30",["2026-10-26"],self.fetch(self.body()))
if __name__=="__main__":
    unittest.main()
