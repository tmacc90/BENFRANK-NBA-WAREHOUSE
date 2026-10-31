"""One-command early shadow forecast, fresh depth/projections and injury snapshots.

Config supplies real source-backed historical profile contexts and history DB.
Historical context ingestion stays independent of projected starting status.
"""
import argparse
import hashlib
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from acquire_history import name_key
from benfrank_v52_sources import collect,secondary_injury_snapshot,fetch,BASE
from benfrank_v47_live_official_injuries import collect as collect_injury
from benfrank_v47_availability import parse_pdf

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();config=json.loads(Path(a.config).read_text());root=Path(a.output)
    root.mkdir(parents=True,exist_ok=False)
    board=json.loads(Path(config['board']).read_text())
    dates={p['game_date'] for p in board}
    if len(dates)!=1:raise ValueError('ONE_ASOF_GAME_DATE_PER_SOURCE_CAPTURE_REQUIRED')
    day=dates.pop();teams=sorted({p[k] for p in board for k in ('team','opponent')})
    collect(teams,day,root/'sources',projected=config.get('published_projected_lineups',False))
    ir=collect_injury(dt.datetime.now(dt.timezone.utc).isoformat(),root/'injury')
    input_path=root/'injury_input.json'
    if ir['status']=='OFFICIAL_PDF_PARSED':
        report=ir['report'];cutoff=dt.datetime.now(dt.timezone.utc).isoformat()
        parsed=parse_pdf(root/'injury'/report['file'],report['report_time_utc'],cutoff)
        statuses={}
        for key,g in parsed['game_team_reports'].items():
            if key.startswith(day+'|'):statuses[key.split('|')[-1]]={name_key(x['player']):x for x in g['players'].values()}
        data={'teams':statuses,'printed_at':report['report_time_utc'],'retrieved_at':report['retrieved_at'],
              'sha256':report['sha256'],'url':report['url'],'authority':'ORIGINAL_NBA_INJURY_PDF'}
    else:
        raw=fetch(BASE+'injuries');captured=dt.datetime.now(dt.timezone.utc).isoformat()
        (root/'injury/espn_secondary.json').write_bytes(raw)
        data=secondary_injury_snapshot(json.loads(raw),json.loads((root/'sources/teams_index.json').read_text()),captured,hashlib.sha256(raw).hexdigest())
        data['official_source_failure']=ir
    input_path.write_text(json.dumps(data,indent=2))
    command=[sys.executable,str(Path(__file__).with_name('benfrank_v52_early.py')),
        '--board',config['board'],'--contexts',config['contexts'],'--sources',str(root/'sources/early_sources.json'),
        '--injury',str(input_path),'--history-db',config['history_db'],'--output',str(root/'results'),
        '--ledger',config['ledger'],'--trials',str(config.get('trials',25000)),
        '--stress-trials',str(config.get('stress_trials',2000))]
    return subprocess.run(command,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
