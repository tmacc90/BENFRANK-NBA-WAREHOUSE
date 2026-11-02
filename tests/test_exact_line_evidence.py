import unittest
from benfrank_exact_line_evidence import analyze_exact_line,rank_scanned_props

BASE=dict(sport="NBA",player="Example",market="points",line=20.5,
          cutoff_utc="2026-11-01T23:00:00Z",current_season="2026",previous_season="2025")
def game(n,stat):
    return dict(sport="NBA",player="Example",market="points",game_id=str(n),
                game_utc=f"2026-10-{n:02d}T20:00:00Z",season="2026",
                stat=stat,source="official_box_score",features={"workload":0.8})
class ExactLineTests(unittest.TestCase):
    def test_windows_both_sides_and_analog(self):
        x=analyze_exact_line(**BASE,games=[game(1,21),game(2,19),game(3,21)],
                             current_features={"workload":0.8})
        self.assertEqual(x["windows"]["L5"]["over"],2)
        self.assertEqual(x["windows"]["L5"]["under"],1)
        self.assertEqual(len(x["matched_analogs"]),3)
    def test_cutoff_rejected(self):
        g=game(1,22);g["game_utc"]="2026-11-02T00:00:00Z"
        with self.assertRaisesRegex(ValueError,"LEAKAGE"):
            analyze_exact_line(**BASE,games=[g])
    def test_cross_sport_rejected(self):
        g=game(1,22);g["sport"]="NFL"
        with self.assertRaisesRegex(ValueError,"CROSS_SPORT"):
            analyze_exact_line(**BASE,games=[g])
    def test_no_fake_probabilities(self):
        x=analyze_exact_line(**BASE,games=[game(1,22)])
        self.assertNotIn("win_probability",x)
    def test_scanner_requires_calibration_and_edge(self):
        x=[dict(id="a",calibration_verified=True,source_verified=True,calibrated_win_probability=.61,break_even_probability=.55),
           dict(id="b",calibration_verified=False,source_verified=True,calibrated_win_probability=.99,break_even_probability=.55)]
        self.assertEqual([p["id"] for p in rank_scanned_props(x,2)],["a"])
if __name__=="__main__":unittest.main()
