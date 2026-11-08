import unittest
from benfrank_v52_early import apply_lineup_evidence

class TestLineupEvidenceAdjustment(unittest.TestCase):
    def base_context(self, quality="FULL"):
        return {
            "rosters": {
                "LAL": [{
                    "player": "Target Player",
                    "minutes_mean": 32.0,
                    "fg2a_per36": 12.0,
                    "fg3a_per36": 6.0,
                    "fta_per36": 5.0,
                    "ast_per36": 6.0,
                    "reb_per36": 8.0,
                }]
            },
            "early_role_evidence": {
                "LAL": {
                    "selected_projected_five": [
                        "Target Player", "Mate One", "Mate Two", "Mate Three", "Mate Four"
                    ],
                    "depth_derived_five": [],
                }
            },
            "lineup_evidence": {
                "quality": quality,
                "target": {"closing_share": 1.0},
                "teammates": {
                    "2": {
                        "name": "Mate One", "possessions_with": 180,
                        "fga_ratio_shrunk": 1.20, "ast_ratio_shrunk": 0.80,
                        "reb_ratio_shrunk": 1.15,
                    },
                    "3": {
                        "name": "Mate Two", "possessions_with": 120,
                        "fga_ratio_shrunk": 1.15, "ast_ratio_shrunk": 0.90,
                        "reb_ratio_shrunk": 1.10,
                    },
                },
            },
            "limitations": [],
        }

    def test_full_evidence_is_bounded_and_correlated(self):
        ctx = self.base_context("FULL")
        before = ctx["rosters"]["LAL"][0].copy()
        out = apply_lineup_evidence(ctx, {"team":"LAL","player":"Target Player","market":"pra"})
        target = out["rosters"]["LAL"][0]
        rec = out["lineup_evidence_adjustment"]
        self.assertTrue(rec["applied"])
        self.assertFalse(rec["confidence_vote_allowed"])
        self.assertEqual(rec["independence_family"], "LINEUP_PBP_CORRELATED_WITH_ROLE_OPPORTUNITY")
        self.assertLessEqual(target["fg2a_per36"] / before["fg2a_per36"], 1.08)
        self.assertGreaterEqual(target["ast_per36"] / before["ast_per36"], 0.92)
        self.assertLessEqual(abs(rec["minutes_delta"]), 1.5)

    def test_limited_evidence_does_not_change_model(self):
        ctx = self.base_context("LIMITED")
        before = dict(ctx["rosters"]["LAL"][0])
        out = apply_lineup_evidence(ctx, {"team":"LAL","player":"Target Player","market":"points"})
        self.assertEqual(out["rosters"]["LAL"][0], before)
        self.assertFalse(out["lineup_evidence_adjustment"]["applied"])

if __name__ == "__main__":
    unittest.main()
