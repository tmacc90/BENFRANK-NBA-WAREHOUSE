import copy
import datetime as dt
import unittest

from benfrank_omni.contracts import CONTEXT_KEYS, SPORTS, eligible_games, validate_prop
from benfrank_omni.sources import espn_history, espn_stats


def prop(sport="NBA", market="points"):
    return {"sport": sport, "player": "Test Player", "player_id": "123", "market": market,
            "line": 10.5, "opponent": "OPP", "event_id": "target", "event_start_utc": "2025-12-01T20:00:00Z",
            "captured_at_utc": "2025-12-01T12:00:00Z", "line_source": "SOFTWARE_FIXTURE", "scope": "FULL_GAME",
            "rules": {"push": "PUSH", "void": "DNP", **{k: "FIXTURE" for k in CONTEXT_KEYS.get(sport, [])}}}


def games(sport="NBA", market="points", n=60):
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    return [{"sport": sport, "player": "Test Player", "player_id": "123", "game_id": str(i),
             "start_utc": (start + dt.timedelta(days=i)).isoformat(), "season": "2025", "scope": "FULL_GAME", "opponent": "OPP" if i%3 == 0 else "OTHER",
             "stats": {market: i%20}, "workload": 30+i%4, "workload_unit": "TEST_OPPORTUNITIES", "completed": True,
             "context": {k: "FIXTURE" for k in CONTEXT_KEYS.get(sport, [])},
             "source_url": "https://example.org/test", "source_sha256": "a"*64, "retrieved_at_utc": "2025-11-30T12:00:00Z"} for i in range(n)]


CUTOFF = "2025-12-01T18:00:00Z"


