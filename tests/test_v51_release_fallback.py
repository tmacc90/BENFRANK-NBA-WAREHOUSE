"""2027 release mirror fallback preserves provenance and blocks post-target data."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from benfrank_v51_release_fallback import (
    BASE,REPOSITORY,capture,date_asof,httpget,identify_asset,qualify_asof
)

class PublicMirrorSafetyTests(unittest.TestCase):
    def sample(self,include_date=True):
        import pyarrow as pa
        import pyarrow.parquet as pq
        table=pa.table({"game_date":["2026-10-28","2026-10-30","2026-10-29"],
                        "shot_distance":[8,12,18]} if include_date
                       else {"game_id":["0022600001","0022600002"],"points":[3,2]})
        buffer=pa.BufferOutputStream()
        pq.write_table(table,buffer)
        return buffer.getvalue().to_pybytes()
    def test_future_result_is_filtered_out_of_pregame_feature(self):
        with tempfile.TemporaryDirectory() as d:
            report=qualify_asof(self.sample(),"2026-10-30",Path(d)/"safe.parquet")
            self.assertEqual(report["raw_rows"],3)
            self.assertEqual(report["rows_before_cutoff"],2)
            self.assertTrue((Path(d)/"safe.parquet").exists())
    def test_without_game_date_never_assume_future_free(self):
        with tempfile.TemporaryDirectory() as d:
            report=qualify_asof(self.sample(False),"2026-10-30",Path(d)/"safe.parquet")
            self.assertEqual(report["rows_before_cutoff"],0)
            self.assertEqual(report["status"],"NO_ROW_DATE_CANNOT_USE_AS_PREGAME_FEATURE")
            self.assertFalse((Path(d)/"safe.parquet").exists())
    def test_release_must_be_exact_allowlisted_name_and_url(self):
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_RELEASE_ASSET_URL"):
            identify_asset("espn_nba_shots",{"assets":[{"name":"shots_2027.parquet",
                "size":1000,"browser_download_url":"https://example.com/unsafe"}]})
    def test_403_not_silently_promoted_to_official(self):
        with self.assertRaisesRegex(ValueError,"UNAVAILABLE"):
            httpget(BASE+"espn_nba_shots",github_api=True,
                    fetch=lambda url,size:(403,url,b"error"))
    def test_real_parquet_release_asof_is_not_direct_official(self):
        raw=self.sample()
        tag="espn_nba_shots"
        filename="shots_2027.parquet"
        asset_url="https://github.com/"+REPOSITORY+"/releases/download/"+tag+"/"+filename
        metadata=json.dumps({"assets":[{"name":filename,"size":len(raw),
            "browser_download_url":asset_url,"id":1,
            "updated_at":"2026-10-30T12:04:58Z"}]}).encode()
        def fetch(url,size):
            return 200,url,metadata if url==BASE+tag else raw
        with tempfile.TemporaryDirectory() as d:
            result=capture(tag,"2026-10-30",d,fetch=fetch)
            self.assertEqual(result["status"],"CAPTURED_MIRROR_ASOF_FILTERED")
            self.assertEqual(result["quality"]["rows_before_cutoff"],2)
            self.assertFalse(result["official_direct_fetch"])
            self.assertFalse(result["historical_prop_snapshot_authenticated"])
if __name__=="__main__":
    unittest.main()
