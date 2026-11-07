'use strict';
const $ = id => document.getElementById(id);
const terminal = new Set(['completed', 'incomplete', 'failed', 'interrupted']);
let currentJob = null;
let polling = false;
const headers = () => ({Authorization: 'Bearer ' + $('token').value.trim()});
const setStatus = text => { $('status').textContent = text; };
function lastJob(value) {
  try {
    if (value) sessionStorage.setItem('benfrank-last-job', value);
    return sessionStorage.getItem('benfrank-last-job');
  } catch (_) { return value || null; }
}
async function request(path, options = {}) {
  const response = await fetch(path, {...options, headers: headers()});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed: ' + response.status);
  return data;
}
function showJob(job) {
  currentJob = job;
  $('job-id').textContent = 'Job: ' + job.job_id;
  $('result').textContent = JSON.stringify(job, null, 2);
  $('verified').textContent = job.execution_receipt?.verified ? 'Execution verified ✓' : 'Execution unverified';
  const explanation = job.reason || job.error;
  setStatus('Framework status: ' + job.status + (explanation ? ' · ' + explanation : ''));
  $('receipt').hidden = !terminal.has(job.status) || !job.execution_receipt?.url;
  $('artifacts').hidden = !terminal.has(job.status);
  const summary = job.prediction_summary;
  $('prediction').hidden = !summary;
  $('empty').hidden = Boolean(summary);
  if (!summary) return;
  $('direction').textContent = summary.direction;
  $('projection').textContent = Number(summary.projection).toFixed(1);
  $('comparison').textContent = 'Blind model: ' + Number(summary.blind_projection).toFixed(1) +
    ' · Model disagreement: ' + (summary.model_disagreement ? 'YES' : 'NO');
  $('risk').textContent = 'Scenario reversal: ' + (summary.scenario_side_flip ? 'YES — fragile' : 'No in tested cases') +
    ' · 25,000 main trials · Raw model OVER share: ' + (100 * summary.p_over_raw).toFixed(1) + '% (uncalibrated)';
  $('windows').replaceChildren();
  for (const [name, w] of Object.entries(summary.historical_windows)) {
    const row = document.createElement('tr');
    for (const value of [name, w.over_count, w.under_count, w.push_count ?? w.push, w.n]) {
      const cell = document.createElement('td'); cell.textContent = value ?? '—'; row.append(cell);
    }
    $('windows').append(row);
  }
}
async function poll(id) {
  if (polling) return;
  polling = true; $('run').disabled = true; $('resume').disabled = true;
  try {
    // A reload can resume with the job ID; the token is entered again.
    for (let attempt = 0; attempt < 1200; attempt++) {
      const job = await request('/api/jobs/' + encodeURIComponent(id));
      showJob(job);
      if (terminal.has(job.status)) return;
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
    setStatus('This run is still processing. Use Check last job to resume.');
  } catch (error) { setStatus('Unable to check execution: ' + error.message); }
  finally { polling = false; $('run').disabled = false; $('resume').disabled = false; }
}
$('prop-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (polling) return;
  const local = new Date($('cutoff').value);
  if (!Number.isFinite(local.getTime()) || local <= new Date()) {
    setStatus('Choose a future cutoff before the game starts.'); return;
  }
  $('run').disabled = true; $('prediction').hidden = true;
  $('receipt').hidden = true; $('artifacts').hidden = true;
  setStatus('Checking your exact prop and creating a saved job…');
  try {
    const form = new FormData();
    form.append('player', $('player').value.trim()); form.append('market', $('market').value);
    form.append('line', $('line').value); form.append('pregame_cutoff', local.toISOString());
    const data = await request('/api/run-framework', {method: 'POST', body: form});
    lastJob(data.job_id); $('resume').hidden = false;
    await poll(data.job_id);
  } catch (error) { setStatus('Unable to start execution: ' + error.message); }
  finally { $('run').disabled = false; }
});
$('resume').hidden = !lastJob();
$('resume').addEventListener('click', () => {
  if (!$('token').value.trim()) { setStatus('Enter your access token to check the saved job.'); return; }
  if (lastJob()) poll(lastJob());
});
async function download(kind) {
  if (!currentJob) return;
  try {
    const response = await fetch('/api/jobs/' + currentJob.job_id + '/' + kind, {headers: headers()});
    if (!response.ok) throw new Error('Download failed: ' + response.status);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url;
    link.download = 'BENFRANK_' + currentJob.job_id + (kind === 'receipt' ? '_receipt.json' : '_evidence.zip');
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (error) { setStatus(error.message); }
}
$('receipt').addEventListener('click', () => download('receipt'));
$('artifacts').addEventListener('click', () => download('artifacts'));
fetch('/health').then(async response => {
  const health = await response.json();
  $('health').textContent = response.ok && health.status === 'ok' ? 'Service ready' : 'Service needs setup';
}).catch(() => { $('health').textContent = 'Service unavailable'; });
