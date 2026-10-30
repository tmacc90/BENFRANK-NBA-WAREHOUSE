import io
import json
import unittest
from nba_live_probe import attempt, normalize_espn, normalize_nba

class FakeResponse:
    def __init__(self, value):
        self.raw = json.dumps(value).encode()
        self.status = 200
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def read(self, limit):
        return self.raw[:limit]

def fake(value):
    return lambda req, timeout=15: FakeResponse(value)

class ProbeTests(unittest.TestCase):
    def test_official_normalize(self):
        d={"scoreboard":{"gameDate":"2026-10-29","games":[{"gameId":"0022600123","homeTeam":{"teamTricode":"BOS"},"awayTeam":{"teamTricode":"NYK"},"gameStatus":1}]}}
        a=attempt("NBA_OFFICIAL","https://example.invalid","2026-10-29",opener=fake(d))
        self.assertEqual(a["status"],"AVAILABLE")
        self.assertEqual(a["game_count"],1)
        b=attempt("NBA_OFFICIAL","https://example.invalid","2026-10-28",opener=fake(d))
        self.assertEqual(b["status"],"DATE_MISMATCH")
    def test_no_fabricated_nba_games(self):
        with self.assertRaises(ValueError):
            normalize_nba({"scoreboard":{"gameDate":"2026-10-29"}})
    def test_espn_is_secondary(self):
        payload={"events":[{"id":"401234","date":"2026-10-29T23:00Z",
                 "competitions":[{"competitors":[
                   {"homeAway":"home","team":{"abbreviation":"BOS"}},
                   {"homeAway":"away","team":{"abbreviation":"NYK"}}]}]}]}
        a=attempt("ESPN_SECONDARY","https://example.invalid","2026-10-29",opener=fake(payload))
        self.assertEqual(a["status"],"AVAILABLE")
        self.assertEqual(a["games"][0]["home"],"BOS")
    def test_provider_error_is_unavailable(self):
        def err(req,timeout=15):
            raise TimeoutError("blocked")
        a=attempt("NBA_OFFICIAL","https://example.invalid","2026-10-29",opener=err)
        self.assertEqual(a["status"],"UNAVAILABLE")
        self.assertEqual(a["game_count"],None)

if __name__=='__main__':
    unittest.main()
