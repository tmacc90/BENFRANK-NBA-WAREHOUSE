"""Capture fresh official NBA Stats box scores and complete season league logs."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

from refresh_and_audit import atomic_json, now


def run(games, seasons, out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    requests={}
    for gid in games:
        requests['boxscore_'+gid]=('boxscoretraditionalv3',{'GameID':gid,'LeagueID':'00',
          'StartPeriod':0,'EndPeriod':0,'StartRange':0,'EndRange':0,'RangeType':0})
    for season in seasons:
        requests['league_'+season]=('leaguegamelog',{'LeagueID':'00','Season':season,
          'SeasonType':'Regular Season','PlayerOrTeam':'P','Counter':0,'Sorter':'DATE',
          'Direction':'ASC','DateFrom':'','DateTo':''})
    def capture(item):
        name,(endpoint,params)=item
        url='https://stats.nba.com/stats/'+endpoint+'?'+urllib.parse.urlencode(params)
        receipt={'name':name,'url':url,'started_utc':now()}
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0',
                 'Accept':'application/json','Referer':'https://www.nba.com/'})
            with urllib.request.urlopen(req,timeout=25) as response:
                raw=response.read(10_000_001);receipt['http_status']=response.status
            if len(raw)>10_000_000:
                raise ValueError('OVERSIZED_RESPONSE')
            data=json.loads(raw)
            if endpoint=='boxscoretraditionalv3':
                if str(data['boxScoreTraditional']['gameId'])!=params['GameID']:
                    raise ValueError('WRONG_GAME_ID')
            elif data['parameters']['Season']!=params['Season'] or not data['resultSets'][0]['rowSet']:
                raise ValueError('WRONG_OR_EMPTY_SEASON')
            (out/(name+'.json')).write_bytes(raw)
            receipt.update(status='FETCHED_JSON',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        except Exception as exc:
            receipt.update(status='FAILED',error_type=type(exc).__name__,error=str(exc))
        receipt['finished_utc']=now()
        return receipt
    receipts=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(capture,item) for item in requests.items()]
        for future in concurrent.futures.as_completed(futures):
            receipt=future.result();receipts.append(receipt)
            atomic_json(out/'fetch_receipt.json',sorted(receipts,key=lambda r:r['name']))
            print(json.dumps(receipt),flush=True)
    return 0 if receipts and all(r['status']=='FETCHED_JSON' for r in receipts) else 2


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--games',nargs='*',default=['0022400871'])
    p.add_argument('--seasons',nargs='+',default=['2024-25','2025-26'])
    p.add_argument('--out',required=True)
    a=p.parse_args()
    raise SystemExit(run(a.games,a.seasons,a.out))
