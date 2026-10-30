import tempfile
import unittest
import zipfile
from pathlib import Path
from benfrank_v47_saved_history_ci import verified_extract,audit_archive

class SavedOfficialArchiveSafetyTests(unittest.TestCase):
    def make_zip(self,entries):
        td=tempfile.TemporaryDirectory()
        path=Path(td.name)/"archive.zip"
        with zipfile.ZipFile(path,"w") as z:
            for key,value in entries.items():
                z.writestr(key,value)
        self.addCleanup(td.cleanup)
        return path
    def test_rejects_path_traversal(self):
        z=self.make_zip({"../sneaky":"x"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                verified_extract(z,d)
    def test_missing_official_receipts_fails(self):
        z=self.make_zip({"DELIVERY_MANIFEST.json":"{}"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                verified_extract(z,d)
    def test_pin_required(self):
        z=self.make_zip({"DELIVERY_MANIFEST.json":"{}"})
        with self.assertRaises(ValueError):
            audit_archive(z,"wrong")
    def test_missing_archive_fails(self):
        with self.assertRaises(FileNotFoundError):
            audit_archive("/missing.zip","a"*64)

if __name__=="__main__":
    unittest.main()
