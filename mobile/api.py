"""Authenticated, single-job mobile adapter for the preserved NBA runner."""
import datetime as dt
import hashlib
import json
import math
import os
import secrets
import tempfile
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from acquire_history import name_key
from benfrank_auto_history import ET
from benfrank_auto_runner import run
from benfrank_v44_twon import MARKETS
from scripts.verify_auto_run import verify

ROOT = Path(os.environ.get('BENFRANK_MOBILE_RUNS', 'mobile_runs')).resolve()
JOBS = {}
LOCK = threading.RLock()
RUN_LOCK = threading.Lock()
TERMINAL = {'completed', 'incomplete', 'failed', 'interrupted'}
MAX_BODY = 16 * 1024


def clock():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def persist(job_id, payload):
    folder = ROOT / job_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    events = folder / 'events'
    events.mkdir(exist_ok=True, mode=0o700)
    data = json.dumps(payload, indent=2, allow_nan=False)
    # Events and requests are append-only; job.json is only a status index.
    with (events / (uuid.uuid4().hex + '.json')).open('x') as stream:
        stream.write(data)
    temporary = folder / 'job.tmp'
    with temporary.open('w') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(folder / 'job.json')


def set_job(job_id, payload):
    with LOCK:
        previous = JOBS.get(job_id)
        if previous is None and (ROOT / job_id / 'job.json').is_file():
            previous = json.loads((ROOT / job_id / 'job.json').read_text())
        updated = {**(previous or {}), **payload, 'updated_utc': clock()}
        persist(job_id, updated)
        JOBS[job_id] = updated


def recover_jobs():
    if not ROOT.exists():
        return
    for path in ROOT.glob('*/job.json'):
        if not valid_id(path.parent.name):
            continue
        payload = json.loads(path.read_text())
        if payload.get('status') in ('queued', 'running'):
            set_job(path.parent.name, dict(payload, status='interrupted',
                error='SERVER_RESTART_INTERRUPTED_JOB', execution_receipt={'verified': False}))


@asynccontextmanager
async def lifespan(app):
    recover_jobs()
    yield


app = FastAPI(title='BENFRANK mobile API', lifespan=lifespan, docs_url=None, redoc_url=None)


def authorize(authorization):
    token = os.environ.get('BENFRANK_API_TOKEN', '')
    if len(token) < 32 or not token.isascii():
        raise HTTPException(503, 'SERVER_TOKEN_NOT_CONFIGURED_OR_TOO_SHORT')
    supplied = (authorization or '').encode('utf8')
    if not secrets.compare_digest(supplied, ('Bearer ' + token).encode('ascii')):
        raise HTTPException(401, 'UNAUTHORIZED', headers={'WWW-Authenticate': 'Bearer'})


def storage_health():
    required = os.environ.get('BENFRANK_REQUIRE_PERSISTENT_STORAGE', '').lower() == 'true'
    # Only paths beneath a separately mounted disk qualify in deployment mode.
    mount = Path(os.environ.get('BENFRANK_PERSISTENT_MOUNT', '/var/lib/benfrank')).resolve()
    mounted = ROOT.is_relative_to(mount) and os.path.ismount(mount)
    try:
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryFile(dir=ROOT) as probe:
            probe.write(b'BENFRANK_STORAGE_PROBE')
            probe.flush()
            os.fsync(probe.fileno())
        writable = True
    except OSError:
        writable = False
    return {'writable': writable, 'persistent_mount_required': required,
            'persistent_mount_verified': mounted, 'ready': writable and (mounted or not required)}


@app.middleware('http')
async def protect_api(request: Request, call_next):
    try:
        if request.url.path.startswith('/api/') or request.url.path == '/openapi.json':
            authorize(request.headers.get('authorization'))
        if request.method == 'POST':
            # Reject oversized multipart data before the form parser allocates it.
            length = request.headers.get('content-length')
            if length and (not length.isdigit() or int(length) > MAX_BODY):
                raise HTTPException(413, 'REQUEST_BODY_TOO_LARGE')
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise HTTPException(413, 'REQUEST_BODY_TOO_LARGE')
            request._body = bytes(body)
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if request.url.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


