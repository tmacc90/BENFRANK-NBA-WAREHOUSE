"""Best-effort public PrizePicks secondary snapshot; NEVER native authenticated.

Tracks the most recent original GitHub collector commit and response hashes.
If no contemporaneous pregame rows exist, records NO_CURRENT_LINES rather than
inventing exact thresholds or using stale snapshot rows for today's bets.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from benfrank_v46_public_lines import (
    REPOSITORY,SOURCE_PATH,SOURCE_TIER,normalize,source_url,read_url
)
URL="https://api.github.com/repos/"+REPOSITORY+"/commits?path="+SOURCE_PATH+"&per_page=1"
def recent_commit(fetch=None):
    if fetch is None:
        req=urllib.request.Request(URL,headers={
            "User-Agent":"BENFRANK-NBA-Secondary-Research/5.1","Accept":"application/vnd.github+json"})
        with urllib.request.urlopen(req,timeout=12) as resp:
            if resp.status!=200 or resp.geturl()!=URL:
                raise ValueError("UNTRUSTED_COLLECTOR_GITHUB_COMMIT_SOURCE")
            raw=resp.read(400001)
    else:raw=fetch(URL)
    if len(raw)>400000 or not raw:raise ValueError("COLLECTOR_COMMIT_PAYLOAD_UNAVAILABLE")
    items=json.loads(raw)
    if not isinstance(items,list) or not items:raise ValueError("NO_CAPTURE_REVISIONS_AVAILABLE")
    head=items[0]
    sha=head.get("sha")
    stamp=((head.get("commit") or {}).get("committer") or {}).get("date")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha):
        raise ValueError("INVALID_COLLECTOR_COMMIT_SHA")
    if not isinstance(stamp,str):
        raise ValueError("COLLECTOR_COMMIT_TIME_MISSING")
    parsed=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
    if parsed.tzinfo is None:raise ValueError("COLLECTOR_COMMIT_TIME_NOT_UTC")
    return sha,stamp
def collect(target_date,output,commit_fetch=None,raw_fetch=None):
    dt.date.fromisoformat(target_date)
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    receipt={"source":"ENKDAY_PUBLIC_PRIZEPICKS_COLLECTOR",
             "authority":SOURCE_TIER,"requested_date":target_date,
             "collection_time_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
             "status":"BLOCKED","current_date_pregame_rows":0,
             "native_platform_attestation":False,"ticket_authority":"NO_TICKET",
             "prediction_certification":"NOT_CERTIFIED"}
    try:
        sha,committed=recent_commit(commit_fetch)
        url=source_url(sha)
        raw=read_url(url) if raw_fetch is None else raw_fetch(url)
        if not raw or len(raw)>8_000_000:raise ValueError("NO_VALID_COLLECTOR_CAPTURE_BODY")
        digest=hashlib.sha256(raw).hexdigest()
        content_name="public-collector-"+sha+".json"
        (root/content_name).write_bytes(raw)
        source_receipt={"repository":REPOSITORY,"path":SOURCE_PATH,
                        "commit_sha":sha,"committed_at":committed,
                        "source_url":url,"raw_sha256":digest,
                        "retrieved_at":dt.datetime.now(dt.timezone.utc).isoformat(),
                        "source_tier":SOURCE_TIER}
        receipt_name="public-collector-"+sha+".receipt.json"
        data=json.dumps(source_receipt,indent=2)+"\n"
        (root/receipt_name).write_text(data)
        receipt_sha256=hashlib.sha256(data.encode()).hexdigest()
        rows,rejected=normalize(json.loads(raw),source_receipt,
                                 content_name,receipt_name,receipt_sha256)
        current=[r for r in rows if r["game_date"]==target_date]
        receipt.update(status="SECONDARY_PREGAME_ROWS_CAPTURED" if current
                       else "NO_CURRENT_SECONDARY_PREGAME_LINES",
                       commit_sha=sha,source_sha256=digest,
                       collector_captured_at=(json.loads(raw).get("scrapedAt")),
                       raw_file=content_name,source_receipt_file=receipt_name,
                       all_valid_source_rows=len(rows),
                       current_date_pregame_rows=len(current),
                       rejected=dict(rejected))
        (root/"current-date-line-snapshots.json").write_text(
            json.dumps(current,indent=2)+"\n")
    except (urllib.error.HTTPError,urllib.error.URLError,
            ValueError,KeyError,TypeError,OSError,TimeoutError,
            json.JSONDecodeError) as exc:
        receipt["error"]=type(exc).__name__+":"+str(exc)[:220]
    (root/"secondary-line-source-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    r=collect(a.date,a.output)
    print(json.dumps({k:r[k] for k in
          ("status","current_date_pregame_rows","native_platform_attestation")},indent=2))
    return 0 if r["status"]=="SECONDARY_PREGAME_ROWS_CAPTURED" else 2
if __name__=="__main__":
    raise SystemExit(main())
