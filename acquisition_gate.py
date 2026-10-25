"""Fail-closed gate for real NBA historical acquisition. No sample data counted."""
import argparse, json, sqlite3, sys
from pathlib import Path

def audit(db, player, seasons, min_games):
    if not Path(db).exists():
        return {'status':'FAIL','reason':'WAREHOUSE_MISSING','db':db}
    conn=sqlite3.connect(db)
    conn.row_factory=sqlite3.Row
    try:
        tables={x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'games' not in tables:return {'status':'FAIL','reason':'GAMES_TABLE_MISSING'}
        counts={season:conn.execute('SELECT COUNT(*) FROM games WHERE lower(player)=lower(?) AND season=?',(player,season)).fetchone()[0] for season in seasons}
        invalid=conn.execute('SELECT COUNT(*) FROM games WHERE lower(player)=lower(?) AND (minutes < 0 OR minutes > 70 OR pts < 0 OR reb < 0 OR ast < 0 OR stl < 0 OR blk < 0 OR tov < 0 OR fg3m < 0 OR starter NOT IN (0,1) OR home NOT IN (0,1))',(player,)).fetchone()[0]
        duplicate_dates=conn.execute('SELECT COUNT(*) FROM (SELECT date, COUNT(*) n FROM games WHERE lower(player)=lower(?) GROUP BY date HAVING n > 1)',(player,)).fetchone()[0]
        provenance=[]
        if 'provenance' in tables:
            provenance=[dict(x) for x in conn.execute("SELECT * FROM provenance WHERE lower(player)=lower(?) OR player='*' ORDER BY rowid DESC LIMIT 12",(player,))]
        identity_missing=sum(counts.values())
        if 'game_verifications' in tables:
            placeholders=','.join('?' for _ in seasons)
            identity_missing=conn.execute('''SELECT COUNT(*) FROM games g LEFT JOIN game_verifications v
              USING(player,date,team) WHERE lower(g.player)=lower(?) AND g.season IN ('''+placeholders+''')
              AND v.player IS NULL''',(player,*seasons)).fetchone()[0]
        good=min_games>0 and bool(seasons) and all(v>=min_games for v in counts.values()) and invalid==0 and duplicate_dates==0 and bool(provenance) and identity_missing==0
        return {'status':'PASS' if good else 'FAIL','player':player,'season_counts':counts,'min_games_per_season':min_games,'invalid_rows':invalid,'duplicate_dates':duplicate_dates,'provenance_count':len(provenance),'unverified_game_identities':identity_missing,'recent_provenance':provenance,'scope':'Record presence/identity only; not model calibration or complete career coverage'}
    finally:conn.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--player',required=True);p.add_argument('--seasons',nargs='+',required=True);p.add_argument('--min-games',type=int,default=1);p.add_argument('--output',default='acquisition_audit.json')
    a=p.parse_args();result=audit(a.db,a.player,a.seasons,a.min_games);Path(a.output).write_text(json.dumps(result,indent=2,default=str));print(json.dumps(result,indent=2,default=str));sys.exit(0 if result['status']=='PASS' else 2)
if __name__=='__main__':main()
