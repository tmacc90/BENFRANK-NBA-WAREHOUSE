"""BENFRANK multi-source evidence acquisition: provenance first, fail closed.

Fetches public endpoints without authentication, captures response hashes, source
timestamps and bounded raw evidence. HTTP 403/429 is a BLOCKED receipt, never a
reason to bypass restrictions. No claims of lineup or native sportsbook proof.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

UTC=dt.timezone.utc
SOURCES={
 "espn_scoreboard":{
   "category":"schedule_current_games",
   "url":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date}",
   "host":"site.api.espn.com","format":"json","max_bytes":3000000,
   "authority":"ESPN_SECONDARY","cadence":"daily"},
 "espn_teams":{
   "category":"league_roster_team_index",
   "url":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams",
   "host":"site.api.espn.com","format":"json","max_bytes":3000000,
   "authority":"ESPN_SECONDARY_ROSTER_INDEX","cadence":"daily"},
 "nba_cdn_schedule":{
   "category":"official_nba_season_schedule_game_ids",
   "url":"https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
   "host":"cdn.nba.com","format":"json","max_bytes":9000000,
   "authority":"NBA_CDN_OFFICIAL_SCHEDULE","cadence":"daily"},
 "espn_injuries":{
   "category":"injury_secondary",
   "url":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
   "host":"site.api.espn.com","format":"json","max_bytes":3000000,
   "authority":"ESPN_SECONDARY_NOT_OFFICIAL_INJURY_REPORT","cadence":"hourly"},
 "espn_news":{
   "category":"news_context",
   "url":"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news",
   "host":"site.api.espn.com","format":"json","max_bytes":3000000,
   "authority":"ESPN_EDITORIAL_NOT_OFFICIAL_LINEUP","cadence":"hourly"},
 "nba_cdn_scoreboard":{
   "category":"official_schedule_and_scores",
   "url":"https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json",
   "host":"cdn.nba.com","format":"json","max_bytes":3000000,
   "authority":"NBA_CDN_OFFICIAL_CURRENT_NOT_HISTORICAL","cadence":"hourly"},
 "nba_official_injury_index":{
   "category":"injury_primary_discovery",
   "url":"https://official.nba.com/nba-injury-report-2026-27-season/",
   "host":"official.nba.com","format":"html","max_bytes":1500000,
   "authority":"NBA_OFFICIAL_DISCOVERY_NOT_A_PARSED_PDF","cadence":"hourly"},
}
# Other useful sources require source-specific adapters or permission:
# NBA.com/stats: official advanced defense, tracking and shots; often rate-limited.
# PBP Stats: possessions, lineups, substitutions; verify terms and access.
# Basketball Reference, Stathead, Rotowire: no unauthorized bulk scraping.
# PrizePicks: native pregame capture requires authorized platform source and clock.
# NCAA/G League: rookie translated priors, not current NBA official outcomes.

def utc_now():
    return dt.datetime.now(UTC).isoformat()
def validate_url(url,host):
    p=urlparse(url)
    if p.scheme!="https" or p.hostname!=host or p.username or p.password or p.fragment:
        raise ValueError("UNTRUSTED_SOURCE_HOST")
    return url
def capture(name,day,out,fetch=None):
    if name not in SOURCES:raise ValueError("SOURCE_NOT_ALLOWLISTED")
    dt.date.fromisoformat(day)
    spec=SOURCES[name]
    url=validate_url(spec["url"].format(date=day.replace("-","")),spec["host"])
    start=utc_now()
    receipt={"source":name,"category":spec["category"],"url":url,
             "authority":spec["authority"],"requested_day":day,
             "started_at_utc":start,"status":"BLOCKED","sha256":None,
             "source_asof":None,"certified":False}
    try:
        if fetch is None:
            req=urllib.request.Request(url,headers={
                "User-Agent":"BENFRANK-NBA-Evidence-Collector/5.1 (research; contact repo owner)",
                "Accept":"application/json,text/html"})
            with urllib.request.urlopen(req,timeout=16) as res:
                status=res.status
                content_type=res.headers.get("Content-Type","")
                if not validate_url(res.geturl(),spec["host"]):
                    raise ValueError("UNTRUSTED_SOURCE_REDIRECT")
                raw=res.read(spec["max_bytes"]+1)
        else:
            status,content_type,raw=fetch(url,spec["max_bytes"])
        if status!=200:raise ValueError("HTTP_STATUS_"+str(status))
        if len(raw)>spec["max_bytes"]:raise ValueError("OVERSIZE_SOURCE_BODY")
        if not raw:raise ValueError("EMPTY_SOURCE_BODY")
        if spec["format"]=="json":
            if "json" not in content_type.lower():raise ValueError("NOT_JSON_CONTENT_TYPE")
            payload=json.loads(raw)
            if not isinstance(payload,(dict,list)):raise ValueError("NON_OBJECT_SOURCE_JSON")
        elif "html" not in content_type.lower():
            raise ValueError("NOT_HTML_CONTENT_TYPE")
        digest=hashlib.sha256(raw).hexdigest()
        filename=name+"_"+day+"_"+digest[:12]+(" .json" if spec["format"]=="json" else " .html")
        filename=filename.replace(" ","")
        out=Path(out);out.mkdir(parents=True,exist_ok=True)
        path=out/filename
        if path.exists() and path.read_bytes()!=raw:
            raise ValueError("IMMUTABLE_SOURCE_BODY_CONFLICT")
        path.write_bytes(raw)
        receipt.update(status="CAPTURED_UNVERIFIED",sha256=digest,
                       captured_at_utc=utc_now(),bytes=len(raw),
                       raw_file=filename,content_type=content_type)
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,
            ValueError,TypeError,json.JSONDecodeError,OSError) as exc:
        receipt["failure"]=type(exc).__name__+":"+str(exc)[:180]
    return receipt

def run(day,output,sources=None,fetch=None):
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    names=list(SOURCES) if sources is None else sources
    receipts=[capture(name,day,root,fetch=fetch) for name in names]
    report={"framework":"BENFRANK v5.1 source-capture evidence only",
            "run_at_utc":utc_now(),"requested_date":day,"sources":receipts,
            "captured":sum(r["status"]=="CAPTURED_UNVERIFIED" for r in receipts),
            "blocked":sum(r["status"]=="BLOCKED" for r in receipts),
            "original_official_injury_pdf_parsed":False,
            "final_lineup_confirmed":False,"authenticated_native_prop_lines":False,
            "possession_trials_executed":0,
            "certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    (root/"v51-source-receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    return report
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--date",default=dt.datetime.now(UTC).date().isoformat())
    p.add_argument("--output",required=True)
    p.add_argument("--sources",nargs="+",choices=list(SOURCES))
    a=p.parse_args()
    r=run(a.date,a.output,a.sources)
    print(json.dumps({k:r[k] for k in ("captured","blocked","certification")},indent=2))
    return 0 if r["captured"] else 2
if __name__=="__main__":
    raise SystemExit(main())
