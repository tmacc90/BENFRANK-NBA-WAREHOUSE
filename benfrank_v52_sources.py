"""Current depth-chart and optional published projected-lineup evidence.

Depth order is a forecast input, never medical clearance or a final starting five.
All retrieval clocks, source clocks, hashes, failures and disagreements survive.
"""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import json
import re
import urllib.request
from pathlib import Path

from acquire_history import name_key, team_key
from benfrank_v44_calibration import instant
from benfrank_v51_rosters import list_teams

BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/'
PROJECTED='https://www.rotowire.com/basketball/nba-lineups.php'

def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'BENFRANK-Early-Pregame/5.2','Accept':'application/json,text/html'})
    with urllib.request.urlopen(req,timeout=20) as r:
        if r.status!=200:raise ValueError('SOURCE_HTTP_'+str(r.status))
        if r.geturl().split('/')[2]!=url.split('/')[2]:raise ValueError('SOURCE_REDIRECT_HOST_CONFLICT')
        raw=r.read(4_000_001)
    if not raw or len(raw)>4_000_000:raise ValueError('EMPTY_OR_OVERSIZE_SOURCE')
    return raw

def parse_depth(document, expected, captured):
    team=team_key(document.get('team',{}).get('abbreviation',''))
    if team!=team_key(expected):raise ValueError('DEPTH_TEAM_CONFLICT')
    timestamp=document.get('timestamp')
    if timestamp and instant(timestamp)>instant(captured):raise ValueError('DEPTH_SOURCE_CLOCK_AFTER_RETRIEVAL')
    players={};positions={}
    for chart in document.get('depthchart',[]):
        for pos,group in chart.get('positions',{}).items():
            if pos.lower() not in ('pg','sg','sf','pf','c'):continue
            names=[]
            for rank,a in enumerate(group.get('athletes',[]),1):
                name=a.get('displayName');pid=str(a.get('id',''))
                if not name or not pid.isdigit():continue
                key=name_key(name)
                if key in players and players[key]['id']!=pid:raise ValueError('AMBIGUOUS_DEPTH_PLAYER_ID')
                item=players.setdefault(key,{'player':name,'id':pid,'ranks':{},'injuries':a.get('injuries') or []})
                item['ranks'][pos.upper()]=rank;names.append(name)
            if names:positions[pos.upper()]=names
    if len(positions)!=5 or len(players)<7:raise ValueError('INCOMPLETE_FIVE_POSITION_DEPTH_CHART')
    return {'team':team,'players':players,'positions':positions,'source_timestamp':timestamp,
            'captured_at':captured,'authority':'ESPN_PUBLISHED_DEPTH_ORDER_NOT_FINAL_LINEUP'}

def parse_projected(text,game_date):
    date=re.search(r'data-gamedate="(\d{4}-\d\d-\d\d)"',text)
    if not date or date.group(1)!=game_date:raise ValueError('PROJECTED_PAGE_GAME_DATE_CONFLICT')
    result={}
    for body in re.findall(r'<ul class="lineup__list[^\"]*">(.*?)</ul>',text,re.S):
        team=re.search(r'data-team="([A-Z]{2,4})"',body)
        if not team:continue
        first=body.split('class="lineup__title',1)[0]
        players=[]
        for li in re.findall(r'<li class="lineup__player[^\"]*"[^>]*>(.*?)</li>',first,re.S):
            a=re.search(r'<a[^>]*title="([^"]+)"[^>]*href="/basketball/player/',li)
            if a:players.append(html.unescape(a.group(1)))
        if len(players)!=5 or len({name_key(n) for n in players})!=5:continue
        code=team_key(team.group(1))
        if code in result and result[code]['players']!=players:raise ValueError('DUPLICATE_PROJECTED_TEAM_CONFLICT')
        result[code]={'players':players,'source_label':'EXPECTED' if 'is-expected' in first else 'PUBLISHED_LINEUP',
                      'official_final_starters_claimed':False}
    if not result:raise ValueError('NO_PUBLISHED_FIVE_PLAYER_PROJECTIONS')
    return result