@app.get('/')
def mobile_home():
    return FileResponse(Path(__file__).with_name('index.html'))


@app.get('/mobile.js')
def mobile_script():
    return FileResponse(Path(__file__).with_name('app.js'), media_type='text/javascript')


@app.get('/mobile.css')
def mobile_style():
    return FileResponse(Path(__file__).with_name('style.css'), media_type='text/css')


@app.get('/health')
def health():
    token = os.environ.get('BENFRANK_API_TOKEN', '')
    storage = storage_health()
    ready = len(token) >= 32 and token.isascii() and storage['ready']
    return JSONResponse({'status': 'ok' if ready else 'not_ready', 'backend': 'BENFRANK_AUTO',
        'token_configured': len(token) >= 32 and token.isascii(), 'storage': storage,
        'execution_verified': False}, status_code=200 if ready else 503)


def valid_id(job_id):
    return len(job_id) == 32 and all(c in '0123456789abcdef' for c in job_id)


def read_job(job_id):
    if not valid_id(job_id):
        raise HTTPException(404, 'UNKNOWN_JOB')
    with LOCK:
        job = JOBS.get(job_id)
        if job is None:
            path = ROOT / job_id / 'job.json'
            if not path.is_file():
                raise HTTPException(404, 'UNKNOWN_JOB')
            job = json.loads(path.read_text())
            if job['status'] in ('queued', 'running'):
                set_job(job_id, dict(job, status='interrupted', error='SERVER_RESTART_INTERRUPTED_JOB',
                                     execution_receipt={'verified': False}))
                job = JOBS[job_id]
        result = dict(job, job_id=job_id)
        if job.get('execution_receipt', {}).get('verified') and job.get('matched_results'):
            sid = job['matched_results'][0]['prop']['snapshot_id']
            path = ROOT / job_id / 'execution' / 'props' / sid / 'prediction.json'
            if path.is_file():
                prediction = json.loads(path.read_text())
                result['prediction_summary'] = {key: prediction[key] for key in (
                    'direction', 'projection', 'model_disagreement', 'scenario_side_flip', 'historical_windows')}
                result['prediction_summary'].update(
                    blind_projection=prediction['blind_model']['projection'],
                    p_over_raw=prediction['main_simulation']['p_over_raw'],
                    calibration_applied=False)
        return result


def package_artifacts(job_id):
    folder = ROOT / job_id
    temporary = folder / 'artifacts.tmp'
    target = folder / 'artifacts.zip'
    if target.exists():
        return target
    with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path not in (temporary, target):
                archive.write(path, str(path.relative_to(folder)))
    temporary.replace(target)
    return target


def worker(job_id, config):
    folder = ROOT / job_id
    try:
        set_job(job_id, {'status': 'running', 'started_utc': clock(), 'execution_receipt': {'verified': False}})
        result, code = run(str(folder / 'request.json'), str(folder / 'execution'),
                           str(ROOT / 'state'), 25000, 2000)
        requested = config['requested_prop']
        matched = [p for p in result.get('props', [])
                   if name_key(p.get('prop', {}).get('player', '')) == name_key(requested['player'])
                   and p.get('prop', {}).get('market') == requested['market']
                   and p.get('prop', {}).get('line') == requested['line']]
        verified, proof, reason = False, None, None
        if code == 0 and len(matched) == 1 and result.get('all_requested_props_executed') and result.get('preservation_verified'):
            try:
                proof = verify(folder / 'execution', ROOT / 'state')
                verified = True
            except Exception as exc:
                reason = 'ARTIFACT_VERIFICATION_FAILED:' + type(exc).__name__ + ': ' + str(exc)
        if not verified and reason is None:
            reason = result.get('fatal_blocker') or next(
                (p.get('exact_blocker') for p in matched if p.get('exact_blocker')),
                'EXACT_REQUESTED_PROP_EXECUTION_INCOMPLETE')
        verification_path = folder / 'verification.json'
        with verification_path.open('x') as stream:
            json.dump({'verified': verified, 'proof': proof, 'reason': reason}, stream, indent=2)
        receipt_path = folder / 'execution' / 'execution_receipt.json'
        digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest() if receipt_path.is_file() else None
        set_job(job_id, {'status': 'completed' if verified else 'incomplete', 'completed_utc': clock(),
            'exit_code': code, 'matched_exact_prop': len(matched) == 1, 'matched_results': matched,
            'reason': reason, 'artifact_verification': proof,
            'execution_receipt': {'verified': verified, 'sha256': digest,
                'url': '/api/jobs/' + job_id + '/receipt', 'pipeline_status': result.get('status')},
            'artifacts_url': '/api/jobs/' + job_id + '/artifacts'})
    except Exception as exc:
        set_job(job_id, {'status': 'failed', 'completed_utc': clock(),
            'error': type(exc).__name__ + ': ' + str(exc), 'execution_receipt': {'verified': False}})
    finally:
        RUN_LOCK.release()


