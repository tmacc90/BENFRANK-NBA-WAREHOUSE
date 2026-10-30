"""Capture a CURRENT original NBA injury report without inferring availability.

An original official PDF is evidence only after retrieval and printed-time
verification. Never backdate a live retrieval to the PDF's publication time;
missing/unlisted players are never assumed healthy or playing.
"""
import argparse
import collections
import datetime as dt
import json
from pathlib import Path

from benfrank_v44_calibration import instant
from benfrank_v45_evidence import write_json
from benfrank_v46_official_injuries import capture_before
from benfrank_v47_availability import parse_pdf

UTC=dt.timezone.utc

def collect(cutoff, out_dir):
    instant_cutoff=instant(cutoff)
    current=dt.datetime.now(UTC)
    if instant_cutoff>current+dt.timedelta(minutes=1):
        raise ValueError("FUTURE_REPORT_CUTOFF_NOT_ALLOWED")
    if instant_cutoff<current-dt.timedelta(hours=24):
        raise ValueError("CURRENT_CAPTURE_CANNOT_BE_HISTORICALLY_BACKDATED")
    root=Path(out_dir).resolve()
    root.mkdir(parents=True,exist_ok=True)
    report=capture_before(instant_cutoff.isoformat(),root)
    summary={"source":"NBA_OFFICIAL_ORIGINAL_INJURY_PDF",
             "cutoff_utc":instant_cutoff.isoformat(),
             "status":"BLOCKED_OFFICIAL_REPORT_UNAVAILABLE",
             "current_retrieval_only":True,
             "report_to_use_asof_no_earlier_than_actual_retrieval":True,
             "unlisted_player_status":"UNKNOWN_NOT_CLEARED",
             "not_submitted_team_status":"UNKNOWN",
             "official_starter_confirmation":False,
             "rotation_minutes_verified":False,
             "certification":"NOT_CERTIFIED",
             "ticket_authority":"NO_TICKET",
             "report":report}
    if report.get("status")=="PRESERVED_ORIGINAL_OFFICIAL_PREGAME_REPORT":
        try:
            parsed=parse_pdf(root/report["file"], report["report_time_utc"], cutoff)
            groups=parsed["game_team_reports"]
            states=collections.Counter()
            submissions=collections.Counter()
            for group in groups.values():
                submissions[group["submission_status"]]+=1
                for player in group["players"].values():
                    states[player["status"]]+=1
            summary.update(
                status="OFFICIAL_PDF_PARSED_WITH_ISSUES" if parsed["issues"] else "OFFICIAL_PDF_PARSED",
                parsed_report_count=1, game_team_reports=len(groups),
                listed_player_status_counts=dict(states),
                submission_status_counts=dict(submissions),
                parser_issues=parsed["issues"],
                original_pdf_sha256=report["sha256"],
                report_time_utc=report["report_time_utc"],
                retrieved_at=report["retrieved_at"],
                availability_asof_not_before=report["retrieved_at"])
        except (ValueError,KeyError,TypeError,OSError) as exc:
            summary["status"]="OFFICIAL_PDF_PARSE_FAILED"
            summary["parse_error"]=type(exc).__name__+": "+str(exc)[:250]
    else:
        summary["source_outage_diagnostics"]=report.get("attempts")
    # Compatible with the existing v4.7 original-report archive reader.
    write_json(root/"official-injury-captures.json",
               {"status":"PRESERVED_OFFICIAL_PREGAME_DOCUMENTS" if summary["status"].startswith("OFFICIAL_PDF_PARSED") else
                "BLOCKED_NO_VERIFIED_OFFICIAL_REPORTS",
                "requested_capture_cutoffs":1,
                "verified_documents":int(report.get("status")=="PRESERVED_ORIGINAL_OFFICIAL_PREGAME_REPORT"),
                "reports":[report],
                "certification":"NOT_CERTIFIED",
                "player_availability_inferred":False,
                "rotation_forecasts_verified":False})
    write_json(root/"live-official-injury-receipt.json",summary)
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir",required=True)
    p.add_argument("--cutoff",help="Optional current UTC timestamp. Never reconstruct a past cutoff.")
    p.add_argument("--require-report",action="store_true")
    args=p.parse_args()
    cutoff=args.cutoff or dt.datetime.now(UTC).isoformat()
    result=collect(cutoff,args.output_dir)
    print(json.dumps({k:v for k,v in result.items()
                      if k not in ("report","parser_issues","source_outage_diagnostics")},indent=2))
    return 0 if result["status"]=="OFFICIAL_PDF_PARSED" or not args.require_report else 2

if __name__=="__main__":
    raise SystemExit(main())
