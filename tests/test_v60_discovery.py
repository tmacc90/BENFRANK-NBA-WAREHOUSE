import unittest
from benfrank_v60_discovery import normalize

BASE={"player":"Example Player","market":"PTS","line":22.5,"team":"AAA",
      "opponent":"BBB","game_date":"2026-11-02",
      "tipoff_utc":"2026-11-03T00:00:00Z","source":"PUBLIC_URL",
      "captured_at_utc":"2026-11-02T12:00:00Z"}
CUTOFF="2026-11-02T13:00:00Z"

class DiscoveryTests(unittest.TestCase):
    def test_accept_and_normalize(self):
        r=normalize([BASE],cutoff_utc=CUTOFF)
        self.assertEqual(len(r["board"]),1)
        self.assertEqual(r["board"][0]["market"],"points")
        self.assertFalse(r["certified_live_board"])
    def test_stale_rejected(self):
        row=dict(BASE,captured_at_utc="2026-10-31T12:00:00Z")
        self.assertEqual(normalize([row],cutoff_utc=CUTOFF)["rejected"][0]["reason"],"STALE_LINE")
    def test_after_tipoff_rejected(self):
        row=dict(BASE,tipoff_utc="2026-11-02T12:00:00Z")
        self.assertEqual(normalize([row],cutoff_utc=CUTOFF)["rejected"][0]["reason"],"NOT_PREGAME")
    def test_duplicate_rejected(self):
        r=normalize([BASE,BASE],cutoff_utc=CUTOFF)
        self.assertEqual(len(r["board"]),1)
        self.assertEqual(len(r["rejected"]),1)
    def test_no_timezone_rejected(self):
        row=dict(BASE,captured_at_utc="2026-11-02T12:00:00")
        self.assertEqual(normalize([row],cutoff_utc=CUTOFF)["rejected"][0]["reason"],"TIMEZONE_REQUIRED")
if __name__=="__main__":
    unittest.main()
