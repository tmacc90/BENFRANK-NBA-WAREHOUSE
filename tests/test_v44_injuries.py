import json
import unittest
from benfrank_v44_injuries import normalize,fetch

class Response:
    def __init__(self,data):
        self.data=json.dumps(data).encode()
        self.status=200
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def read(self,n):
        return self.data[:n]

class InjuryTests(unittest.TestCase):
    def test_nested_schema(self):
        data={"injuries":[{"team":{"abbreviation":"NYK"},"injuries":[
            {"athlete":{"displayName":"Test Player","id":"1001"},
             "status":"Out","type":{"name":"Knee"},"date":"2026-10-29T12:00Z"}]}]}
        result=normalize(data)
        self.assertEqual(result[0]["player"],"Test Player")
        self.assertEqual(result[0]["team"],"NYK")
        self.assertEqual(result[0]["status"],"Out")
    def test_absence_does_not_mean_available(self):
        def opener(req,timeout=18):
            return Response({"timestamp":"2026-10-29T12:00Z","injuries":[]})
        r=fetch(opener)
        self.assertEqual(r["status"],"RETRIEVED_SECONDARY")
        self.assertEqual(r["unlisted_players_status"],"UNKNOWN_NOT_CLEARED")
        self.assertFalse(r["official_authority"])
    def test_missing_schema_fails_closed(self):
        with self.assertRaises(ValueError):
            normalize({"message":"Service denied"})

if __name__=="__main__":
    unittest.main()
