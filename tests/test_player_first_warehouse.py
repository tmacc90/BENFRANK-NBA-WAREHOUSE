import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from benfrank_player_first_warehouse import connect, ingest, l52

class PlayerFirstWarehouseTests(unittest.TestCase):
    def test_exact_line_and_no_future_games(self):
        with tempfile.TemporaryDirectory() as d:
            db=connect(str(Path(d)/"games.sqlite"))
            raw=b'{"verified_source_fixture":true}'
            sha=hashlib.sha256(raw).hexdigest()
            url="https://site.api.espn.com/test"
            db.execute("INSERT INTO raw_sources VALUES(?,?,?,?)",
                       (sha,url,"2026-11-05T00:00:00Z",raw))
            records=[]
            for i in range(55):
                records.append(dict(player_id="1",game_id=str(i),
                    game_date="2026-10-"+str(i%28+1).zfill(2),
                    team="LAL",opponent="POR",minutes=30,
                    points=20,rebounds=5,three_pm=5 if i%2 else 3,
                    source_sha256=sha,source_url=url))
            ingest(db,records)
            report=l52(db,"1","3PM",4.5,"2026-11-06")
            self.assertEqual(report["windows"]["L52"]["available"],52)
            self.assertEqual(report["windows"]["L52"]["over"]+
                             report["windows"]["L52"]["under"],52)
            db.close()

    def test_no_fake_completeness(self):
        with tempfile.TemporaryDirectory() as d:
            db=connect(str(Path(d)/"empty.sqlite"))
            report=l52(db,"1","PTS",25.5,"2026-11-06")
            self.assertFalse(report["l52_complete"])
            self.assertEqual(report["windows"]["L52"]["available"],0)
            db.close()

if __name__=="__main__":
    unittest.main()
