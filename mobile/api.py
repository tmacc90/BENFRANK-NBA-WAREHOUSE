"""Mobile API adapter for existing BENFRANK auto runner.

Run: pip install fastapi uvicorn python-multipart
     BENFRANK_API_TOKEN=<secret> uvicorn mobile.api:app --host 127.0.0.1 --port 8000
Expose only behind authenticated HTTPS reverse proxy. No arbitrary commands or paths.
"""
import datetime as dt
import json
import os
import secrets
import threading
import uuid
from pathlib import Path
from fastapi import FastAPI, Form, Header, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from benfrank_auto_runner import run

app = FastAPI(title="BENFRANK mobile API")
ROOT = Path(os.environ.get("BENFRANK_MOBILE_RUNS", "mobile_runs")).resolve()
JOBS = {}
LOCK = threading.Lock()
MAX_IMAGE = 8 * 1024 * 1024

def authorize(authorization):
    token = os.environ.get("BENFRANK_API_TOKEN")
    if not token:
        raise HTTPException(503, "SERVER_TOKEN_NOT_CONFIGURED")
    if not authorization or not secrets.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(401, "UNAUTHORIZED")

def worker(job_id, day, player, market, line):
    folder = ROOT / job_id
    config = folder / "request.json"
    try:
        config.write_text(json.dumps({"mode":"future_discovery","game_date":day,
            "max_props":25,"max_games":15}, indent=2))
        result, code = run(str(config), str(folder / "execution"),
                           str(ROOT / "state"), 25000, 2000)
        # Existing discovery cannot guarantee the user-specified exact line.
        props = result.get("props", []) if isinstance(result, dict) else []
        matched = [p for p in props if
                   str(p.get("prop",{}).get("player","")).casefold()==player.casefold()
                   and str(p.get("prop",{}).get("market","")).casefold()==market.casefold()
                   and p.get("prop",{}).get("line")==line]
        with LOCK:
            JOBS[job_id] = {"status":"completed" if matched and code==0 else "incomplete",
                "exit_code":code,"matched_exact_prop":bool(matched),
                "matched_results":matched,
                "reason":None if matched else "EXACT_UPLOADED_PROP_NOT_FOUND_ON_NATIVE_BOARD",
                "execution_receipt":{"verified":False,"path":str(folder/"execution")}}
    except Exception as exc:
        with LOCK:
            JOBS[job_id]={"status":"failed","error":type(exc).__name__ + ": " + str(exc),
                          "execution_receipt":{"verified":False}}

@app.get("/health")
def health():
    return {"status":"ok","backend":"BENFRANK_AUTO","execution_verified":False}

@app.post("/api/run-framework", status_code=202)
async def submit(player: str=Form(...), market: str=Form(...), line:float=Form(...),
                 pregame_cutoff:str=Form(...), screenshot:UploadFile|None=File(None),
                 authorization:str|None=Header(None)):
    authorize(authorization)
    if screenshot is not None:
        raise HTTPException(422,"SCREENSHOT_EXTRACTION_NOT_IMPLEMENTED_USE_MANUAL_FIELDS")
    if not player.strip() or not market.strip() or not 0<=line<=10000:
        raise HTTPException(422,"INVALID_PROP")
    try:
        cutoff=dt.datetime.fromisoformat(pregame_cutoff.replace("Z","+00:00"))
        if cutoff.tzinfo is None: raise ValueError()
    except ValueError:
        raise HTTPException(422,"TIMEZONE_AWARE_CUTOFF_REQUIRED")
    now=dt.datetime.now(dt.timezone.utc)
    if cutoff.astimezone(dt.timezone.utc)<=now:
        raise HTTPException(422,"PREGAME_CUTOFF_IN_PAST")
    day=cutoff.date().isoformat()
    ROOT.mkdir(parents=True,exist_ok=True)
    job_id=uuid.uuid4().hex
    (ROOT/job_id).mkdir(mode=0o700)
    with LOCK: JOBS[job_id]={"status":"queued","execution_receipt":{"verified":False}}
    threading.Thread(target=worker,args=(job_id,day,player.strip(),market.strip(),line),daemon=True).start()
    return {"job_id":job_id,"status":"queued","poll":"/api/jobs/"+job_id,
            "execution_receipt":{"verified":False}}

@app.get("/api/jobs/{job_id}")
def status(job_id:str,authorization:str|None=Header(None)):
    authorize(authorization)
    with LOCK:
        if job_id not in JOBS: raise HTTPException(404,"UNKNOWN_JOB")
        return dict(JOBS[job_id],job_id=job_id)
