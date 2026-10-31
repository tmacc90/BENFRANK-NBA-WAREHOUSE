"""Roster capture contract: real team IDs required and no starters inferred."""
import json
import tempfile
import unittest
from pathlib import Path
from benfrank_v51_rosters import list_teams,fetch_roster,collect

def index():
    return {"sports":[{"leagues":[{"teams":[
        {"team":{"id":str(i),"abbreviation":"NYK" if i==1 else "TEAM"}}
        for i in range(1,31)]}]}]}
def roster():
    return json.dumps({"athletes":[{"id":str(i),"displayName":f"Player {i}"} for i in range(14)]}).encode()
class RosterSourceTests(unittest.TestCase):
    def test_index_supports_all_30_nba_team_ids(self):
        self.assertEqual(len(list_teams(index())),30)
    def test_missing_index_doesnt_become_complete(self):
        with self.assertRaises(ValueError):
            list_teams({"sports":[]})
    def test_source_roster_collect_does_not_claim_lineup(self):
        with tempfile.TemporaryDirectory() as folder:
            index_path=Path(folder)/"teams.json"
            index_path.write_text(json.dumps(index()))
            result=collect(index_path,Path(folder)/"out",
                           fetch=lambda url:roster(),workers=5)
            self.assertEqual(result["roster_teams_collected"],30)
            self.assertEqual(result["player_roster_entries"],420)
            self.assertFalse(result["starter_confirmation"])
            self.assertFalse(result["injury_clearance_inferred"])
            self.assertEqual(result["ticket_authority"],"NO_TICKET")
    def test_short_team_roster_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"TOO_SHORT"):
            fetch_roster("1","NYK",fetch=lambda url:b'{"athletes":[]}')
    def test_no_external_host_or_unbounded_team_id(self):
        with self.assertRaisesRegex(ValueError,"TEAM_ID"):
            fetch_roster("1/../../secrets","NYK",fetch=lambda url:b'{}')
if __name__=="__main__":
    unittest.main()