@app.post('/api/run-framework', status_code=202)
async def submit(player: str = Form(...), market: str = Form(...), line: float = Form(...),
                 pregame_cutoff: str = Form(...), screenshot: UploadFile | None = File(None),
                 authorization: str | None = Header(None)):
    authorize(authorization)
    if screenshot is not None:
        raise HTTPException(422, 'SCREENSHOT_EXTRACTION_NOT_IMPLEMENTED_USE_MANUAL_FIELDS')
    player, market = player.strip(), market.strip().lower()
    if not player or len(player) > 120 or market not in MARKETS or not math.isfinite(line) or not 0 <= line <= 10000:
        raise HTTPException(422, 'INVALID_OR_UNSUPPORTED_PROP')
    try:
        cutoff = dt.datetime.fromisoformat(pregame_cutoff.replace('Z', '+00:00'))
        if cutoff.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'TIMEZONE_AWARE_CUTOFF_REQUIRED')
    if cutoff <= dt.datetime.now(dt.timezone.utc):
        raise HTTPException(422, 'PREGAME_CUTOFF_IN_PAST')
    if not storage_health()['ready']:
        raise HTTPException(503, 'PERSISTENT_STORAGE_NOT_READY')
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(429, 'ONE_FRAMEWORK_JOB_ALREADY_RUNNING', headers={'Retry-After': '30'})
    try:
        job_id = uuid.uuid4().hex
        folder = ROOT / job_id
        folder.mkdir(mode=0o700)
        config = {'mode': 'future_discovery', 'game_date': cutoff.astimezone(ET).date().isoformat(),
            'pregame_cutoff_utc': cutoff.astimezone(dt.timezone.utc).isoformat(),
            'requested_prop': {'player': player, 'market': market, 'line': line},
            'max_props': 1, 'max_games': 1, 'max_seasons': 3}
        with (folder / 'request.json').open('x') as stream:
            json.dump(config, stream, indent=2, allow_nan=False)
        set_job(job_id, {'status': 'queued', 'submitted_utc': clock(), 'request': config,
                         'execution_receipt': {'verified': False}})
        threading.Thread(target=worker, args=(job_id, config), daemon=True, name='benfrank-' + job_id).start()
    except Exception:
        RUN_LOCK.release()
        raise
    return {'job_id': job_id, 'status': 'queued', 'poll': '/api/jobs/' + job_id,
            'execution_receipt': {'verified': False}}


@app.get('/api/jobs/{job_id}')
def status(job_id: str):
    return read_job(job_id)


@app.get('/api/jobs/{job_id}/receipt')
def receipt(job_id: str):
    job = read_job(job_id)
    path = ROOT / job_id / 'execution' / 'execution_receipt.json'
    if job['status'] not in TERMINAL or not path.is_file():
        raise HTTPException(409, 'EXECUTION_RECEIPT_NOT_READY')
    return FileResponse(path, media_type='application/json', filename='BENFRANK_' + job_id + '_receipt.json')


@app.get('/api/jobs/{job_id}/artifacts')
def artifacts(job_id: str):
    job = read_job(job_id)
    if job['status'] not in TERMINAL:
        raise HTTPException(409, 'JOB_STILL_RUNNING')
    with LOCK:
        path = package_artifacts(job_id)
    return FileResponse(path, media_type='application/zip', filename='BENFRANK_' + job_id + '_evidence.zip')
