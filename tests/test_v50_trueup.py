"""Source-backed current season true-up tests; fixtures never enter production."""
import unittest
from benfrank_v50_trueup import norm,trueup,opponent_modifier

def r(player,date,minutes,points,team="MIA",opponent="IND"):
    return dict(player=player,date=date,season="2026-27",team=team,
                opponent=opponent,minutes=minutes,pts=points,reb=5,
                ast=4,stl=1,blk=0,tov=2,fg3m=2,fgm=7,fga=15,
                fg3a=6,ftm=2,fta=3,source_game_id="401900000")
def prop(player="Test Player",market="points",line=16.5):
    return [{"id":"unit","player":player,"market":market,"line":line,
             "opponent":"IND","now":{"projection":15.0,"direction":"UNDER"}}]
class TrueupTests(unittest.TestCase):
    def test_only_explicit_verified_portis_alias(self):
        self.assertEqual(norm("Bobby Portis Jr."),norm("Bobby Portis"))
        self.assertNotEqual(norm("Bobby Smith Jr."),norm("Bobby Smith"))
    def test_current_form_changes_projection(self):
        hist=[r("Test Player","2026-04-01",30,15) for _ in range(20)]
        cur=[r("Test Player","2026-10-22",32,27),r("Test Player","2026-10-28",32,30)]
        x=trueup(prop(),hist,cur,"2026-10-30")[0]
        self.assertGreater(x["new_projection"],15)
        self.assertEqual(x["status"],"EXECUTED_CURRENT_SEASON_SHRUNK_RATE_AND_ROLE_TRUEUP")
        self.assertEqual(x["ticket_authority"],"NO_TICKET")
        self.assertEqual(x["current_2026_27_games_eligible"],2)
    def test_future_games_not_silently_included(self):
        with self.assertRaisesRegex(ValueError,"CURRENT_ROW_AFTER_ASOF_CUTOFF"):
            trueup(prop(),[],[r("Test Player","2026-10-30",30,99)],"2026-10-30")
    def test_no_current_history_keeps_baseline(self):
        hist=[r("Test Player","2026-04-01",30,15)]
        x=trueup(prop(),hist,[],"2026-10-30")[0]
        self.assertEqual(x["new_projection"],15.0)
        self.assertEqual(x["status"],"NO_NEW_SEASON_PLAYER_HISTORY_KEEP_BASELINE")
    def test_synthetic_history_cannot_certify(self):
        hist=[r("Test Player","2026-04-01",30,15)]
        cur=[r("Test Player","2026-10-21",35,27)]
        x=trueup(prop(),hist,cur,"2026-10-30")[0]
        self.assertEqual(x["model_certification"],"NOT_CERTIFIED")
        self.assertNotIn("calibrated_probability",x)
    def test_opponent_signal_no_false_precision_with_one_game(self):
        current=[r("Test Player","2026-10-20",32,22)]
        modifier,n=opponent_modifier(current,"IND","points")
        self.assertEqual(modifier,1.0)
if __name__=="__main__":
    unittest.main()
