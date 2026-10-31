"""ESPN pregame evidence must be genuinely captured before tipoff."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from benfrank_v51_espn_pregame import upcoming_events,candidates,collect

UTC=dt.timezone.utc
START=dt.datetime(2026,10,30,16,0,tzinfo=UTC)
TIP="2026-10-30T23:30:00Z"
def board(start=TIP,completed=False):
    return {"events":[{"id":"401990111","date":start,
        "status":{"type":{"completed":completed,"state":"post" if completed else "pre"}},
        "competitions":[{"competitors":[
            {"homeAway":"home","team":{"abbreviation":"DEN"}},
            {"homeAway":"away","team":{"abbreviation":"PHX"}}]}]}]}
def summary():
    return {"header":{"competitions":[{"id":"401990111",
        "status":{"type":{"completed":False}}}]},
        "boxscore":{"players":[{"team":{"abbreviation":"DEN"},"statistics":[{"athletes":[
            {"starter":True,"athlete":{"id":"203999","displayName":"Nikola Jokic"}},
            {"starter":False,"athlete":{"id":"2001","displayName":"Other Athlete"}}
        ]}]}]}}
def fake(url):
    data=board() if "scoreboard" in url else summary()
    return data,json.dumps(data).encode()
class PregameESPNTests(unittest.TestCase):
    def test_only_genuinely_unstarted_games_eligible(self):
        self.assertEqual(len(upcoming_events(board(),"2026-10-30",START)),1)
        self.assertEqual(upcoming_events(board(),"2026-10-30",
                          dt.datetime(2026,10,30,23,40,tzinfo=UTC)),[])
        self.assertEqual(upcoming_events(board(completed=True),"2026-10-30",START),[])
    def test_unlisted_players_never_assumed_available(self):
        g=upcoming_events(board(),"2026-10-30",START)[0]
        players,status=candidates(summary(),g)
        self.assertEqual(len(players),1)
        self.assertEqual(players[0]["evidence"],"ESPN_PREGAME_LISTED_STARTER_NOT_OFFICIAL")
        self.assertNotIn("Other Athlete",[p["player"] for p in players])
    def test_before_tipoff_receipt_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            result=collect("2026-10-30",folder,fetch=fake,clock=lambda:START)
            self.assertEqual(result["listed_pregame_starters"],1)
            self.assertEqual(result["final_official_starters_confirmed"],0)
            self.assertFalse(result["native_prizepicks_lines_authenticated"])
            self.assertEqual(result["ticket_authority"],"NO_TICKET")
    def test_delayed_summary_after_tipoff_not_promoted(self):
        calls=iter([START,dt.datetime(2026,10,30,23,40,tzinfo=UTC)])
        with tempfile.TemporaryDirectory() as folder:
            r=collect("2026-10-30",folder,fetch=fake,clock=lambda:next(calls))
            self.assertEqual(r["listed_pregame_starters"],0)
            self.assertTrue(any("AFTER_TIPOFF" in e["reason"] for e in r["issues"]))
    def test_cannot_backdate_pregame_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"NOT_CONTEMPORANEOUS"):
                collect("2026-10-28",folder,fetch=fake,clock=lambda:START)
if __name__=="__main__":
    unittest.main()
