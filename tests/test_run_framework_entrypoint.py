import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from run_framework import execute

class RunFrameworkTest(unittest.TestCase):
    def test_research_writes_report_and_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"input.json"
            source.write_text(json.dumps({"cutoff_utc":"2026-11-03T18:00:00Z",
              "props":[{"player":"Sample Player","market":"points","line":20.5,
                "current_season":"2026-27","previous_season":"2025-26",
                "games":[{"sport":"NBA","player":"Sample Player","market":"points",
                  "stat":22,"game_utc":"2026-10-30T18:00:00Z",
                  "game_id":"test-game-1","source":"https://example.org/test",
                  "season":"2026-27"}]}]}))
            output=root/"run"
            self.assertEqual(execute(SimpleNamespace(input=str(source),config=None,output=str(output))),0)
            self.assertTrue((output/"report.md").exists())
            receipt=json.loads((output/"execution_receipt.json").read_text())
            self.assertFalse(receipt["physical_simulations_verified"])
            self.assertEqual(receipt["props"],1)
            with self.assertRaises(FileExistsError):
                execute(SimpleNamespace(input=str(source),config=None,output=str(output)))

if __name__=="__main__": unittest.main()
