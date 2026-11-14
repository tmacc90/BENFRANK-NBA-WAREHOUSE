"""NBA player identity discovery. Never guess IDs or accept fuzzy matches."""
import json,urllib.request,unicodedata,re
NBA_PLAYERS='https://stats.nba.com/stats/commonallplayers?LeagueID=00&Season={}-{}&IsOnlyCurrentSeason=0'
def normalize(name):
 return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode().lower()).strip()
def discover(name,season,request_json=None):
 if not name or len(name)>100:raise ValueError('INVALID_NAME')
 if request_json is None:
  def request_json(url):
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.nba.com/','Origin':'https://www.nba.com','Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=12) as r:return json.load(r)
 data=request_json(NBA_PLAYERS.format(season-1,str(season)[-2:]))
 matches=[]
 for group in data.get('resultSets',[]):
  headers=group.get('headers',[])
  for values in group.get('rowSet',[]):
   r=dict(zip(headers,values))
   if normalize(r.get('DISPLAY_FIRST_LAST',''))==normalize(name):
    matches.append({'nba_id':str(r['PERSON_ID']),'name':r['DISPLAY_FIRST_LAST']})
 ids={m['nba_id']:m for m in matches}
 if len(ids)!=1:raise ValueError('PLAYER_ID_AMBIGUOUS_OR_MISSING')
 return next(iter(ids.values()))
