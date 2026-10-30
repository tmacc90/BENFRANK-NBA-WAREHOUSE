"""Parse official dated injury tables into explicit, game-scoped observations.

Unlisted players and unsubmitted teams remain UNKNOWN. Table rows with ambiguous
names/statuses are retained as parsing issues, never silently converted to healthy.
"""
import argparse
import collections
import datetime as dt
import json
import re
from pathlib import Path

from acquire_history import name_key, team_key
from benfrank_v44_calibration import instant
from benfrank_v45_evidence import digest, write_json
from benfrank_v45_odds import TEAM_NAMES
from benfrank_v46_official_injuries import validate_header

STATUSES = {"Out", "Doubtful", "Questionable", "Probable", "Available"}
UNKNOWN = "UNKNOWN_NOT_CLEARED"
TEAM_KEYS = {name_key(name): code for name, code in TEAM_NAMES.items()}


def canonical_name(source_name, aliases=None):
    parts = source_name.split(",", 1)
    if len(parts) != 2 or not all(p.strip() for p in parts):
        raise ValueError("UNRESOLVED_OFFICIAL_PLAYER_NAME")
    name = parts[1].strip() + " " + parts[0].strip()
    return (aliases or {}).get(name_key(name), name)


def parse_report(text, report_time_utc, cutoff, aliases=None):
    validate_header(text, report_time_utc, cutoff)
    columns, date, matchup, team = None, None, None, None
    groups, issues = {}, []
    last_player = None
    for index, line in enumerate(text.splitlines(), 1):
        if all(h in line for h in ("Game Date", "Matchup", "Team", "Player Name", "Current Status", "Reason")):
            columns = {h: line.index(h) for h in ("Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason")}
            continue
        if columns is None or not line.strip() or "Injury Report:" in line or re.search(r"Page \d+ of \d+", line):
            continue
        c = columns
        date_cell = line[c["Game Date"]:c["Game Time"]].strip()
        matchup_cell = line[c["Matchup"]:c["Team"]].strip()
        team_cell = line[c["Team"]:c["Player Name"]].strip()
        player_cell = line[c["Player Name"]:c["Current Status"]].strip()
        status_cell = line[c["Current Status"]:c["Reason"]].strip()
        reason_cell = line[c["Reason"]:].strip()
        if date_cell:
            try:
                date = dt.datetime.strptime(date_cell, "%m/%d/%Y").date().isoformat()
            except ValueError:
                issues.append({"line": index, "reason": "UNPARSED_GAME_DATE", "text": line})
                date, matchup, team = None, None, None
                continue
        if matchup_cell:
            if not re.fullmatch(r"[A-Z]{2,4}@[A-Z]{2,4}", matchup_cell):
                issues.append({"line": index, "reason": "UNPARSED_MATCHUP", "text": line})
                matchup, team = None, None
                continue
            matchup = "@".join(team_key(t) for t in matchup_cell.split("@"))
            team = None
        if team_cell:
            team = TEAM_KEYS.get(name_key(team_cell))
            last_player = None
            if team is None:
                issues.append({"line": index, "reason": "UNPARSED_TEAM", "text": line})
                continue
        if not date or not matchup or not team:
            if player_cell or status_cell:
                issues.append({"line": index, "reason": "MISSING_GAME_TEAM_CONTEXT", "text": line})
            continue
        if team not in matchup.split("@"):
            issues.append({"line": index, "reason": "TEAM_MATCHUP_CONFLICT", "text": line})
            continue
        key = date + "|" + matchup + "|" + team
        group = groups.setdefault(key, {"game_date": date, "matchup": matchup, "team": team,
                    "submission_status": "UNKNOWN", "players": {}, "report_time_utc": instant(report_time_utc).isoformat()})
        if "NOT YET SUBMITTED" in line:
            group["submission_status"] = "NOT_YET_SUBMITTED"
            continue
        if status_cell in STATUSES and player_cell:
            try:
                name = canonical_name(player_cell, aliases)
            except ValueError as exc:
                issues.append({"line": index, "reason": str(exc), "text": line})
                continue
            name_id = name_key(name)
            player = {"player": name, "source_name": player_cell, "status": status_cell,
                      "reason": reason_cell, "source_line": index}
            if name_id in group["players"] and group["players"][name_id]["status"] != status_cell:
                issues.append({"line": index, "reason": "CONFLICTING_PLAYER_STATUS", "text": line})
                group["players"][name_id]["status"] = UNKNOWN
            else:
                group["players"][name_id] = player
            group["submission_status"] = "SUBMITTED_WITH_LISTED_PLAYERS"
            last_player = group["players"][name_id]
        elif player_cell or status_cell:
            issues.append({"line": index, "reason": "UNPARSED_PLAYER_STATUS_ROW", "text": line})
            last_player = None
        elif reason_cell and last_player is not None:
            last_player["reason"] += " " + reason_cell
    return {"report_time_utc": instant(report_time_utc).isoformat(), "line_cutoff_utc": instant(cutoff).isoformat(),
            "game_team_reports": groups, "issues": issues, "unlisted_player_status": UNKNOWN}


