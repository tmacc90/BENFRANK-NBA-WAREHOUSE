import unittest
from engine import connect
from benfrank_v44_shots import parse_attempts,stage_attempts

class ShotStageTests(unittest.TestCase):
    def test_scoring_conservation(self):
        x=parse_attempts("7-15","2-6","1-2",17)
        self.assertEqual((x["fg2m"],x["fg2a"]),(5,9))
        self.assertEqual(x["fg3a"],6)
        self.assertEqual(x["fta"],2)
    def test_inconsistent_points_rejected(self):
        with self.assertRaises(ValueError):
            parse_attempts("7-15","2-6","1-2",18)
    def test_additive_secondary_shots(self):
        c=connect(":memory:")
        row={"source_game_id":"1","date":"2026-10-29","team":"BOS",
             "player":"Test Player","fga":15,"fgm":7,"fg2a":9,"fg2m":5,
             "fg3a":6,"fg3m":2,"fta":2,"ftm":1,"minutes":31.5,
             "source_body_sha":"a"*64,"retrieved_at":"2026-10-29T22:00:00Z"}
        first=stage_attempts(c,[row])
        second=stage_attempts(c,[row])
        self.assertEqual(first["staged"],1)
        self.assertEqual(second["staged"],0)
        self.assertEqual(c.execute("SELECT verified_official FROM player_shot_attempts").fetchone()[0],0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM games").fetchone()[0],0)
        c.close()

if __name__=="__main__":
    unittest.main()
