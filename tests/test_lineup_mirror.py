import unittest
import pandas as pd
from benfrank_lineup_mirror import (
    season_end_for_date, name_key, _parse_minutes, _player_event_stats
)

class TestLineupMirror(unittest.TestCase):
    def test_season_end(self):
        self.assertEqual(season_end_for_date("2026-11-06"), 2027)
        self.assertEqual(season_end_for_date("2026-05-01"), 2026)

    def test_name_key(self):
        self.assertEqual(name_key("Luka Dončić"), name_key("Luka Doncic"))

    def test_minutes(self):
        self.assertAlmostEqual(_parse_minutes("PT36M30.00S"), 36.5)
        self.assertAlmostEqual(_parse_minutes("12:30"), 12.5)

    def test_scoring_events(self):
        df = pd.DataFrame([
            {"person_id": 1, "event_type":"made_shot", "is_field_goal":1,
             "shot_value":3, "shot_result":"Made"},
            {"person_id": 1, "event_type":"missed_shot", "is_field_goal":1,
             "shot_value":2, "shot_result":"Missed"},
            {"person_id": 1, "event_type":"free_throw", "is_field_goal":0,
             "shot_value":1, "shot_result":"Made"},
            {"person_id": 1, "event_type":"turnover", "is_field_goal":0},
            {"person_id": 2, "event_type":"made_shot", "is_field_goal":1,
             "shot_value":2, "shot_result":"Made"},
        ])
        out = _player_event_stats(df, 1)
        self.assertEqual(out["pts"], 4)
        self.assertEqual(out["fga"], 2)
        self.assertEqual(out["fg3a"], 1)
        self.assertEqual(out["fta"], 1)
        self.assertEqual(out["tov"], 1)

if __name__ == "__main__":
    unittest.main()
