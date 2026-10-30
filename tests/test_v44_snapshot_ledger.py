import sqlite3
import unittest
from benfrank_v44_snapshot_ledger import ingest,export

class SnapshotLedgerTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(":memory:")
        self.prop={"player":"Sample Player","market":"points","line":25.5,"opponent":"BOS",
                   "game_date":"2026-10-29","platform":"PrizePicks","snapshot_id":"board-a",
                   "captured_at":"2026-10-29T12:00:00Z",
                   "tipoff_utc":"2026-10-29T23:00:00Z","source_type":"SCREENSHOT_CAPTURE"}
    def tearDown(self):
        self.c.close()
    def test_idempotent(self):
        a=ingest(self.c,[self.prop])
        b=ingest(self.c,[self.prop])
        self.assertEqual(a["inserted"],1)
        self.assertEqual(b["idempotent"],1)
        self.assertEqual(len(export(self.c)),1)
    def test_moved_line_requires_new_snapshot(self):
        ingest(self.c,[self.prop])
        with self.assertRaises(ValueError):
            ingest(self.c,[{**self.prop,"line":26.5}])
    def test_after_tipoff_rejected(self):
        bad={**self.prop,"captured_at":"2026-10-30T00:00:00Z"}
        with self.assertRaises(ValueError):
            ingest(self.c,[bad])
    def test_export_preserves_line(self):
        ingest(self.c,[self.prop])
        self.assertEqual(export(self.c)[0]["line"],25.5)

if __name__=="__main__":
    unittest.main()
