import json
import tempfile
import unittest
from pathlib import Path
from benfrank_version_isolation import verify_release, check_lock_change, VersionIsolationError, LOCK

class VersionIsolationTests(unittest.TestCase):
    def test_unreleased_sports_fail_closed(self):
        for sport in ("NBA","NFL","TENNIS","NHL","SOCCER","COD","CS2","MLB","WNBA",
                      "NCAAB","CFB","MMA","GOLF","DOTA2","LOL","VALORANT","F1","BOXING","TABLETENNIS"):
            with self.assertRaisesRegex(VersionIsolationError,"NOT_APPROVED"):
                verify_release(sport, {"sport":sport})
    def test_unknown_sport_rejected(self):
        with self.assertRaisesRegex(VersionIsolationError,"UNKNOWN_SPORT"):
            verify_release("RUGBY", {})
    def test_independent_change_requires_approval(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"lock.json"
            data=json.loads(LOCK.read_text())
            data["sports"]["NFL"]["model_version"]="1.0.0"
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(VersionIsolationError,"UNAPPROVED_SPORT"):
                check_lock_change(LOCK,p)
            self.assertTrue(check_lock_change(LOCK,p,approved_sports={"NFL"}))
    def test_cross_sport_receipt_fails_even_with_matching_versions(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"lock.json"
            data=json.loads(LOCK.read_text())
            spec=data["sports"]["NFL"]
            spec["release_status"]="OPERATIONAL"
            spec["approved_core_sha256"]="a"*64
            spec["approved_model_sha256"]="b"*64
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(VersionIsolationError,"CROSS_SPORT"):
                verify_release("NFL",{"sport":"NBA"},lock_path=p)
    def test_pinned_versions_must_match(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"lock.json"
            data=json.loads(LOCK.read_text())
            spec=data["sports"]["NFL"]
            spec["release_status"]="OPERATIONAL"
            spec["approved_core_sha256"]="a"*64
            spec["approved_model_sha256"]="b"*64
            p.write_text(json.dumps(data))
            with self.assertRaisesRegex(VersionIsolationError,"VERSION_LOCK_MISMATCH"):
                verify_release("NFL",{"sport":"NFL","core_version":"wrong"},lock_path=p)

if __name__=="__main__": unittest.main()
