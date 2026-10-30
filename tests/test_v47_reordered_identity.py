"""Cross-source player-name order repairs: unique only, never fuzzy guessing."""
import copy
import json
import unittest

from acquire_history import migrate,name_key,name_token_signature,reconcile
from engine import connect

class NameOrderProofTests(unittest.TestCase):
    def setUp(self):
        self.c=connect(":memory:")
        migrate(self.c)
        self.nba=[]
        self.espn=[]
        for i in range(5):
            first,last=("Hansen","Yang") if i==0 else ("Test",str(i))
            self.nba.append(dict(game_id="0022500001",season=2026,season_type_id="2",
                team_id=1610612757,team_tricode="POR",person_id=100+i,
                first_name=first,family_name=last,position="F",
                side="home",minutes="22:30",points=9,rebounds_total=4,
                assists=2,steals=1,blocks=0,turnovers=1,three_pointers_made=1))
            self.espn.append(dict(game_id="401900001",season="2026",season_type="2",
                game_date="2025-11-12",athlete_id=str(1000+i),
                athlete_display_name=("Yang Hansen" if i==0 else f"Test {i}"),
                team_abbreviation="POR",opponent_team_abbreviation="SAS",
                home_away="home",starter="true",did_not_play="false",
                minutes="22.5",points="9",rebounds="4",assists="2",steals="1",
                blocks="0",turnovers="1",three_point_field_goals_made="1",
                team_score="105",opponent_team_score="98"))
        self.schedule=[dict(game_id="0022500001",season=2026,season_type_id="2",
            game_status=3,home_team_id=1610612757,away_team_id=1610612759,
            home_team_tricode="POR",away_team_tricode="SAS",
            game_date_est="2025-11-12T00:00:00Z",
            home_team_score=105,away_team_score=98)]
        self.nm={"actual_sha256":"a"*64}
        self.em={"actual_sha256":"b"*64}
    def tearDown(self):
        self.c.close()
    def run_import(self):
        return reconcile(self.c,self.nba,self.espn,self.schedule,2026,self.nm,self.em)
    def test_name_order_exact_unique_match_accepted(self):
        self.assertNotEqual(name_key("Hansen Yang"),name_key("Yang Hansen"))
        self.assertEqual(name_token_signature("Hansen Yang"),name_token_signature("Yang Hansen"))
        result=self.run_import()
        self.assertEqual(result["crosschecked_player_games"],5)
        self.assertEqual(result["approved_unique_reordered_name_matches"],1)
        row=self.c.execute("SELECT check_detail_json FROM game_verifications WHERE player='Hansen Yang'").fetchone()
        self.assertEqual(json.loads(row[0])["identity_method"],"UNIQUE_NAME_TOKEN_PERMUTATION")
    def test_two_token_order_matches_remain_ambiguous(self):
        copy_row=copy.deepcopy(self.espn[0])
        copy_row["athlete_id"]="different-espn-id"
        self.espn.append(copy_row)
        result=self.run_import()
        self.assertEqual(result["crosschecked_player_games"],4)
        self.assertEqual(result["approved_unique_reordered_name_matches"],0)
    def test_source_stat_disagreement_is_never_overridden(self):
        self.espn[0]["points"]="10"
        result=self.run_import()
        self.assertEqual(result["crosschecked_player_games"],4)
        self.assertTrue(any(x["code"]=="CROSS_SOURCE_CONFLICT" for x in result["failures"]))
    def test_nickname_or_unrelated_name_is_not_guessed(self):
        self.espn[0]["athlete_display_name"]="Somebody Else"
        result=self.run_import()
        self.assertEqual(result["crosschecked_player_games"],4)
    def test_incomplete_name_cannot_match(self):
        self.assertEqual(name_token_signature("Hansen"),())
if __name__=="__main__":
    unittest.main()
