"""NBA warehouse connection/installation diagnostic; no synthetic data."""
import argparse, importlib.util, json, sqlite3, subprocess, sys
from pathlib import Path
from engine import connect
from upgrade import migrate, acquire

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--db',default='nba_warehouse.sqlite')
 p.add_argument('--install',action='store_true')
 p.add_argument('--player',default='Giannis Antetokounmpo')
 p.add_argument('--player-id',default='203507')
 p.add_argument('--season',default='2025-26')
 p.add_argument('--fetch',action='store_true')
 args=p.parse_args()
 installed=importlib.util.find_spec('nba_api') is not None
 install_result='NOT_REQUESTED'
 if args.install and not installed:
  r=subprocess.run([sys.executable,'-m','pip','install','nba_api'],capture_output=True,text=True,timeout=90)
  install_result='SUCCESS' if r.returncode==0 else 'FAILED: '+(r.stderr[-500:] or r.stdout[-500:])
  installed=importlib.util.find_spec('nba_api') is not None
 db=Path(args.db)
 c=connect(db);migrate(c)
 schema=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
 out={'database':str(db.resolve()),'warehouse_tables':schema,'nba_api_installed':installed,'install_result':install_result,'live_fetch':'NOT_REQUESTED'}
 if args.fetch:
  out['live_fetch']=acquire(c,args.player,args.player_id,args.season) if installed else 'BLOCKED_NBA_API_NOT_INSTALLED'
 print(json.dumps(out,indent=2,default=str))
 c.close()
if __name__=='__main__':main()
