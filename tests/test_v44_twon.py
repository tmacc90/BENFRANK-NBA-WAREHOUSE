import copy
import datetime as dt
import unittest
from benfrank_v44_twon import trial_run,simulate_game,validate,schedule

def fixture():
    teams=("BOS","NYK")
    out={"game_date":"2026-10-29","tipoff_utc":"2026-10-29T23:00:00Z",
         "home":teams[0],"away":teams[1],
         "pace_per_team":98.0,
         "pace_source":"TEST_FIXTURE_NOT_REAL_NBA",
         "pace_asof":"2026-10-29T12:00:00Z","rosters":{},"team_rates":{}}
    for team in teams:
        m=[38,38,34,32,30,25,23,20]
        roster=[]
        for i,x in enumerate(m):
            roster.append({"player":team+" Player "+str(i),
                "minutes_target":x,"fg2a_per36":9.5,
                "fg3a_per36":4.0,"fta_per36":3,
                "fg2_pct":0.50,"fg3_pct":0.36,"ft_pct":0.78,
                "ast_per36":4,"reb_per36":6,"stl_per36":1.3,
                "blk_per36":0.5,"tov_per36":2.0,
                "source":"TEST_FIXTURE_NOT_REAL_NBA","asof":"2026-10-29T12:00:00Z"})
        out["rosters"][team]=roster
        out["team_rates"][team]={
            "off_reb_probability":0.25,"assist_probability":0.62,
            "block_on_missed_fg_probability":0.06,
            "shooting_foul_probability":0.10,
            "source":"TEST_FIXTURE_NOT_REAL_NBA","asof":"2026-10-29T12:00:00Z"}
    self_mins=sum(x["minutes_target"] for x in out["rosters"]["BOS"])
    assert self_mins==240
    return out

class TwonTests(unittest.TestCase):
    def test_48_minute_five_on_floor_schedule(self):
        c=fixture()
        for t in ("BOS","NYK"):
            sched=schedule(c["rosters"][t])
            self.assertEqual(len(sched),48)
            self.assertTrue(all(len(set(s))==5 for s in sched))
            for player in c["rosters"][t]:
                self.assertEqual(sum(player["player"] in minute for minute in sched),
                                 player["minutes_target"])
    def test_regulation_minutes_and_stat_conservation(self):
        c=fixture()
        r=simulate_game(c,seed=7)
        self.assertEqual(r["regulation_team_minutes"],{"BOS":240,"NYK":240})
        self.assertEqual(r["possession_count_regulation"],196)
        self.assertEqual(sum(x["points"] for n,x in r["stats"].items() if n.startswith("BOS")),r["score"]["BOS"])
    def test_exact_line_trial_receipt_and_determinism(self):
        c=fixture()
        r=trial_run(c,"BOS Player 0","points",21.5,trials=10,seed=7)
        again=trial_run(c,"BOS Player 0","points",21.5,trials=10,seed=7)
        self.assertEqual(r["status"],"EXECUTED_BELOW_25K")
        self.assertEqual(r["over_count"],again["over_count"])
        self.assertEqual(r["under_count"],again["under_count"])
        self.assertEqual(r["ticket_authority"],"NO_TICKET")
        self.assertEqual(r["over_count"]+r["under_count"]+r["push_count"],10)
    def test_incomplete_source_is_blocked(self):
        c=fixture()
        del c["rosters"]["BOS"][0]["fg3_pct"]
        with self.assertRaises(ValueError):
            validate(c)
    def test_wrong_minutes_blocked(self):
        c=fixture()
        c["rosters"]["BOS"][0]["minutes_target"]=30
        with self.assertRaises(ValueError):
            trial_run(c,"BOS Player 0","points",20.5,trials=5)
    def test_no_fake_source_context_pass(self):
        c=fixture()
        del c["team_rates"]["BOS"]["source"]
        with self.assertRaises(ValueError):
            validate(c)

if __name__=="__main__":
    unittest.main()
