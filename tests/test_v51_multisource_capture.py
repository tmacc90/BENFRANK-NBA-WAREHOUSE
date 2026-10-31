"""Source adapter tests: HTTP outages and missing evidence never certify data."""
import json
import tempfile
import unittest
from pathlib import Path

from benfrank_v51_multisource_capture import capture,run,validate_url

class MultiSourceCaptureTests(unittest.TestCase):
    def test_enforces_exact_https_provider_host(self):
        self.assertEqual(validate_url("https://cdn.nba.com/data.json","cdn.nba.com"),
                         "https://cdn.nba.com/data.json")
        for url in ("http://cdn.nba.com/x","https://example.com/x",
                    "https://cdn.nba.com.evil.tld/x","https://u:p@cdn.nba.com/x"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_url(url,"cdn.nba.com")
    def test_success_is_raw_snapshot_not_certification(self):
        with tempfile.TemporaryDirectory() as d:
            def fake(url,n):
                return 200,"application/json",b'{"leagues":[]}'
            r=capture("espn_teams","2026-10-30",d,fetch=fake)
            self.assertEqual(r["status"],"CAPTURED_UNVERIFIED")
            self.assertFalse(r["certified"])
            self.assertEqual(json.loads((Path(d)/r["raw_file"]).read_text()),{"leagues":[]})
    def test_http_403_and_429_fail_closed(self):
        for status in (403,429):
            with tempfile.TemporaryDirectory() as d:
                r=capture("nba_cdn_schedule","2026-10-30",d,
                          fetch=lambda url,n:(status,"application/json",b'{}'))
                self.assertEqual(r["status"],"BLOCKED")
                self.assertIsNone(r["sha256"])
    def test_fake_html_200_is_not_valid_json_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            r=capture("espn_injuries","2026-10-30",d,
                      fetch=lambda url,n:(200,"text/html",b"<h1>error</h1>"))
            self.assertEqual(r["status"],"BLOCKED")
    def test_source_capture_cannot_claim_final_lineups(self):
        with tempfile.TemporaryDirectory() as d:
            r=run("2026-10-30",d,["espn_injuries","nba_cdn_scoreboard"],
                  fetch=lambda url,n:(200,"application/json",b'{"value":true}'))
            self.assertEqual(r["captured"],2)
            self.assertFalse(r["final_lineup_confirmed"])
            self.assertFalse(r["authenticated_native_prop_lines"])
            self.assertEqual(r["ticket_authority"],"NO_TICKET")
if __name__=="__main__":
    unittest.main()
