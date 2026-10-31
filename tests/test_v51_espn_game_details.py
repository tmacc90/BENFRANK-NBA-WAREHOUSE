"""ESPN.com direct game details, shooting evidence and cut-off tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from benfrank_v51_espn_game_details import (
    completed_scoreboard_events,verify_completed_summary,
    extract_plays,coordinate_shots,collect,BASE
)
EVENT="401990123"
DATE="2026-10-29"
STAMP="2026-10-29T23:30:00Z"
def scoreboard(complete=True,stamp=STAMP):
    return {"events":[{"id":EVENT,"date":stamp,"status":{"type":{"completed":complete}},
       "season":{"type":2},
       "competitions":[{"competitors":[
          {"homeAway":"home","team":{"abbreviation":"IND"}},
          {"homeAway":"away","team":{"abbreviation":"MIA"}}]}]}]}
def summary(final=True,stamp=STAMP):
    columns=["MIN","PTS","REB","AST","STL","BLK","TO","3PT","FG","FT"]
    groups=[]
    for team in ("IND","MIA"):
        players=[]
        for i in range(9):
            plays=["30:00","5","2","1","0","0","1","1-2","2-4","0-0"]
            players.append({"athlete":{"id":str(10000+i+(1000 if team=="IND" else 2000)),
                                       "displayName":f"{team} Player {i}"},
                             "didNotPlay":False,"starter":i<5,"stats":plays})
        groups.append({"team":{"abbreviation":team},
                       "statistics":[{"labels":columns,"athletes":players}]})
    plays=[{"id":str(i),"type":{"text":"Jump Shot"},
            "text":"Player jump shot",
            "shootingPlay":True,"scoringPlay":i%2==0,
            "coordinate":{"x":10+i%20,"y":5},
            "period":{"number":1},"clock":{"displayValue":"10:00"},
            "athletes":[{"athlete":{"id":"10001"}}],
            "team":{"id":"11"}} for i in range(40)]
    return {"header":{"competitions":[{"id":EVENT,"date":stamp,
           "status":{"type":{"completed":final}},
           "competitors":[
             {"homeAway":"home","team":{"abbreviation":"IND"}},
             {"homeAway":"away","team":{"abbreviation":"MIA"}}]}]},
           "boxscore":{"players":groups},"plays":plays}
def asbytes(obj):
    return json.dumps(obj).encode()
class ESPNEvidenceTests(unittest.TestCase):
    def test_only_final_completed_event_before_target(self):
        self.assertEqual(len(completed_scoreboard_events(scoreboard(),DATE)),1)
        self.assertEqual(completed_scoreboard_events(scoreboard(False),DATE),[])
        self.assertEqual(completed_scoreboard_events(scoreboard(), "2026-10-30"),[])
    def test_summary_comparison_rejects_not_final_and_wrong_teams(self):
        event=completed_scoreboard_events(scoreboard(),DATE)[0]
        self.assertTrue(verify_completed_summary(summary(),event))
        with self.assertRaisesRegex(ValueError,"NOT_FINAL"):
            verify_completed_summary(summary(False),event)
        x=summary()
        x["header"]["competitions"][0]["competitors"][0]["team"]["abbreviation"]="NYK"
        with self.assertRaisesRegex(ValueError,"OPPONENT_CONFLICT"):
            verify_completed_summary(x,event)
    def test_shot_coordinates_preserved_without_calibration_claim(self):
        actions,status=extract_plays(summary())
        self.assertEqual(status,"ESPN_ACTION_SEQUENCE_CAPTURED")
        rows,rejected=coordinate_shots(actions)
        self.assertEqual(len(rows),40)
        self.assertEqual(rejected,0)
        self.assertEqual(rows[0][4:6],(10.0,5.0))
        self.assertEqual(rows[0][6],1)
    def test_invalid_coordinates_not_imputed(self):
        actions,status=extract_plays(summary())
        raw=list(actions)
        idx,pid,q,clk,payload=raw[0]
        play=json.loads(payload)
        play["coordinate"]={"x":None,"y":3000}
        raw[0]=(idx,pid,q,clk,json.dumps(play))
        rows,bad=coordinate_shots(raw)
        self.assertEqual(len(rows),39)
        self.assertEqual(bad,1)
    def test_writes_completions_without_using_target_date_results(self):
        def fetch(url):
            if "scoreboard" in url:
                day=url.rsplit("=",1)[-1]
                return asbytes(scoreboard()) if day=="20261029" else asbytes({"events":[]})
            if "summary?event=" in url:return asbytes(summary())
            raise AssertionError("Unapproved URL "+url)
        with tempfile.TemporaryDirectory() as folder:
            report=collect("2026-10-30",folder,days=2,max_events=20,fetch=fetch)
            self.assertEqual(report["completed_games"],1)
            self.assertEqual(report["played_player_rows"],18)
            self.assertEqual(report["game_play_sequences"],1)
            self.assertEqual(report["observed_espn_shot_coordinates"],40)
            self.assertFalse(report["confirmed_pregame_starters"])
            self.assertFalse(report["shot_coordinate_system_independently_verified"])
            self.assertEqual(report["ticket_authority"],"NO_TICKET")
            c=sqlite3.connect(Path(folder)/"espn_completed_evidence.sqlite")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM espn_shot_coordinates").fetchone()[0],40)
            self.assertEqual(c.execute("SELECT count(*) FROM current_games WHERE date>=?",("2026-10-30",)).fetchone()[0],0)
            c.close()
if __name__=="__main__":
    unittest.main()