class ContractsTest(unittest.TestCase):
    def test_automatic_seasons_use_source_season_not_calendar_year(self):
        class Source:
            def __init__(self):
                self.urls = []
            def get(self, url):
                self.urls.append(url)
                proof = {"source_url": url, "source_sha256": "a"*64, "retrieved_at_utc": CUTOFF}
                if "/gamelog" not in url:
                    return {"athlete": {"id": "123", "displayName": "Test Player"}, "season": {"year": 2027}}, proof
                return {"names": ["points"], "events": {"g": {"gameDate": "2026-11-01T00:00:00Z", "gameResult": "W"}}, "seasonTypes": [{"categories": [{"events": [{"eventId": "g", "stats": ["22"]}]}]}]}, proof
        source = Source()
        espn_history(prop(), {}, source)
        self.assertTrue(any("season=2027" in u for u in source.urls))
        self.assertTrue(any("season=2026" in u for u in source.urls))

    def test_soccer_filter_uses_actual_event_competition_and_extra_time_scope(self):
        class Source:
            def get(self, url):
                proof = {"source_url": url, "source_sha256": "a"*64, "retrieved_at_utc": CUTOFF}
                if "/gamelog" not in url:
                    return {"athlete": {"id": "123", "displayName": "Test Player"}}, proof
                return {"filters": [{"name": "league", "options": [{"displayValue": "UEFA Champions League", "value": "uefa.champions"}]}], "names": ["totalShots"], "events": {"g": {"gameDate": "2025-01-01T00:00:00Z", "leagueName": "UEFA Champions League", "leagueAbbreviation": "UEFA Champions League", "gameResult": "W"}}, "seasonTypes": [{"categories": [{"events": [{"eventId": "g", "stats": ["4"]}]}]}]}, proof
        p = prop("SOCCER", "shots")
        p["rules"].update(competition="eng.1", extra_time="EXCLUDED")
        with self.assertRaisesRegex(ValueError, "NO_COMPLETED_GAMES"):
            espn_history(p, {"seasons": [2025]}, Source())
        p["rules"].update(competition="uefa.champions", extra_time="INCLUDED_IF_PLAYED")
        rows = espn_history(p, {"seasons": [2025]}, Source())
        self.assertEqual(rows[0]["context"]["competition"], "uefa.champions")
        self.assertEqual(rows[0]["context"]["extra_time"], "INCLUDED_IF_PLAYED")

    def test_zero_opportunity_game_is_retained_as_real_zero(self):
        raw = games()
        raw[0]["workload"] = 0
        rows, _ = eligible_games(raw, validate_prop(prop(), CUTOFF, "RESEARCH_REPLAY"), CUTOFF, "RESEARCH_REPLAY")
        self.assertEqual(len(rows), 60)
        self.assertEqual(rows[0]["value"], 0)

    def test_every_catalog_sport_can_use_explicit_normalized_contract(self):
        for sport, spec in SPORTS.items():
            p = validate_prop(prop(sport, spec["markets"][0]), CUTOFF, "SOFTWARE_TEST")
            rows, rejected = eligible_games(games(sport, spec["markets"][0]), p, CUTOFF, "SOFTWARE_TEST")
            self.assertEqual(len(rows), 60)
            self.assertFalse(rejected)

    def test_target_future_wrong_player_and_wrong_sport_are_never_training(self):
        p = validate_prop(prop(), CUTOFF, "RESEARCH_REPLAY")
        raw = games()
        raw += [{**raw[0], "game_id": "target"}, {**raw[1], "sport": "WNBA"}, {**raw[2], "player_id": "456"}, {**raw[3], "start_utc": "2026-01-01T00:00:00Z"}]
        rows, rejected = eligible_games(raw, p, CUTOFF, "RESEARCH_REPLAY")
        self.assertEqual(len(rows), 60)
        self.assertEqual(len(rejected), 4)

    def test_conflicting_duplicate_fails_instead_of_choosing_one_source(self):
        raw = games()
        raw.append({**raw[0], "stats": {"points": 999}})
        with self.assertRaisesRegex(ValueError, "CONFLICTING_DUPLICATE"):
            eligible_games(raw, validate_prop(prop(), CUTOFF, "RESEARCH_REPLAY"), CUTOFF, "RESEARCH_REPLAY")

    def test_map_scope_patch_and_scoring_are_required(self):
        p = prop("CS2", "kills")
        p["rules"].pop("patch")
        with self.assertRaisesRegex(ValueError, "SPORT_RULE_REQUIRED"):
            validate_prop(p, CUTOFF, "RESEARCH_REPLAY")
        p = prop("NBA", "fantasy_score")
        with self.assertRaisesRegex(ValueError, "SCORING"):
            validate_prop(p, CUTOFF, "RESEARCH_REPLAY")
        p = prop()
        p["scope"] = "FIRST_HALF"
        with self.assertRaisesRegex(ValueError, "EIGHT_COMPARABLE"):
            eligible_games(games(), validate_prop(p, CUTOFF, "RESEARCH_REPLAY"), CUTOFF, "RESEARCH_REPLAY")

    def test_actual_game_log_labels_and_baseball_outs(self):
        s = espn_stats(["minutes", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "points"], ["31:30", "4-9", "--"], "NBA")
        self.assertEqual(s["minutes"], 31.5)
        self.assertEqual(s["threes"], 4)
        self.assertNotIn("points", s)
        s = espn_stats(["innings", "strikeouts"], ["5.2", "7"], "MLB", "pitcher")
        self.assertEqual(s["outs"], 17)
        self.assertEqual(s["pitcher_strikeouts"], 7)

    def test_tournament_date_never_implies_match_was_already_finished(self):
        raw = games()
        raw[0]["available_after_utc"] = "2026-01-01T00:00:00Z"
        rows, rejected = eligible_games(raw, validate_prop(prop(), CUTOFF, "RESEARCH_REPLAY"), CUTOFF, "RESEARCH_REPLAY")
        self.assertEqual(len(rows), 59)
        self.assertIn("DATE_PRECISION", rejected[0]["reason"])

    def test_future_capture_unknown_sport_and_stale_lines_rejected(self):
        for changes in ({"sport": "FAKE"}, {"line": float("nan")}, {"captured_at_utc": "2025-12-02T12:00:00Z"}, {"captured_at_utc": "2025-11-01T12:00:00Z"}):
            with self.assertRaises(ValueError):
                validate_prop({**prop(), **changes}, CUTOFF, "RESEARCH_REPLAY")


if __name__ == "__main__":
    unittest.main()
