"""Readable per-prop receipts without inventing a calibrated confidence score."""
import json
from pathlib import Path


def write_prop_report(path,result):
    p=result['prop'];s=result['main_simulation'];blind=result['blind_model']
    lines=[f"# 🧬🏀 {p['player']} — {p['market']} {p['line']}",'',
        f"**{result['direction']} — research only. Ticket-qualified: NO.**",'',
        f"Game: {p['team']} vs {p['opponent']} | cutoff: {result['analysis_cutoff_utc']}",
        f"Exact line source: {p.get('source_url')} | authority: {p.get('line_authority')}",'',
        f"Projection: {result['projection']:.3f}; difference from line: {result['projection']-p['line']:+.3f}.",
        f"Raw nonpush OVER share: {s['p_over_raw']:.4f}; probability calibration: UNCALIBRATED.",
        f"Actual main trials: {s['trials_executed']:,}; all simulation branches: {result['actual_complete_game_count_all_branches']:,}.",
        f"Blind forecast: {blind.get('projection')}; process independence verified: {blind.get('independence_evidence',{}).get('verified',False)}.",
        f"Model-error risk: {result['model_error']['calibration_status']}; numerical estimate: {result['model_error']['estimated_error_probability']}.",'',
        '| Historical window | OVER | UNDER | PUSH | Sample | Mean | Status |',
        '|---|---:|---:|---:|---:|---:|---|']
    for name,w in result['historical_windows'].items():
        lines.append(f"| {name} | {w['over_count']} | {w['under_count']} | {w['push_count']} | {w['n']} | {w['mean']} | {w['availability']} |")
    career=result.get('career_baseline',{})
    if career.get('career_means'):
        lines += ['',f"Verified career mean: {career['career_means'][p['market']]:.3f} over {career['career_games']} appearances. Exact-line coverage uses the available game archive only."]
    lines+=['','Historical percentages describe exact-line coverage; they are separate from simulation shares.','',
            '| Tested line | OVER share (raw, nonpush) | Side |','|---|---:|---|']
    for item in result['sensitivity']['ladder']:
        lines.append(f"| {item['line']} | {item['p_over_raw']} | {item['side']} |")
    lines+=['','**Opposing case:** '+result['adversarial']['opposing_side']+'. Minutes cuts, limited availability, foul-trouble and blowout proxies can change opportunities and efficiency.',
            f"Tested scenario side reversal: {result['scenario_side_flip']}. These are assumption stresses, not empirically calibrated scenario probabilities.",'',
            '**Limitations:** '+ '; '.join(result['context']['limitations']),
            'Official availability, projected five, source disagreements, uncertainty intervals, exact seeds, inputs and hashes are in prediction.json and companion source receipts.',
            'The 🤑 primary marker requires a qualified ticket. No primary is awarded in this uncalibrated run.']
    with Path(path).open('x') as stream:stream.write('\n'.join(lines)+'\n')
