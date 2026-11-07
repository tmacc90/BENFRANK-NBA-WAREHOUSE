"""Live acquisition first; explicit supplied-capture route for native API 403.

A successful supplied-capture prediction does NOT make live discovery available.
No new endpoint, proxy, or access-control workaround is used.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benfrank_auto_runner import run,write
from benfrank_auto_history import PP
from scripts.verify_auto_run import verify


def execute(config,capture_config,root,state):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    live,code=run(config,root/'live',state)
    route=dict(live_acquisition_status=live['status'],live_run=str(root/'live'),
               live_exact_blocker=live.get('fatal_blocker'),current_native_line_recheck=code==0)
    target=root/'live'
    if code:
        reason=live.get('fatal_blocker','')
        # A different data/model failure is not hidden by switching cohorts.
        if PP not in reason or 'HTTP Error 403' not in reason:
            write(root/'ci_route_receipt.json',route);return code
        route['live_acquisition_status']='BLOCKED_NATIVE_PROVIDER_HTTP_403'
        captured,code=run(capture_config,root/'supplied-capture',state)
        route.update(supplied_capture_status=captured['status'],
                     supplied_capture_run=str(root/'supplied-capture'),
                     current_native_line_recheck=False)
        target=root/'supplied-capture'
    if code==0:
        route['actual_execution_verification']=verify(target,state)
    route['certified']=False
    write(root/'ci_route_receipt.json',route)
    print(json.dumps(route,indent=2),flush=True)
    return code


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True)
    p.add_argument('--capture-config',required=True);p.add_argument('--output',required=True)
    p.add_argument('--state',required=True);a=p.parse_args()
    raise SystemExit(execute(a.config,a.capture_config,a.output,a.state))
