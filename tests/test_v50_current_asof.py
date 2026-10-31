"""As-of ESPN collector contracts. Fixtures are tests, never production stats."""
import unittest
from benfrank_v50_current_asof import collect,validate_row
class CurrentAsOfTests(unittest.TestCase):
    def row(self,date="2026-10-29"):
        return {
            "player":"Test Player","date":date,"season":"2026-27",
            "team":"IND","opponent":"MIA","home":0,"starter":True,
            "minutes":30.0,"pts":21,"reb":6,"ast":7,"stl":1,"blk":0,"tov":2,
            "fg3m":3,"fgm":8,"fga":15,"fg3a":6,"ftm":2,"fta":3,
            "source_game_id":"401900000","source_body_sha":"a"*64,
            "retrieved_at":"2026-10-30T00:00:00Z"
        }
    def test_conservation_and_lookahead(self):
        validate_row(self.row(),"2026-10-30")
        with self.assertRaisesRegex(ValueError,"LOOKAHEAD"):
            validate_row(self.row("2026-10-30"),"2026-10-30")
        with self.assertRaisesRegex(ValueError,"LOOKAHEAD"):
            validate_row(self.row("2026-10-31"),"2026-10-30")
    def test_inconsistent_shots_rejected(self):
        r=self.row();r["pts"]=24
        with self.assertRaisesRegex(ValueError,"SHOOTING_COMPONENTS"):
            validate_row(r,"2026-10-30")
    def test_negative_and_missing_shots_not_imputed(self):
        for key in ("fgm","fga","fg3a"):
            r=self.row();r.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_row(r,"2026-10-30")
    def test_only_completed_previous_games_accepted(self):
        def fake(day,max_events=20):
            return {"status":"PARSED_UNVERIFIED",
                    "events":[{"event_id":"401900000","status":"PARSED_UNVERIFIED"}],
                    "staged_rows":[self.row(day)]}
        rows,rec=collect("2026-10-30",days=2,fetcher=fake)
        self.assertEqual(len(rows),2)
        self.assertEqual(rec["strict_history_through"],"2026-10-29")
        self.assertEqual(rec["official_verified"],False)
        self.assertEqual(rec["ticket_authority"],"NO_TICKET")
    def test_missing_source_is_recorded(self):
        def fake(day,max_events=20):
            return {"status":"SUMMARY_UNAVAILABLE","staged_rows":[]}
        rows,rec=collect("2026-10-30",1,fake)
        self.assertEqual(rows,[])
        self.assertEqual(len(rec["retrieval_issues"]),1)
        self.assertFalse(rec["official_verified"])
if __name__=="__main__":
    unittest.main()
