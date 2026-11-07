"""Append final-game grading; retain source bytes and never rewrite a prediction."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benfrank_auto_history import Store
from benfrank_auto_runner import write
from benfrank_v52_ledger import settle, scorecard


def grade(state_dir, output):
    state, root = Path(state_dir), Path(output)
    ledger = state / 'forward_ledger.sqlite'
    if not ledger.is_file():
        raise FileNotFoundError('FROZEN_FORWARD_LEDGER_MISSING')
    root.mkdir(parents=True, exist_ok=False)
    store = Store(state)
    def fetch(url):
        raw, meta = store.fetch(url, 'ESPN')
        return json.loads(raw), raw
    try:
        settlements = settle(ledger, fetch=fetch)
        card = scorecard(ledger)
        result = dict(settlements=settlements, scorecard=card,
                      native_platform_settlement_verified=False, certified=False,
                      note='DNP and platform void ambiguity remains unresolved; no forced win/loss')
        write(root/'grading_receipt.json', result)
        write(root/'grading_source_manifest.json', store.manifest())
        return result
    finally:
        store.db.close()


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(grade(a.state,a.output),indent=2))
