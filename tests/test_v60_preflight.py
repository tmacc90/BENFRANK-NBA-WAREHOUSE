import json
import tempfile
import unittest
from pathlib import Path
from benfrank_v60_preflight import preflight

class PreflightTests(unittest.TestCase):
    def test_missing_inputs_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"config.json"
            p.write_text("{}")
            r=preflight(p)
            self.assertEqual(r["status"],"BLOCKED")
            self.assertEqual(len(r["missing"]),4)
    def test_empty_board_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"board.json").write_text("[]")
            (root/"config.json").write_text(json.dumps({"board":"board.json"}))
            r=preflight(root/"config.json")
            self.assertIn("EMPTY_OR_INVALID_BOARD",r["missing"])
    def test_no_certification_from_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"config.json";p.write_text("{}")
            r=preflight(p)
            self.assertFalse(r["source_certified"])
            self.assertFalse(r["full_execution_verified"])
if __name__=="__main__":unittest.main()
