"""Preserve official historical injury PDFs issued before archived line captures.

Printed report time is validated against its official URL and the line cutoff.
No missing/unlisted/not-submitted player is inferred healthy. No roster is filled.
"""
import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from benfrank_v44_calibration import instant
from benfrank_v45_evidence import digest, readonly, write_json

EASTERN = ZoneInfo("America/New_York")


def report_url(time):
    local = instant(time).astimezone(EASTERN)
    if local.minute % 15 or local.second or local.microsecond:
        raise ValueError("OFFICIAL_REPORT_QUARTER_HOUR_REQUIRED")
    return "https://ak-static.cms.nba.com/referee/injury/Injury-Report_" + local.strftime("%Y-%m-%d_%I_%M%p") + ".pdf"


def report_times(cutoff):
    local = (instant(cutoff) - dt.timedelta(minutes=15)).astimezone(EASTERN)
    local = local.replace(minute=local.minute // 15 * 15, second=0, microsecond=0)
    return [(local - dt.timedelta(minutes=m)).astimezone(dt.timezone.utc) for m in (0, 15, 45)]


def validate_header(text, expected, cutoff):
    found = re.search(r"Injury Report:\s*(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2})\s+(AM|PM)", text)
    if not found:
        raise ValueError("OFFICIAL_PRINTED_REPORT_TIMESTAMP_MISSING")
    printed = dt.datetime.strptime(" ".join(found.groups()), "%m/%d/%y %I:%M %p").replace(tzinfo=EASTERN)
    if printed.astimezone(dt.timezone.utc) != instant(expected):
        raise ValueError("OFFICIAL_PRINTED_REPORT_TIME_DIFFERS_FROM_URL")
    if printed.astimezone(dt.timezone.utc) >= instant(cutoff):
        raise ValueError("OFFICIAL_REPORT_NOT_AVAILABLE_BY_LINE_CUTOFF")
    return printed.astimezone(dt.timezone.utc).isoformat()


def capture_before(cutoff, root):
    attempts = []
    for time in report_times(cutoff):
        url = report_url(time)
        target = root / url.rsplit("/", 1)[1]
        attempt = {"url": url, "report_time_utc": time.isoformat()}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "BENFRANK-NBA-Evidence/4.6"})
            retrieved = dt.datetime.now(dt.timezone.utc).isoformat()
            with urllib.request.urlopen(request, timeout=18) as response:
                raw = response.read(3_000_001)
                attempt["http_status"] = response.status
            if not raw.startswith(b"%PDF-") or len(raw) > 3_000_000:
                raise ValueError("BOUNDED_ORIGINAL_OFFICIAL_PDF_REQUIRED")
            try:
                with target.open("xb") as stream:
                    stream.write(raw)
            except FileExistsError:
                if target.read_bytes() != raw:
                    raise ValueError("ORIGINAL_OFFICIAL_REPORT_CHANGED_DURING_CAPTURE")
            process = subprocess.run(["pdftotext", "-layout", str(target), "-"], text=True,
                                     capture_output=True, timeout=15, check=True)
            printed = validate_header(process.stdout, time, cutoff)
            text_path = target.with_suffix(".txt")
            text_path.write_text(process.stdout)
            return {"status": "PRESERVED_ORIGINAL_OFFICIAL_PREGAME_REPORT", "line_cutoff_utc": cutoff,
                "source": "NBA_OFFICIAL_INJURY_PDF", "url": url, "report_time_utc": printed,
                "retrieved_at": retrieved, "file": target.name, "sha256": digest(target),
                "text_file": text_path.name, "text_sha256": digest(text_path),
                "prior_failed_attempts": attempts,
                "unlisted_player_status": "UNKNOWN_NOT_CLEARED", "not_submitted_team_status": "UNKNOWN",
                "warning": "Printed official publication time is distinct from today's retrieval time. This is not a final availability or starting-lineup confirmation."}
        except urllib.error.HTTPError as exc:
            attempt.update(status="UNAVAILABLE", http_status=exc.code)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            attempt.update(status="UNAVAILABLE_OR_UNVERIFIED", error=type(exc).__name__ + ": " + str(exc)[:180])
        attempts.append(attempt)
    return {"status": "BLOCKED_NO_VERIFIED_OFFICIAL_REPORT", "line_cutoff_utc": cutoff, "attempts": attempts}


def collection_status(requested, verified):
    if not verified:
        return "BLOCKED_NO_VERIFIED_OFFICIAL_REPORTS"
    return "PRESERVED_OFFICIAL_PREGAME_DOCUMENTS" if verified == requested else "PARTIAL_OFFICIAL_PREGAME_DOCUMENTS"


def collect(ledger, out_dir):
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    before = digest(ledger)
    conn = readonly(ledger)
    try:
        cutoffs = [r[0] for r in conn.execute("SELECT DISTINCT captured_at FROM exact_line_snapshots ORDER BY captured_at")]
    finally:
        conn.close()
    if len(cutoffs) > 100:
        raise ValueError("AT_MOST_100_DISTINCT_CAPTURE_TIMES_PER_BATCH")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results.extend(pool.map(lambda cutoff: capture_before(cutoff, out), cutoffs))
    verified = sum(r["status"] == "PRESERVED_ORIGINAL_OFFICIAL_PREGAME_REPORT" for r in results)
    report = {"status": collection_status(len(cutoffs), verified), "requested_capture_cutoffs": len(cutoffs),
              "verified_documents": verified,
              "reports": results, "ledger_unchanged": before == digest(ledger),
              "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "player_availability_inferred": False, "rotation_forecasts_verified": False}
    write_json(out / "official-injury-captures.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    result = collect(args.ledger, args.out_dir)
    print(json.dumps({k: v for k, v in result.items() if k != "reports"}, indent=2))


if __name__ == "__main__":
    main()
