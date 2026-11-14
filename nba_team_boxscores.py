"""NBA team box-score source adapter; official team rows for game-level reconciliation."""
import json,urllib.request
URL='https://stats.nba.com/stats/leaguegamefinder?LeagueID=00&PlayerOrTeam=T&Season={}-{}&SeasonType=Regular+Season'
def fetch_team_boxscores(season,request_json=None):
 url=URL.format(season-1,str(season)[-2:])
 if request_json is None:
  def request_json(url):
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36','Referer':'https://www.nba.com/stats/teams/boxscores','Origin':'https://www.nba.com','Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
 data=request_json(url)
 groups=data.get('resultSets') or data.get('resultSet') or []
 if isinstance(groups,dict):groups=[groups]
 rows=[]
 for group in groups:
  headers=group.get('headers',[])
  for values in group.get('rowSet',[]):
   r=dict(zip(headers,values))
   if not {'GAME_ID','TEAM_ID','GAME_DATE','MATCHUP'}<=r.keys():continue
   rows.append({'game_id':str(r['GAME_ID']),'team_id':str(r['TEAM_ID']),'date_raw':str(r['GAME_DATE']),'matchup':str(r['MATCHUP']),'points':r.get('PTS'),'source':'NBA_TEAM_BOX_SCORES'})
 if not rows:raise ValueError('TEAM_BOXSCORE_SCHEMA_EMPTY_OR_BLOCKED')
 return rows,url
def verify_team_games(player_rows,team_rows):
 games={str(r['game_id']) for r in team_rows}
 matched=[r for r in player_rows if str(r['event_id']) in games]
 return {'status':'PARTIAL' if len(matched)!=len(player_rows) else 'MATCHED_GAME_IDS','matched':len(matched),'player_games':len(player_rows),'team_rows':len(team_rows),'note':'Team rows validate game identity, not player points/rebounds/assists'}
