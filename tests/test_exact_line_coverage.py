import csv, tempfile, pathlib, unittest, sys
from types import SimpleNamespace
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from exact_line_coverage import run
class ExactLineCoverageTests(unittest.TestCase):
    def test_windows_and_cutoff(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'logs.csv'
            with p.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['date','player','season','opponent','points','rebounds','assists','blocks','steals','three_pointers_made'])
                w.writeheader()
                for date,pts in [('2026-11-01',25),('2026-11-02',24),('2026-11-03',25),('2026-11-06',100)]:
                    w.writerow(dict(date=date,player='Tyrese Maxey',season='2026-27',opponent=date,points=pts,rebounds=1,assists=1,blocks=0,steals=0,three_pointers_made=1))
            args=SimpleNamespace(csv=str(p),player='Tyrese Maxey',market='points',line=24.5,current_season='2026-27',last_season='2025-26',cutoff='2026-11-06')
            r=run(args)
            self.assertEqual((r['windows']['L5']['games'],r['windows']['L5']['over'],r['windows']['L5']['under']),(3,2,1))
            self.assertEqual(len(r['games']),3)
    def test_integer_push(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'logs.csv'
            p.write_text('date,player,season,opponent,points,rebounds,assists,blocks,steals,three_pointers_made\n2026-11-01,Tyrese Maxey,2026-27,CLE,25,0,0,0,0,0\n')
            args=SimpleNamespace(csv=str(p),player='Tyrese Maxey',market='points',line=25,current_season='2026-27',last_season='2025-26',cutoff='2026-11-06')
            self.assertEqual(run(args)['windows']['L5']['push'],1)
if __name__=='__main__':unittest.main()
