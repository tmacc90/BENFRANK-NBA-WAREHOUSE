import unittest
from benfrank_lineup_acquisition import (
    iso_seconds, elapsed, _nba_game_ids, validate_minutes,
    reconstruct_stints, enrich_stints, summarize_game
)

class TestLineupAcquisition(unittest.TestCase):
    def test_clock_math(self):
        self.assertEqual(iso_seconds("PT12M00.00S"), 720)
        self.assertEqual(elapsed(1, "PT11M00.00S"), 60)
        self.assertEqual(elapsed(4, "PT0M00.00S"), 2880)

    def test_extract_nba_game_ids(self):
        record = {
            "source_game_id": "401999999",
            "source_game_ids": {
                "ESPN": ["401999999"],
                "NBA_STATS_ARCHIVE": ["0022400001"],
            },
        }
        self.assertEqual(_nba_game_ids(record), ["0022400001"])

    def test_minute_validation_full(self):
        players = []
        for tid, ids in ((1, range(1, 6)), (2, range(6, 11))):
            for pid in ids:
                players.append({
                    "team_id": tid, "player_id": pid, "name": str(pid),
                    "starter": True, "minutes": 12.0, "official": {}
                })
        stints = [{
            "period": 1, "start": 0.0, "end": 720.0,
            "lineups": {"1": [1,2,3,4,5], "2": [6,7,8,9,10]},
        }]
        result = validate_minutes(stints, players)
        self.assertEqual(result["quality"], "FULL")
        self.assertEqual(result["minute_error_pct"], 0.0)

    def test_q1_substitution_keeps_five(self):
        players = []
        for pid in range(1, 7):
            players.append({
                "team_id": 1, "player_id": pid, "name": f"P{pid}",
                "starter": pid <= 5, "minutes": 0.0, "official": {}
            })
        for pid in range(7, 13):
            players.append({
                "team_id": 2, "player_id": pid, "name": f"P{pid}",
                "starter": pid <= 11, "minutes": 0.0, "official": {}
            })
        actions = [
            {"period":1,"clock":"PT12M00.00S","teamId":0,"personId":0,
             "actionType":"period","subType":"start","orderNumber":1},
            {"period":1,"clock":"PT11M30.00S","teamId":1,"personId":1,
             "actionType":"Made Shot","orderNumber":2},
            {"period":1,"clock":"PT11M00.00S","teamId":2,"personId":7,
             "actionType":"Made Shot","orderNumber":3},
            {"period":1,"clock":"PT06M00.00S","teamId":1,"personId":1,
             "actionType":"Substitution","description":"SUB: P6 FOR P1","orderNumber":4},
            {"period":1,"clock":"PT00M00.00S","teamId":0,"personId":0,
             "actionType":"period","subType":"end","orderNumber":5},
        ]
        stints = reconstruct_stints(actions, players)
        self.assertTrue(stints)
        self.assertTrue(all(len(ids) == 5 for s in stints for ids in s["lineups"].values()))
        self.assertIn(6, stints[-1]["lineups"]["1"])
        self.assertNotIn(1, stints[-1]["lineups"]["1"])

if __name__ == "__main__":
    unittest.main()
