import datetime as dt
import sqlite3
import unittest
from engine import connect
from benfrank_v44_calibration import (
    check_snapshot, probability_from_history, fit_isotonic, calibrate, evaluate)

class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        base=dt.date(2025,10,1)
        for i in range(125):
            self.c.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("Test Player", (base+dt.timedelta(days=i)).isoformat(),"2025-26",
                 "BOS","NYK",1,1,30,15+(i%11),5,4,1,0,2,2))
        self.c.commit()
        self.base=base
    def snapshot(self, i, line=20.5):
        d=self.base+dt.timedelta(days=i)
        return {"player":"Test Player","market":"points","line":line,"opponent":"NYK",
                "game_date":d.isoformat(),"platform":"FixturePlatform","snapshot_id":f"test-{i}",
                "captured_at":d.isoformat()+"T13:00:00Z","tipoff_utc":d.isoformat()+"T23:00:00Z"}
    def test_after_tipoff_rejected(self):
        p=self.snapshot(30)
        p["captured_at"]=p["tipoff_utc"]
        with self.assertRaises(ValueError):
            check_snapshot(p)
    def test_raw_probability_uses_prior_only(self):
        x=self.c.execute("SELECT * FROM games WHERE date<? ORDER BY date DESC",
                         ((self.base+dt.timedelta(days=40)).isoformat(),)).fetchall()
        p=probability_from_history(x,"points",20.5)
        self.assertEqual(p["history_n"],20)
        self.assertTrue(0 < p["p_over_raw"] < 1)
    def test_snapshot_historical_evaluation_not_certified(self):
        p=[self.snapshot(i) for i in range(20,120)]
        result=evaluate(self.c,p)
        self.assertEqual(result["eligible"],100)
        self.assertEqual(result["status"],"EVALUATED_SOURCE_VERIFICATION_PENDING")
        self.assertEqual(result["train_n"],60)
        self.assertEqual(result["holdout_n"],40)
        self.assertEqual(result["certification"],"NOT_CERTIFIED")
        self.assertLess(result["train_latest_tipoff"],result["holdout_earliest_tipoff"])
    def test_insufficient_real_snapshots(self):
        x=evaluate(self.c,[self.snapshot(30)])
        self.assertEqual(x["status"],"INSUFFICIENT_SNAPSHOTS")
    def test_isotonic_monotone(self):
        blocks=fit_isotonic([(0.1,0),(0.2,1),(0.3,0),(0.8,1)])
        out=[calibrate(p,blocks) for p in [0.1,0.2,0.3,0.8]]
        self.assertEqual(out,sorted(out))
    def test_snapshot_dedup(self):
        with self.assertRaises(ValueError):
            evaluate(self.c,[self.snapshot(30),self.snapshot(30)])

if __name__=="__main__":
    unittest.main()
