"""Bridge captured NBA/ESPN completed-game SQLite evidence to exact-line and legacy model.
No source promotion: only official NBA rows are authoritative; ESPN is separate secondary.
"""
import argparse,csv,json,sqlite3,pathlib,collections
from types import SimpleNamespace
from exact_line_coverage import run as coverage
PROPS=[
 ("Victor Wembanyama","blocks_steals",4.5,"SAC","blocks_steals"),
 ("Cam Spencer","pra",15.5,"OKC","pra"),
 ("Ziaire Williams","points_rebounds",10.5,"POR","pr"),
 ("Tyrese Maxey","points",24.5,"CLE","points"),
 ("Paul George","pra",26.5,"CHA","pra"),
 ("Jaylen Brown","3ptm",1.5,"CLE","threes")]
def load(db,table,source):
    if not pathlib.Path(db).exists():return []
    c=sqlite3.connect('file:'+str(pathlib.Path(db).resolve())+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    try:return [dict(r,source=source) for r in c.execute('SELECT * FROM '+table)]
    finally:c.close()
def normalize(r):
    official='game_date' in r
    get=lambda a,b:r[a if official else b]
    return dict(date=get('game_date','date'),player=r['player'],season='2026-27',opponent=r['opponent'],
                points=get('pts','pts'),rebounds=get('reb','reb'),assists=get('ast','ast'),
                blocks=get('blk','blk'),steals=get('stl','stl'),three_pointers_made=get('fg3m','fg3m'),
                game_id=get('game_id','source_game_id'),competition='NBA',source=r['source'],
                team=r['team'],minutes=r['minutes'],starter=r['starter'],
                home=r['home'],tov=r['tov'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--official',required=True);p.add_argument('--espn',required=True);p.add_argument('--out',required=True);p.add_argument('--cutoff',default='2026-11-06');a=p.parse_args()
    root=pathlib.Path(a.out);root.mkdir(parents=True,exist_ok=True)
    sources={'official':load(a.official,'nba_official_completed','NBA_OFFICIAL'),'espn':load(a.espn,'current_games','ESPN_SECONDARY')}
    normalized={k:[normalize(r) for r in rows] for k,rows in sources.items()}
    # Prefer official for identical player/date/team; never silently assert a cross-source match.
    merged={};conflicts=[]
    for source in ('espn','official'):
        for r in normalized[source]:
            key=(r['player'].casefold(),r['date'],r['team'])
            old=merged.get(key)
            if old and any(old[k]!=r[k] for k in ('points','rebounds','assists','blocks','steals','three_pointers_made')):
                conflicts.append({'player':r['player'],'date':r['date'],'official_vs_secondary':'STAT_CONFLICT'})
                merged.pop(key,None)
                continue
            if key not in merged or source=='official':merged[key]=r
    cols=['date','player','season','opponent','points','rebounds','assists','blocks','steals','three_pointers_made','game_id','competition']
    csvpath=root/'observed_game_logs.csv'
    with csvpath.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows([{k:r[k] for k in cols} for r in merged.values()])
    results=[]
    for player,market,line,opponent,legacy in PROPS:
        dest=root/(player.lower().replace(' ','_')+'_coverage.json')
        args=SimpleNamespace(csv=str(csvpath),player=player,market=market,line=line,current_season='2026-27',last_season='2025-26',cutoff=a.cutoff)
        report=coverage(args);dest.write_text(json.dumps(report,indent=2))
        n=report['windows']['L52']['games']
        results.append({'player':player,'market':market,'line':line,'historical_games':n,'coverage_file':dest.name,'historical_status':'PARTIAL' if n<52 else '52_OBSERVED','prediction_status':'BLOCKED_INSUFFICIENT_VERIFIED_MODEL_INPUT','sequential_simulations_executed':0,'blind_ai_executed':False})
    summary={'official_rows':len(sources['official']),'espn_rows':len(sources['espn']),'merged_rows':len(merged),'conflicts':conflicts,'props':results,'ticket_authority':'NO_TICKET','note':'No invented simulations. Historical 3-day captures are insufficient for L52 or validated predictions.'}
    (root/'integrated_report.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