def parse_pdf(path, report_time_utc, cutoff, aliases=None):
    """Use physical PDF columns; page-local text cropping must not shift cells."""
    import pdfplumber
    labels = ("Game Date", "Game Time", "Matchup", "Team", "Player Name", "Current Status", "Reason")
    normalized = {name_key(label): label for label in labels}
    rows, coordinates, source_positions = [], None, []
    with pdfplumber.open(path) as document:
        for page in document.pages:
            words = page.extract_words(x_tolerance=1, y_tolerance=2)
            default_words = page.extract_words()
            heading = next((w for w in default_words if name_key(w["text"]) == 'matchup'), None)
            header = {normalized[name_key(w["text"])]: w["x0"] for w in default_words
                      if heading is not None and abs(w['top']-heading['top']) < 2 and name_key(w["text"]) in normalized}
            if len(header) == len(labels):
                coordinates = header
            if coordinates is None:
                raise ValueError("OFFICIAL_PDF_TABLE_COLUMN_COORDINATES_MISSING")
            starts = [coordinates[label] - 2 for label in labels]
            body_start = heading['top'] + 10 if heading is not None else 70
            footer = next((w for w in default_words if w['text'].startswith('Page') and w['top'] > page.height-100), None)
            body_end = footer['top']-2 if footer is not None else page.height-27
            body = [w for w in words if body_start < w["top"] < body_end and
                    name_key(w["text"]) not in normalized and w["x0"] >= starts[0]]
            status_words = [w for w in body if starts[5] <= w["x0"] < starts[6] and w["text"] in STATUSES]
            not_submitted = [w for w in body if w["text"].replace(" ", "").startswith("NOT")]
            anchors = sorted({round(w["top"], 1) for w in status_words + not_submitted})
            for i, anchor in enumerate(anchors):
                low = (anchors[i-1] + anchor)/2 if i else body_start
                high = (anchor + anchors[i+1])/2 if i+1 < len(anchors) else body_end
                cells = []
                for j, left in enumerate(starts):
                    right = starts[j+1] if j+1 < len(starts) else page.width
                    tokens = sorted((w for w in body if left <= w["x0"] < right and low <= w["top"] < high),
                                    key=lambda w: (round(w["top"], 1), w["x0"]))
                    cells.append(" ".join(w["text"] for w in tokens))
                if any("NOT" in cell and "SUBMITTED" in cell for cell in cells):
                    cells[4], cells[5], cells[6] = "", "", "NOT YET SUBMITTED"
                rows.append(cells)
                source_positions.append({"page": page.page_number, "status_top": anchor})
    widths = [max(len(labels[j]), max((len(row[j]) for row in rows), default=0)) + 3 for j in range(6)]
    def table_line(cells):
        return "".join(cells[j].ljust(widths[j]) for j in range(6)) + cells[6]
    printed = "Injury Report: " + instant(report_time_utc).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%m/%d/%y %I:%M %p')
    # Independently verify the original printed header before normalized parsing.
    import subprocess
    original = subprocess.run(['pdftotext', '-layout', str(path), '-'], text=True, capture_output=True, check=True).stdout
    validate_header(original, report_time_utc, cutoff)
    parsed = parse_report(printed + '\n' + table_line(labels) + '\n' + '\n'.join(table_line(row) for row in rows),
                          report_time_utc, cutoff, aliases)
    parsed['source_row_positions'] = source_positions
    return parsed


def observation(parsed, game_date, home, away, team, player):
    group = parsed["game_team_reports"].get(game_date + "|" + away + "@" + home + "|" + team)
    if group is None:
        return {"status": UNKNOWN, "reason": "GAME_TEAM_NOT_IN_ORIGINAL_REPORT"}
    row = group["players"].get(name_key(player))
    if row is not None:
        return {**row, "report_time_utc": parsed["report_time_utc"], "submission_status": group["submission_status"]}
    return {"status": UNKNOWN, "reason": "UNLISTED_OR_NOT_SUBMITTED", "report_time_utc": parsed["report_time_utc"],
            "submission_status": group["submission_status"]}


def load_archive(directory, aliases=None):
    root = Path(directory).resolve()
    manifest = json.loads((root / "official-injury-captures.json").read_text())
    captures = {}
    for item in manifest["reports"]:
        if item["status"] != "PRESERVED_ORIGINAL_OFFICIAL_PREGAME_REPORT":
            continue
        pdf, text = (root / item["file"]).resolve(), (root / item["text_file"]).resolve()
        if root not in pdf.parents or root not in text.parents:
            raise ValueError("INJURY_SOURCE_PATH_OUTSIDE_ARCHIVE")
        if digest(pdf) != item["sha256"] or digest(text) != item["text_sha256"]:
            raise ValueError("ORIGINAL_INJURY_DOCUMENT_HASH_CONFLICT")
        parsed = parse_pdf(pdf, item["report_time_utc"], item["line_cutoff_utc"], aliases)
        parsed.update(source_pdf_sha256=item["sha256"], source_url=item["url"])
        captures[instant(item["line_cutoff_utc"]).isoformat()] = parsed
    return captures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    captures = load_archive(args.archive)
    report = {"captures": captures, "report_count": len(captures),
              "parsed_game_team_reports": sum(len(r["game_team_reports"]) for r in captures.values()),
              "parse_issue_count": sum(len(r["issues"]) for r in captures.values()), "certification": "NOT_CERTIFIED"}
    write_json(args.out, report)
    print(json.dumps({k: v for k, v in report.items() if k != "captures"}, indent=2))


if __name__ == "__main__":
    main()
