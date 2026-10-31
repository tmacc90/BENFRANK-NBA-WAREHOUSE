"""Official prior NBA final boxscore and PBP source contract tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from benfrank_v51_nba_official import (
    games_before,minutes,parsed_game,collect,NBA
)

def sample_schedule():
    return {"leagueSchedule":{"gameDates":[{"games":[
      {"gameId":"0022600123","gameDateTimeUTC":"2026-10-30T00:30:00Z",
       "gameStatus":3,"homeTeam":{"teamTricode":"IND"},"awayTeam":{"teamTricode":"MIA"}},
      {"gameId":"0022600124","gameDateTimeUTC":"2026-10-31T00:30:00Z",
       "gameStatus":2,"homeTeam":{"teamTricode":"DAL"},"awayTeam":{"teamTricode":"HOU"}}
    ]}]}}
def sample_box():
    teams=[]
    for team in ("IND","MIA"):
        players=[]
        for i in range(7):
            played=(i!=6)
            players.append({"personId":str((100 if team=="IND" else 200)+i),
                "name":f"{team} Player {i}","played":"1" if played else "0",
                "starter":i<5,"statistics":{
                    "minutes":"PT30M00.00S",
                    "points":5,"reboundsTotal":2,"assists":1,"steals":0,
                    "blocks":0,"turnovers":1,
                    "threePointersMade":1,"fieldGoalsMade":2,
                    "fieldGoalsAttempted":4,"threePointersAttempted":2,
                    "freeThrowsMade":0,"freeThrowsAttempted":1,
                    "reboundsOffensive":1,"reboundsDefensive":1}})
        teams.append({"teamTricode":team,"players":players})
    return {"game":{"gameId":"0022600123","gameStatus":3,
        "homeTeam":teams[0],"awayTeam":teams[1]}}
class NBAOfficialSourceTests(unittest.TestCase):
    def test_only_final_prior_day_games_are_eligible(self):
        games,count=games_before(sample_schedule(),"2026-10-30",3,20)
        self.assertEqual(count,1)
        self.assertEqual(games[0]["game_date"],"2026-10-29")
        self.assertEqual(games[0]["game_id"],"0022600123")
    def test_nba_duration_and_fgm(self):
        self.assertAlmostEqual(minutes("PT20M30.00S"),20.5)
        for v in ("20:30","PT100M00S","invalid"):
            with self.subTest(value=v),self.assertRaises(ValueError):
                minutes(v)
    def test_primary_boxscore_cannot_make_nonfinal_game_eligible(self):
        box=sample_box()
        box["game"]["gameStatus"]=2
        expected={"game_id":"0022600123","game_date":"2026-10-29",
                  "home":"IND","away":"MIA"}
        with self.assertRaisesRegex(ValueError,"NOT_FINAL"):
            parsed_game(box,expected,"a"*64,"2026-10-30T00:00:00Z")
    def test_boxscore_stat_conflicts_are_quarantined(self):
        box=sample_box()
        box["game"]["homeTeam"]["players"][0]["statistics"]["points"]=99
        expected={"game_id":"0022600123","game_date":"2026-10-29",
                  "home":"IND","away":"MIA"}
        rows,ex=parsed_game(box,expected,"a"*64,"2026-10-30T00:00:00Z")
        self.assertEqual(len(rows),11)
        self.assertTrue(any("POINT_ACCOUNTING" in x["reason"] for x in ex))
    def test_end_to_end_official_finals_and_playbyplay_have_source_hashes(self):
        schedule=sample_schedule()
        box=sample_box()
        play={"game":{"gameId":"0022600123","actions":[{"actionNumber":i} for i in range(40)]}}
        def fake(url,limit):
            payload=box if "boxscore_" in url else play
            return 200,"application/json",json.dumps(payload).encode()
        with tempfile.TemporaryDirectory() as d:
            r=collect("2026-10-30",d,days=3,max_games=20,
                      fetch=fake,raw_schedule=schedule)
            self.assertEqual(r["final_boxes"],1)
            self.assertEqual(r["official_player_game_rows"],12)
            self.assertEqual(r["official_pbp_games"],1)
            self.assertFalse(r["pregame_lineup_confirmation"])
            self.assertEqual(r["ticket_authority"],"NO_TICKET")
            c=sqlite3.connect(Path(d)/"nba_official_2026_27.sqlite")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM nba_official_completed").fetchone()[0],12)
            self.assertEqual(c.execute("SELECT MAX(game_date) FROM nba_official_completed").fetchone()[0],"2026-10-29")
            self.assertTrue((Path(d)/"official_pbp_0022600123.json").exists())
            c.close()
if __name__=="__main__":
    unittest.main()
