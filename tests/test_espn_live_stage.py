import json
import unittest
from espn_live_stage import rows_from_summary, fetch_staged, parse_minutes, season_for_date

def summary_one():
    return {"boxscore":{"players":[{"team":{"abbreviation":"BOS"},
         "statistics":[{"labels":["MIN","FG","3PT","FT","REB","AST","STL","BLK","TO","PTS"],
                        "athletes":[{"athlete":{"displayName":"Test Player"},
                                     "starter":True,"stats":["31:30","7-15","2-6","1-2","8","5","1","0","2","17"]}]}]},
         {"team":{"abbreviation":"NYK"},"statistics":[]}]}}

class FakeResponse:
    def __init__(self,obj):
        self.data=json.dumps(obj).encode()
        self.status=200
    def __enter__(self):
        return self
    def __exit__(self,*_):
        pass
    def read(self,max_length):
        return self.data[:max_length]

class ESPNStageTests(unittest.TestCase):
    def test_minute_clock(self):
        self.assertEqual(parse_minutes("31:30"),31.5)
        self.assertEqual(season_for_date("2026-10-29"),"2026-27")
    def test_parse_secondary_rows_only(self):
        r=rows_from_summary("401000","2026-10-29","BOS","NYK",summary_one())
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["fg3m"],2)
        self.assertEqual(r[0]["starter"],1)
        self.assertEqual(r[0]["pts"],17)
    def test_bad_team_fails(self):
        with self.assertRaises(ValueError):
            rows_from_summary("401000","2026-10-29","MIA","NYK",summary_one())
    def test_live_collection_mock(self):
        scoreboard={"events":[{"id":"401000","season":{"type":2},
              "status":{"type":{"completed":True}},
              "competitions":[{"competitors":[
                {"homeAway":"home","team":{"abbreviation":"BOS"}},
                {"homeAway":"away","team":{"abbreviation":"NYK"}}]}]}]}
        def opener(req,timeout=18):
            return FakeResponse(summary_one() if "summary?" in req.full_url else scoreboard)
        r=fetch_staged("2026-10-29",max_events=1,opener=opener)
        self.assertEqual(r["status"],"PARSED_UNVERIFIED")
        self.assertEqual(len(r["staged_rows"]),1)
        self.assertEqual(r["official_verified_rows"],0)
    def test_no_final_game_is_not_faked(self):
        def opener(req,timeout=18):
            return FakeResponse({"events":[]})
        r=fetch_staged("2026-10-29",opener=opener)
        self.assertEqual(r["status"],"NO_COMPLETED_REGULAR_GAMES")
        self.assertFalse(r["staged_rows"])

if __name__=="__main__":
    unittest.main()
