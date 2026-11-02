import unittest
from benfrank_multisport_router import resolve_sport,verify_prediction_route

class IsolationTests(unittest.TestCase):
    def test_all_19_sports_registered_and_unverified(self):
        for key in ("NBA","NFL","TENNIS","NHL","SOCCER","COD","CS2","MLB","WNBA",
                    "NCAAB","CFB","MMA","GOLF","DOTA2","LOL","VALORANT","F1","BOXING","TABLETENNIS"):
            result=resolve_sport(key)
            self.assertFalse(result["may_predict"])
    def test_unknown_sport_never_defaults_to_nba(self):
        with self.assertRaisesRegex(ValueError,"UNKNOWN_SPORT"):
            resolve_sport("UNKNOWN")
    def test_cross_sport_model_rejected(self):
        with self.assertRaisesRegex(ValueError,"CROSS_SPORT"):
            verify_prediction_route("NFL","NBA","BENFRANK_NBA_MODEL","BENFRANK_NBA_LEDGER")
    def test_matching_identity_only(self):
        self.assertTrue(verify_prediction_route("NHL","NHL","BENFRANK_NHL_MODEL","BENFRANK_NHL_LEDGER"))
if __name__=="__main__":unittest.main()
