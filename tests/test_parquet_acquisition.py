import tempfile, unittest, csv, os, sys
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from acquire_parquet import ingest
from engine import connect
class AcquisitionTests(unittest.TestCase):
 def test_actual_parquet_is_staged_without_promotion(self):
  import pyarrow as pa
  import pyarrow.parquet as pq
  with tempfile.TemporaryDirectory() as d:
   path=os.path.join(d,'games.parquet');db=os.path.join(d,'db.sqlite')
   pq.write_table(pa.Table.from_pylist([dict(player='Fixture only',date='2025-11-01',
    season='2025-26',team='MIA',opponent='CHA',minutes=30,pts=20,reb=8,ast=5,
    stl=1,blk=1,tov=2,fg3m=1)]),path)
   result=ingest(db,path,'espn')
   self.assertEqual(result['staged'],1)
   self.assertEqual(result['verified_engine_rows_added'],0)
   c=connect(db)
   self.assertIn('SEASON_TYPE_UNVERIFIED',c.execute('SELECT issue FROM staged_games').fetchone()[0])
 def test_stage_and_no_unverified_promotion(self):
  with tempfile.TemporaryDirectory() as d:
   path=os.path.join(d,'games.csv'); db=os.path.join(d,'nba.sqlite')
   with open(path,'w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['PLAYER','DATE','SEASON','TEAM','OPP','MIN','PTS','REB','AST','STL','BLK','TOV','FG3M']);w.writeheader();w.writerow(dict(PLAYER='Test Player',DATE='2025-10-23',SEASON='2025-26',TEAM='MIA',OPP='CHA',MIN=30,PTS=20,REB=8,AST=5,STL=1,BLK=1,TOV=2,FG3M=1))
   m={'player':'PLAYER','date':'DATE','season':'SEASON','team':'TEAM','opponent':'OPP','minutes':'MIN','pts':'PTS','reb':'REB','ast':'AST','stl':'STL','blk':'BLK','tov':'TOV','fg3m':'FG3M'}
   out=ingest(db,path,'espn',m)
   self.assertEqual(out['staged'],1)
   self.assertEqual(out['verified_engine_rows_added'],0)
   c=connect(db);self.assertEqual(c.execute('select count(*) from games').fetchone()[0],0)
   self.assertIn('STARTER_UNVERIFIED',c.execute('select issue from staged_games').fetchone()[0])
 def test_reject_bad_game(self):
  with tempfile.TemporaryDirectory() as d:
   path=os.path.join(d,'bad.csv');db=os.path.join(d,'db.sqlite')
   with open(path,'w') as f:f.write('player,date,team,minutes,pts\nA,2025-10-23,MIA,-1,20\n')
   out=ingest(db,path,'espn')
   self.assertEqual(out['staged'],0);self.assertEqual(out['rejected'],1)
if __name__=='__main__':unittest.main()
