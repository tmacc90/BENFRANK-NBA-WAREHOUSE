"""Reverify a saved original NBA warehouse ZIP without modifying either warehouse.

Uses pinned original official LeagueGameLog JSON response bytes, not network calls
that may return 403 or time out. This attests only historical selected seasons.
"""
import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from benfrank_v46_saved_history import audit_saved_history

REQUIRED = (
    "nba_warehouse.sqlite",
    "DELIVERY_MANIFEST.json",
    "official_evidence/fresh_stats/fetch_receipt.json",
    "official_evidence/fresh_stats/league_2024-25.json",
    "official_evidence/fresh_stats/league_2025-26.json",
)
MAX_UNCOMPRESSED = 850_000_000

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def verified_extract(archive,destination):
    destination=Path(destination)
    with zipfile.ZipFile(archive) as zipped:
        names=zipped.namelist()
        if len(names)!=len(set(names)):
            raise ValueError("DUPLICATE_ARCHIVE_ENTRIES")
        if any(name.startswith("/") or ".." in Path(name).parts or "\\" in name
               for name in names):
            raise ValueError("UNSAFE_ARCHIVE_PATH")
        if sum(info.file_size for info in zipped.infolist())>MAX_UNCOMPRESSED:
            raise ValueError("SOURCE_ARCHIVE_INFLATION_LIMIT")
        if not set(REQUIRED).issubset(names):
            raise ValueError("MISSING_ORIGINAL_OFFICIAL_RECEIPTS")
        for name in REQUIRED:
            dst=destination/name
            dst.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(name,"r") as inp,dst.open("wb") as out:
                shutil.copyfileobj(inp,out,1024*1024)
    return destination

def audit_archive(archive,expected_database_sha256,baseline=None):
    archive=Path(archive)
    if len(expected_database_sha256)!=64:
        raise ValueError("EXPECTED_PINNED_DATABASE_SHA256_REQUIRED")
    if not archive.is_file():
        raise FileNotFoundError("Original saved ZIP missing: "+str(archive))
    prior_hash=sha256(baseline) if baseline else None
    with tempfile.TemporaryDirectory(prefix="benfrank-official-archive-") as folder:
        package=verified_extract(archive,folder)
        manifest=json.loads((package/"DELIVERY_MANIFEST.json").read_text())
        dbhash=sha256(package/"nba_warehouse.sqlite")
        if dbhash!=expected_database_sha256 or manifest.get("database_sha256")!=dbhash:
            raise ValueError("ORIGINAL_WAREHOUSE_OR_MANIFEST_SHA256_MISMATCH")
        result=audit_saved_history(package,baseline)
    source_unchanged=(sha256(baseline)==prior_hash) if baseline else True
    scope={"status":"PASS_RESTORED_OFFICIAL_HISTORY_ONLY" if
                   (result["status"]=="PASS_COMPLETE_SELECTED_SEASONS" and source_unchanged)
                   else "FAIL_ARCHIVED_HISTORY_VERIFICATION",
           "archive_sha256":sha256(archive),
           "original_database_sha256":dbhash,
           "manifest":{key:manifest.get(key) for key in
                       ("database_rows","missing_official_records_in_selected_seasons",
                        "games","seasons","recovered_targets","unresolved_targets")},
           "saved_official_audit_status":result["status"],
           "saved_game_rows":result.get("warehouse_player_games"),
           "season_counts":[{"season":s.get("season"),"warehouse_records":s.get("warehouse_records"),
                             "official_records":s.get("official_records"),"status":s.get("status"),
                             "unmatched_official_count":len(s.get("missing_identities",[])),
                             "conflict_count":len(s.get("conflicts",[]))}
                            for s in result.get("seasons",[])],
           "baseline_comparison":{key:value for key,value in
               result.get("comparison_to_github_import",{}).items() if key not in
               ("missing_baseline_rows","different_baseline_rows")},
           "baseline_missing_or_changed_count":sum(len(result.get("comparison_to_github_import",{}).get(key,[]))
                        for key in ("missing_baseline_rows","different_baseline_rows")),
           "source_warehouse_unchanged":source_unchanged,
           "official_endpoint_access":"CACHED_ORIGINAL_DIRECT_NBA_RESPONSES_NOT_CURRENT_ACCESS",
           "live_source_availability":"NOT_VERIFIED",
           "production_prediction_certification":"NOT_CERTIFIED",
           "ticket_authority":"NO_TICKET",
           "note":"A complete archived 2024-25/2025-26 database may supersede a partial newer import for historical use only; never silently promote model certification."}
    if scope["baseline_missing_or_changed_count"]:
        scope["status"]="FAIL_HISTORICAL_BASELINE_CONFLICT"
    return scope

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",required=True)
    p.add_argument("--expected-database-sha256",required=True)
    p.add_argument("--baseline")
    p.add_argument("--out",required=True)
    args=p.parse_args()
    try:
        result=audit_archive(args.archive,args.expected_database_sha256,args.baseline)
    except (ValueError,KeyError,FileNotFoundError,zipfile.BadZipFile) as exc:
        result={"status":"FAIL_ARCHIVED_HISTORY_VERIFICATION","error":str(exc),
                "production_prediction_certification":"NOT_CERTIFIED","ticket_authority":"NO_TICKET"}
    path=Path(args.out)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return 0 if result["status"]=="PASS_RESTORED_OFFICIAL_HISTORY_ONLY" else 2

if __name__=="__main__":
    raise SystemExit(main())
