"""Versioned public NBA release mirror fallback for datacenter-blocked NBA APIs.

Source files come from public SportsDataverse release assets, and remain
SECONDARY_REPUBLISHED_NBA_SOURCE or ESPN_SECONDARY, not direct NBA CDN success.
The filtered Parquet files are strictly before the requested game date.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPOSITORY="sportsdataverse/sportsdataverse-data"
BASE="https://api.github.com/repos/"+REPOSITORY+"/releases/tags/"
MIRRORS={
 "espn_nba_player_boxscores":("player_box_2027.parquet","ESPN_SECONDARY"),
 "espn_nba_team_boxscores":("team_box_2027.parquet","ESPN_SECONDARY"),
 "espn_nba_shots":("shots_2027.parquet","ESPN_SECONDARY"),
 "espn_nba_pbp":("play_by_play_2027.parquet","ESPN_SECONDARY"),
 "espn_nba_game_rosters":("game_rosters_2027.parquet","ESPN_SECONDARY"),
 "espn_nba_rosters":("rosters_2027.parquet","ESPN_SECONDARY"),
 "espn_nba_team_season_stats":("team_season_stats_2027.parquet","ESPN_SECONDARY"),
 "nba_stats_game_lineups":("nba_lineups_2027.parquet","NBA_STATS_PUBLIC_THIRD_PARTY_MIRROR"),
 "nba_stats_possessions":("nba_possessions_2027.parquet","NBA_STATS_PUBLIC_THIRD_PARTY_MIRROR"),
 "nba_stats_pbp":("nba_play_by_play_2027.parquet","NBA_STATS_PUBLIC_THIRD_PARTY_MIRROR")
}
DATE_COLS=("game_date","game_date_est","game_date_eastern",
           "date","start_date","game_date_time","game_date_time_utc")
ALLOWED_REDIRECTS={"github.com","release-assets.githubusercontent.com",
                    "objects.githubusercontent.com"}
MAX_BYTES=22_000_000

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()
def httpget(url,limit=MAX_BYTES,github_api=False,fetch=None):
    parsed=urlparse(url)
    expected=("api.github.com" if github_api else "github.com")
    if parsed.scheme!="https" or parsed.hostname!=expected or parsed.username or parsed.password:
        raise ValueError("UNTRUSTED_RELEASE_URL")
    if fetch is not None:
        status,returned,raw=fetch(url,limit)
    else:
        headers={"User-Agent":"BENFRANK-NBA-Third-Party-Mirror/5.1","Accept":"application/json" if github_api else "*/*"}
        token=os.environ.get("GITHUB_TOKEN","")
        if github_api and token:headers["Authorization"]="Bearer "+token
        req=urllib.request.Request(url,headers=headers)
        with urllib.request.urlopen(req,timeout=25) as resp:
            status=resp.status
            returned=resp.geturl()
            raw=resp.read(limit+1)
    dest=urlparse(returned)
    allowed={"api.github.com"} if github_api else ALLOWED_REDIRECTS
    if dest.scheme!="https" or dest.hostname not in allowed:
        raise ValueError("UNEXPECTED_RELEASE_REDIRECT_HOST")
    if status!=200 or not raw or len(raw)>limit:
        raise ValueError("RELEASE_HTTP_UNAVAILABLE_OR_OVERSIZED")
    return raw

def identify_asset(tag,release):
    if tag not in MIRRORS:raise ValueError("SOURCE_NOT_ON_PUBLIC_RELEASE_ALLOWLIST")
    filename,_=MIRRORS[tag]
    assets=[a for a in release.get("assets",[]) if a.get("name")==filename]
    if len(assets)!=1:raise ValueError("MISSING_OR_AMBIGUOUS_2027_RELEASE_ASSET")
    asset=assets[0]
    expected="https://github.com/"+REPOSITORY+"/releases/download/"+tag+"/"+filename
    if asset.get("browser_download_url")!=expected:
        raise ValueError("UNEXPECTED_RELEASE_ASSET_URL")
    if not isinstance(asset.get("size"),int) or not 0<asset["size"]<=MAX_BYTES:
        raise ValueError("RELEASE_ASSET_SIZE_OUTSIDE_POLICY")
    return asset

def date_asof(value):
    import datetime
    if value is None:raise ValueError("NULL_OR_UNPARSEABLE_SOURCE_GAME_DATE")
    if isinstance(value,datetime.datetime):
        if value.tzinfo is None:
            return value.date()
        return value.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
    if isinstance(value,datetime.date):return value
    s=str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",s[:10]):
        return datetime.date.fromisoformat(s[:10])
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}",s[:10]):
        return datetime.datetime.strptime(s[:10],"%m/%d/%Y").date()
    raise ValueError("NULL_OR_UNPARSEABLE_SOURCE_GAME_DATE")

def qualify_asof(raw,target_date,output):
    import pyarrow as pa
    import pyarrow.parquet as pq
    target=dt.date.fromisoformat(target_date)
    table=pq.read_table(pa.BufferReader(raw))
    if table.num_rows<1:raise ValueError("EMPTY_MIRROR_PARQUET")
    candidate=next((k for k in DATE_COLS if k in table.column_names),None)
    if candidate is None:
        return {"status":"NO_ROW_DATE_CANNOT_USE_AS_PREGAME_FEATURE",
                "raw_rows":table.num_rows,"rows_before_cutoff":0,
                "date_column":None,
                "all_columns":table.column_names[:40]}
    col=table[candidate].to_pylist()
    mask=[];invalid=0
    for item in col:
        try:
            mask.append(date_asof(item)<target)
        except (ValueError,TypeError):
            mask.append(False);invalid+=1
    clean=table.filter(pa.array(mask))
    # Zero eligible rows is evidence of no safe previous games, not a success.
    if clean.num_rows>0:
        pq.write_table(clean,str(output))
    return {"status":"ASOF_ROW_FILTERED" if clean.num_rows>0
                       else "NO_ELIGIBLE_PRIOR_GAME_ROWS",
            "raw_rows":table.num_rows,"rows_before_cutoff":clean.num_rows,
            "rows_on_after_or_unparseable":table.num_rows-clean.num_rows,
            "unparseable_date_rows":invalid,"date_column":candidate,
            "all_columns":table.column_names[:40]}

def capture(tag,day,root,fetch=None):
    if tag not in MIRRORS:raise ValueError("NONALLOWLISTED_MIRROR_FAMILY")
    dt.date.fromisoformat(day)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    filename,tier=MIRRORS[tag]
    report={"tag":tag,"filename":filename,"source_tier":tier,
            "requested_asof_game_date":day,
            "observed_at_utc":utc(),"status":"BLOCKED",
            "official_direct_fetch":False,"model_certified":False,
            "historical_prop_snapshot_authenticated":False}
    try:
        response=httpget(BASE+tag,limit=1_500_000,github_api=True,fetch=fetch)
        release=json.loads(response)
        asset=identify_asset(tag,release)
        raw=httpget(asset["browser_download_url"],limit=MAX_BYTES,fetch=fetch)
        sha=hashlib.sha256(raw).hexdigest()
        raw_name=tag+"_"+sha[:12]+".raw.parquet"
        (root/raw_name).write_bytes(raw)
        filtered_name=tag+"_"+sha[:12]+".asof.parquet"
        qual=qualify_asof(raw,day,root/filtered_name)
        report.update(status="CAPTURED_MIRROR_ASOF_FILTERED"
                      if qual["status"]=="ASOF_ROW_FILTERED"
                      else "CAPTURED_MIRROR_NO_SAFE_ROW_EVIDENCE",
                      asset_id=asset.get("id"),asset_updated_at=asset.get("updated_at"),
                      source_url=asset["browser_download_url"],
                      source_sha256=sha,raw_file=raw_name,
                      filtered_file=filtered_name if qual["status"]=="ASOF_ROW_FILTERED" else None,
                      bytes=len(raw),quality=qual,
                      source_attribution="sportsdataverse/sportsdataverse-data")
    except (ValueError,TypeError,KeyError,OSError,urllib.error.URLError,TimeoutError,
            json.JSONDecodeError,ImportError) as exc:
        report["error"]=type(exc).__name__+":"+str(exc)[:190]
    return report
def collect(day,output,fetch=None,tags=None):
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    selected=list(MIRRORS) if tags is None else tags
    results=[]
    for tag in selected:
        try:r=capture(tag,day,root,fetch=fetch)
        except ValueError as exc:
            r={"tag":tag,"status":"BLOCKED","error":str(exc)}
        results.append(r)
        print(json.dumps({"tag":tag,"status":r["status"],
                          "safe_rows":(r.get("quality") or {}).get("rows_before_cutoff",0)}),flush=True)
    receipt={"status":"PUBLIC_MIRRORS_CHECKED","captured":sum(r["status"].startswith("CAPTURED_") for r in results),
             "asof_qualified":sum(r["status"]=="CAPTURED_MIRROR_ASOF_FILTERED" for r in results),
             "blocked":sum(r["status"]=="BLOCKED" for r in results),
             "source_version":"NBA 2026-27 third-party 2027-ending-season assets",
             "scope":"HISTORICAL_ROWS_BEFORE_TARGET_ONLY",
             "source_tiers_are_not_official_DIRECT":True,
             "asof_game_date":day,"sources":results,"prediction_certification":"NOT_CERTIFIED",
             "ticket_authority":"NO_TICKET"}
    (root/"v51-mirror-fallback-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--tags",nargs="+",choices=list(MIRRORS))
    a=p.parse_args()
    r=collect(a.date,a.output,tags=a.tags)
    print(json.dumps({k:r[k] for k in ("captured","asof_qualified","blocked",
                                      "prediction_certification")},indent=2))
    return 0 if r["asof_qualified"] else 2
if __name__=="__main__":
    raise SystemExit(main())