def collect(teams,day,output,projected=False,fetcher=fetch):
    dt.date.fromisoformat(day);root=Path(output);root.mkdir(parents=True,exist_ok=True)
    index=fetcher(BASE+'teams');(root/'teams_index.json').write_bytes(index)
    lookup={team_key(c):i for i,c in list_teams(json.loads(index)).items()}
    results={};failures=[]
    def one(code):
        url=BASE+'teams/'+lookup[code]+'/depthcharts';raw=fetcher(url);captured=now()
        report=parse_depth(json.loads(raw),code,captured);sha=hashlib.sha256(raw).hexdigest()
        path=root/(code+'_'+sha[:12]+'.json');path.write_bytes(raw)
        report.update(url=url,sha256=sha,raw_file=path.name);return code,report
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fs={pool.submit(one,team_key(t)):team_key(t) for t in sorted(set(teams))}
        for f in concurrent.futures.as_completed(fs):
            try:code,r=f.result();results[code]=r
            except Exception as exc:failures.append({'team':fs[f],'reason':type(exc).__name__+': '+str(exc)})
    projection={};projection_source=None
    if projected:
        try:
            raw=fetcher(PROJECTED);projection=parse_projected(raw.decode('utf8'),day)
            path=root/'published_projected_lineups.html';path.write_bytes(raw)
            projection_source={'url':PROJECTED,'captured_at':now(),'sha256':hashlib.sha256(raw).hexdigest(),'raw_file':path.name,
                               'authority':'ROTOWIRE_OWN_EXPECTED_LINEUP_PROJECTION_NOT_OFFICIAL_FINAL'}
        except Exception as exc:failures.append({'source':'published_projected_lineups','reason':type(exc).__name__+': '+str(exc)})
    result={'version':'V52_EARLY_SOURCES_1','game_date':day,'captured_at':now(),'depths':results,
            'projected':projection,'projected_source':projection_source,'failures':failures,
            'final_starters_required_for_early_forecast':False,'projected_lineups_are_confirmed':False}
    (root/'early_sources.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

def secondary_injury_snapshot(payload,index,captured,sha):
    """Fallback retains literal ESPN statuses; absence never means available."""
    teams=list_teams(index);groups={};issues=[]
    if not isinstance(payload.get('injuries'),list):raise ValueError('MISSING_ESPN_INJURY_GROUPS')
    for group in payload['injuries']:
        code=teams.get(str(group.get('id')))
        if not code:issues.append({'team_id':group.get('id'),'reason':'UNRESOLVED_TEAM_ID'});continue
        entries={}
        for item in group.get('injuries',[]):
            player=(item.get('athlete') or {}).get('displayName');raw_status=item.get('status')
            if not player:continue
            if item.get('date') and instant(item['date'])>instant(captured):raise ValueError('INJURY_PUBLICATION_AFTER_RETRIEVAL')
            state=raw_status if raw_status in ('Out','Doubtful','Questionable','Probable','Available') else 'UNKNOWN_NOT_CLEARED'
            entries[name_key(player)]={'player':player,'status':state,'reported_status':raw_status,
                'reported_date':item.get('date'),'reason':'ESPN_SECONDARY_LITERAL_STATUS_NOT_OFFICIAL_CLEARANCE'}
        groups[team_key(code)]=entries
    return {'teams':groups,'printed_at':None,'retrieved_at':captured,'sha256':sha,'url':BASE+'injuries',
            'authority':'ESPN_SECONDARY_NOT_OFFICIAL','unlisted_status':'UNKNOWN_NOT_CLEARED','issues':issues}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--teams',nargs='+',required=True)
    p.add_argument('--date',required=True);p.add_argument('--output',required=True)
    p.add_argument('--published-projections',action='store_true',help='Explicitly opt into public RotoWire expected-five projections')
    a=p.parse_args();r=collect(a.teams,a.date,a.output,a.published_projections)
    print(json.dumps({'depth_teams':len(r['depths']),'projected_teams':len(r['projected']),'failures':r['failures']},indent=2))
    return 0 if r['depths'] else 2
if __name__=='__main__':raise SystemExit(main())
