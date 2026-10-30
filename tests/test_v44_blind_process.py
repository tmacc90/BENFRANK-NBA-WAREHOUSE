import datetime as dt
import sqlite3
import unittest
from benfrank_v44_blind_orchestrator import run_separate,worker_input
from benfrank_v44_blind_worker import calculate
from engine import connect

class BlindProcessTests(unittest.TestCase):
    def setUp(self):
        self.c=connect(":memory:")
        base=dt.date(2025,10,1)
        self.base=base
        for i in range(70):
            self.c.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              ("Test Player",(base+dt.timedelta(days=i)).isoformat(),"2025-26","BOS","NYK",
               1,1,25+(i%9),16+(i%12),5,4,1,0,2,2))
        self.c.commit()
    def tearDown(self):
        self.c.close()
    def test_line_cannot_enter_blind_model(self):
        data={"train":[{"x":[i,1,1,1,1],"y":i} for i in range(25)],
              "candidate":[9,1,1,1,1],"ridge":0.15}
        self.assertEqual(calculate(data)["status"],"EXECUTED_PROCESS_SEPARATE_ML")
        data["line"]=18.5
        with self.assertRaises(ValueError):
            calculate(data)
    def test_worker_executes_independently(self):
        target=(self.base+dt.timedelta(days=65)).isoformat()
        result=run_separate(self.c,"Test Player","points",target)
        self.assertEqual(result["status"],"EXECUTED_PROCESS_SEPARATE_ML")
        self.assertTrue(result["training_n"]>=20)
        self.assertFalse(result["line_received"])
        self.assertEqual(result["certification"],"NOT_VALIDATED_OR_CALIBRATED")
    def test_unknown_player_blocks(self):
        target=(self.base+dt.timedelta(days=65)).isoformat()
        r=run_separate(self.c,"Missing","points",target)
        self.assertEqual(r["status"],"BLOCKED")
    def test_later_game_cannot_leak(self):
        target=(self.base+dt.timedelta(days=60)).isoformat()
        prior=run_separate(self.c,"Test Player","points",target)
        later=(self.base+dt.timedelta(days=61)).isoformat()
        self.c.execute("UPDATE games SET pts=100 WHERE date=?",(later,))
        after=run_separate(self.c,"Test Player","points",target)
        self.assertEqual(prior["projection"],after["projection"])
        self.assertEqual(prior["input_sha256"],after["input_sha256"])

if __name__=="__main__":
    unittest.main()
