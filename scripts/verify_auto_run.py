"""Re-read produced bytes, trace chains and immutable ledger. No model rerun."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benfrank_auto_evidence import verify_trace, reproduce_trace_samples
from benfrank_v52_early import stress
from benfrank_v44_calibration import instant


def verify(run_dir, state):
    root, state = Path(run_dir), Path(state)
    summary = json.loads((root/'execution_receipt.json').read_text())
    if summary['all_requested_props_executed'] is not True or summary['preservation_verified'] is not True:
        raise ValueError('RUN_INCOMPLETE_OR_PRESERVATION_FAILURE')
    if summary['certified'] or summary['calibration_applied'] or summary['accuracy_certified']:
        raise ValueError('UNSUPPORTED_CERTIFICATION_CLAIM')
    manifest = json.loads((root/'source_manifest.json').read_text())
    documents={d['id']:d for d in manifest['documents']}
    reconciled=json.loads((root/'reconciliation.json').read_text())
    for source in manifest['documents']:
        if hashlib.sha256((state/source['file']).read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('RAW_SOURCE_BYTES_HASH_CONFLICT')
    count, games = 0, 0
    samples=[]
    with sqlite3.connect('file:'+str((state/'forward_ledger.sqlite').resolve())+'?mode=ro', uri=True) as conn:
        for entry in summary['props']:
            sid = entry['prop']['snapshot_id']
            path = root/'props'/sid/'prediction.json'
            r = json.loads(path.read_text())
            cutoff=instant(r['analysis_cutoff_utc'])
            for record in reconciled['records']:
                if record['date']>=r['prop']['game_date']:
                    raise ValueError('TARGET_OR_FUTURE_HISTORY_RECORD')
                if any(instant(documents[did]['retrieved_utc'])>cutoff for did in record['source_documents']):
                    raise ValueError('SOURCE_RETRIEVAL_AFTER_FROZEN_CUTOFF')
            claimed = r.pop('receipt_sha256')
            actual = hashlib.sha256(json.dumps(r,sort_keys=True,allow_nan=False).encode()).hexdigest()
            if actual != claimed: raise ValueError('PREDICTION_RECEIPT_HASH_CONFLICT')
            row = conn.execute('SELECT issued_at,tipoff_utc,receipt_sha256 FROM early_predictions WHERE id=?',(sid,)).fetchone()
            if not row or row[2] != claimed or not instant(row[0]) < instant(row[1]):
                raise ValueError('FROZEN_PREGAME_LEDGER_CONFLICT')
            deadline = r.get('requested_pregame_cutoff_utc')
            if deadline and not cutoff <= instant(r['forecast_completed_at_utc']) <= instant(row[0]) < instant(deadline):
                raise ValueError('REQUESTED_PREGAME_CUTOFF_VIOLATION')
            main = r['main_simulation']
            # Relocate traces by basename to allow downloading a CI artifact elsewhere.
            for sim in [main, *r['stress_simulations'].values()]:
                trace = root/'props'/sid/'trials'/Path(sim['trial_evidence']['trace_file']).name
                verify_trace(trace,sim,r['prop']['line']); games += sim['trials_executed']
            samples.append(reproduce_trace_samples(r['context'],main,r['prop']['player'],r['prop']['market'],
                           root/'props'/sid/'trials'/'main.jsonl.gz'))
            for kind,sim in r['stress_simulations'].items():
                modified=stress(r['context'],r['prop']['player'],r['direction'],kind)
                samples.append(reproduce_trace_samples(modified,sim,r['prop']['player'],r['prop']['market'],
                               root/'props'/sid/'trials'/(kind+'.jsonl.gz')))
            if main['trials_executed'] < 25000 or not r['blind_model']['independence_evidence']['verified']:
                raise ValueError('PHYSICAL_OR_BLIND_PROCESS_PROOF_MISSING')
            if len(r['interrogation']['questions']) != 60:
                raise ValueError('SIXTY_QUESTION_REPORT_INCOMPLETE')
            count += 1
    return dict(status='ACTUAL_ARTIFACTS_VERIFIED', predictions=count, complete_simulated_games=games,
                source_documents=len(manifest['documents']), deterministic_game_replay_samples=samples,
                calibration_certified=False)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--state',required=True)
    a=p.parse_args();print(json.dumps(verify(a.run,a.state),indent=2))
