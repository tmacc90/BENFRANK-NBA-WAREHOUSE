"""Real contract regression tests for source-backed market extension."""
import csv,hashlib,sqlite3,tempfile,unittest
from pathlib import Path

from engine import connect
from benfrank_v49_market_warehouse import stat,MARKETS
from benfrank_v49_source_backfill import backfill

DATA={"game_id":"401999999","athlete_id":"1234","season":"2026","season_type":"2",
      "did_not_play":"false","game_date":"2025-11-12",
      "team_abbreviation":"DEN","athlete_display_name":"Jokić Nikola",
      "points":"19","rebounds":"7","assists":"4","steals":"1",
      "blocks":"1","turnovers":"2","three_point_field_goals_made":"3",
      "field_goals_made":"7","field_goals_attempted":"14",
      "three_point_field_goals_attempted":"6","free_throws_made":"2",
      "free_throws_attempted":"3","offensive_rebounds":"2","defensive_rebounds":"5"}

class RealSourceMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c=connect(":memory:")
        self.addCleanup(self.c.close)
        self.c.execute("INSERT INTO games VALUES ("+",".join("?" for _ in range(15))+")",
            ("Nikola Jokić","2025-11-12","2025-26","DEN","PHX",1,1,32,19,7,4,1,1,2,3))
        self.c.commit()
    def csvfile(self,override=None):
        d={**DATA,**(override or {})}
        p=Path(self.tmp.name)/"box.csv"
        with p.open("w",newline="") as out:
            writer=csv.DictWriter(out,fieldnames=list(d))
            writer.writeheader();writer.writerow(d)
        return {"path":str(p),"year":2026,
                "sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
                "updated_at":"2026-09-09T05:17:39Z"}
    def test_reordered_nickname_exact_safety_and_game_history_immutability(self):
        result=backfill(self.c,[self.csvfile()])
        self.assertEqual(result["expanded_shooting_rows"],1)
        self.assertEqual(result["counts"]["UNIQUE_REVERSED_NAME_MATCHES"],1)
        row=dict(self.c.execute("SELECT g.*,b.fgm,b.fga,b.fg3a,b.ftm,b.fta,b.oreb,b.dreb FROM games g LEFT JOIN market_boxscores b USING(player,date,team)").fetchone())
        self.assertEqual(stat(row,"field_goals_made"),7)
        self.assertEqual(stat(row,"two_point_attempts"),8)
        self.assertEqual(stat(row,"three_pointers_attempted"),6)
        self.assertEqual(stat(row,"fantasy_score"),19+7*1.2+4*1.5+6-2)
        self.assertEqual(result["original_warehouse_game_rows"],1)
        self.assertEqual(result["unmatched_or_conflicted"],0)
    def test_stat_conflict_quarantined_without_filling(self):
        r=backfill(self.c,[self.csvfile({"points":"20"})])
        self.assertEqual(r["expanded_shooting_rows"],0)
        self.assertEqual(r["unmatched_or_conflicted"],1)
    def test_illogical_shooting_components_quarantined(self):
        r=backfill(self.c,[self.csvfile({"field_goals_attempted":"4"})])
        self.assertEqual(r["expanded_shooting_rows"],0)
    def test_hash_mismatch_fails_closed(self):
        source=self.csvfile();source["sha256"]="0"*64
        with self.assertRaises(ValueError):
            backfill(self.c,[source])
    def test_unverified_market_values_null(self):
        self.assertIsNone(stat({"pts":19},"field_goals_made"))
        self.assertIsNone(stat({"pts":19},"two_point_attempts"))
    def test_all_uploaded_market_types_now_registered(self):
        for name in ("points","rebounds","pra","rebounds_assists",
                     "fantasy_score","three_pointers_made",
                     "field_goals_made","two_point_attempts"):
            self.assertIn(name,MARKETS)

if __name__=="__main__":
    unittest.main()
