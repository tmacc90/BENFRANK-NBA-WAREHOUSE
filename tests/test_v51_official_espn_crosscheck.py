"""NBA-vs-ESPN complete-game source reconciliation is independent of bets."""
import copy
import unittest
from benfrank_v51_official_espn_crosscheck import match
SHOOT=dict(pts=20,reb=7,ast=8,stl=1,blk=0,tov=2,fg3m=2,
           fgm=8,fga=15,fg3a=5,ftm=2,fta=3)
def nba(name="Nikola Jokić"):
    return dict(SHOOT,player=name,game_id="0022600123",person_id="203999",
                game_date="2026-10-29",team="DEN",opponent="PHX",
                minutes=33.0,box_sha256="a"*64)
def espn(name="Nikola Jokic"):
    return dict(SHOOT,player=name,source_game_id="401900001",
                date="2026-10-29",team="DEN",opponent="PHX",
                minutes=33.0,source_body_sha="b"*64)
class TwoSourceTests(unittest.TestCase):
    def test_accents_dont_create_missing_player_identity(self):
        good,bad=match([nba()],[espn()])
        self.assertEqual(len(good),1)
        self.assertEqual(bad,[])
        self.assertEqual(good[0]["identity_method"],"EXACT_ACCENT_PUNCTUATION")
    def test_reverse_token_only_with_unique_player(self):
        good,bad=match([nba("Hansen Yang")],[espn("Yang Hansen")])
        self.assertEqual(len(good),1)
        self.assertEqual(good[0]["identity_method"],"UNIQUE_EXACT_NAME_TOKEN_ORDER")
    def test_same_name_conflicting_points_quarantined(self):
        x=espn();x["pts"]=19
        good,bad=match([nba()],[x])
        self.assertEqual(good,[])
        self.assertEqual(bad[0]["reason"],"COUNTING_STATS_DIFFER")
        self.assertIn("pts",bad[0]["fields"])
    def test_no_guessing_unrelated_name(self):
        good,bad=match([nba()],[espn("Different Player")])
        self.assertEqual(good,[])
        self.assertEqual(bad[0]["reason"],"ESPN_IDENTITY_MISSING_OR_AMBIGUOUS")
    def test_ambiguous_name_never_certified(self):
        other=espn();other["source_game_id"]="401900002"
        good,bad=match([nba()],[espn(),other])
        self.assertEqual(good,[])
        self.assertEqual(bad[0]["reason"],"ESPN_IDENTITY_MISSING_OR_AMBIGUOUS")
if __name__=="__main__":
    unittest.main()
