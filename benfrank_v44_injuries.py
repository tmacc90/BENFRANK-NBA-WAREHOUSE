"""Timestamped ESPN NBA injury observations (secondary, not official NBA authority).

Absence of an athlete from the feed does NOT imply healthy or cleared to play.
No current feed is ever used as if it were a past pregame snapshot.
"""
import argparse
import datetime as dt
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

URL="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

def normalize(payload):
    injuries=payload.get("injuries")
    if not isinstance(injuries,list):
        raise ValueError("Injuries feed missing list; cannot infer availability")
    rows=[]
    for group in injuries:
        if not isinstance(group,dict):
            continue
        team=(group.get("team") or {}).get("abbreviation") or None
        reports=group.get("injuries") if isinstance(group.get("injuries"),list) else [group]
        for item in reports:
            if not isinstance(item,dict):
                continue
            athlete=item.get("athlete") or {}
            name=athlete.get("displayName") or athlete.get("fullName")
            if not name:
                continue
            injury_type=item.get("type") or {}
            if isinstance(injury_type,dict):
                injury_type=injury_type.get("name") or injury_type.get("description")
            status=item.get("status")
            if isinstance(status,dict):
                status=status.get("name") or status.get("description")
            rows.append({"player":name,
                         "player_id":str(athlete.get("id")) if athlete.get("id") is not None else None,
                         "team":team or (athlete.get("team") or {}).get("abbreviation"),
                         "status":status,"injury_type":injury_type,
                         "reported_date":item.get("date"),"description":item.get("details") or item.get("comment")})
    return rows

def fetch(opener=None):
    opener=opener or urllib.request.urlopen
    observed=dt.datetime.now(dt.timezone.utc).isoformat()
    receipt={"source":"ESPN_SECONDARY","endpoint":URL,"observed_at":observed,
             "status":"UNAVAILABLE","injuries":[],"official_authority":False,
             "unlisted_players_status":"UNKNOWN_NOT_CLEARED"}
    try:
        req=urllib.request.Request(URL,headers={"User-Agent":"BENFRANK-NBA-DataAudit/1.0",
                                               "Accept":"application/json"})
        with opener(req,timeout=18) as response:
            body=response.read(3_000_001)
            status=response.status
        receipt["http_status"]=status
        if len(body)>3_000_000:
            raise ValueError("Injury feed too large")
        data=json.loads(body)
        entries=normalize(data)
        receipt.update(status="RETRIEVED_SECONDARY",injuries=entries,
                       record_count=len(entries),
                       body_sha256=hashlib.sha256(body).hexdigest(),
                       provider_timestamp=data.get("timestamp"))
    except urllib.error.HTTPError as exc:
        receipt.update(http_status=exc.code,error="HTTP "+str(exc.code))
    except (urllib.error.URLError,TimeoutError,ValueError,TypeError,OSError) as exc:
        receipt["error"]=type(exc).__name__+": "+str(exc)[:300]
    return receipt

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="receipts/injury_report.json")
    p.add_argument("--strict",action="store_true")
    a=p.parse_args()
    r=fetch()
    path=Path(a.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(r,indent=2)+"\n")
    print(json.dumps({"status":r["status"],"observed_at":r["observed_at"],
                      "records":len(r["injuries"]),
                      "http_status":r.get("http_status"),
                      "official_authority":False},indent=2))
    if a.strict and r["status"]!="RETRIEVED_SECONDARY":
        raise SystemExit(2)

if __name__=="__main__":
    main()
