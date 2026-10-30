"""Read-only ESPN current-game collector, staging-only for NBA historical warehouse.

Fetches ESPN scoreboard and completed regular-season summaries; writes to a NEW
SQLite staging database. Nothing is promoted to official verified games.
"""
import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from warehouse_v36 import stage
from engine import connect

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates="
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="


def fetch_json(url, opener=None):
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": "BENFRANK-NBA-DataAudit/1.0",
                                               "Accept": "application/json"})
    with opener(req, timeout=18) as resp:
        data = resp.read(8_000_001)
        status = resp.status
    if len(data) > 8_000_000:
        raise ValueError("ESPN response exceeds size limit")
    return json.loads(data), {"url": url, "http_status": status,
                              "sha256": hashlib.sha256(data).hexdigest(),
                              "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat()}


def numeric(s):
    value = str(s).strip()
    if value in ("", "--", "-", "DNP", "None"):
        raise ValueError("missing stat")
    v = float(value)
    if not (0 <= v < 1000):
        raise ValueError("out-of-range stat")
    return v


def parse_makes(s):
    return numeric(str(s).split("-")[0])


def parse_minutes(value):
    value = str(value).strip()
    if ":" in value:
        m, sec = value.split(":", 1)
        if not sec.isdigit() or not 0 <= int(sec) < 60:
            raise ValueError("invalid minute clock")
        return float(m) + int(sec) / 60
    return numeric(value)


def season_for_date(date):
    d = dt.date.fromisoformat(date)
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start+1)[-2:]}"


def rows_from_summary(event_id, requested_date, expected_home, expected_away, summary):
    """Return only played box-score rows, never mark as verified official."""
    boxscore = summary.get("boxscore") or {}
    groups = boxscore.get("players")
    if not isinstance(groups, list):
        raise ValueError("ESPN summary boxscore.players missing")
    output = []
    for group in groups:
        team = (group.get("team") or {}).get("abbreviation")
        if team not in {expected_home, expected_away}:
            raise ValueError("summary team doesn't match event competitors")
        home = int(team == expected_home)
        for category in group.get("statistics") or []:
            labels = category.get("labels") or category.get("names") or []
            mapping = {str(name).upper(): i for i, name in enumerate(labels)}
            required = ("MIN","PTS","REB","AST","STL","BLK","TO","3PT")
            if not all(k in mapping for k in required):
                continue
            for athlete in category.get("athletes") or []:
                if athlete.get("didNotPlay") is True:
                    continue
                numbers = athlete.get("stats") or []
                if len(numbers) != len(labels):
                    continue
                try:
                    getter = lambda key: numbers[mapping[key]]
                    name = (athlete.get("athlete") or {}).get("displayName")
                    if not name:
                        raise ValueError("Player name missing")
                    row = {"player": name, "date": requested_date,
                           "season": season_for_date(requested_date),
                           "team": team,
                           "opponent": expected_away if home else expected_home,
                           "home": home,
                           "starter": int(athlete["starter"]) if isinstance(athlete.get("starter"), bool) else None,
                           "minutes": parse_minutes(getter("MIN")),
                           "pts": numeric(getter("PTS")), "reb": numeric(getter("REB")),
                           "ast": numeric(getter("AST")), "stl": numeric(getter("STL")),
                           "blk": numeric(getter("BLK")), "tov": numeric(getter("TO")),
                           "fg3m": parse_makes(getter("3PT")),
                           "source_game_id": str(event_id), "season_type": "regular"}
                    if row["minutes"] > 70:
                        raise ValueError("minutes above safe bounds")
                    output.append(row)
                except (KeyError, IndexError, TypeError, ValueError):
                    # Malformed player rows are explicitly counted by caller; no invented defaults.
                    continue
    if not output:
        raise ValueError("No complete played player box score rows parsed")
    return output


def fetch_staged(date, max_events=2, opener=None):
    dt.date.fromisoformat(date)
    if not 1 <= max_events <= 20:
        raise ValueError("max_events must be 1..20")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    receipt = {"date": date, "retrieved_at": now, "source": "ESPN_SECONDARY",
               "staged_rows": [], "events": [], "status": "NO_SOURCE",
               "official_verified_rows": 0, "promoted_to_games": 0}
    try:
        data, meta = fetch_json(SCOREBOARD + date.replace("-", ""), opener)
        receipt["scoreboard_receipt"] = meta
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        receipt["error"] = type(exc).__name__ + ": " + str(exc)[:200]
        return receipt
    events = data.get("events")
    if not isinstance(events, list):
        receipt["status"] = "SCHEMA_ERROR"
        receipt["error"] = "scoreboard.events is missing"
        return receipt
    completed = []
    for ev in events:
        status = (ev.get("status") or {}).get("type") or {}
        if status.get("completed") is not True:
            continue
        season_type = (ev.get("season") or {}).get("type")
        if season_type is not None and int(season_type) != 2:
            continue
        comps = ev.get("competitions") or []
        if not comps:
            continue
        teams = {x.get("homeAway"): (x.get("team") or {}).get("abbreviation")
                 for x in comps[0].get("competitors") or []}
        if not teams.get("home") or not teams.get("away"):
            continue
        completed.append((str(ev.get("id")), teams["home"], teams["away"]))
    if not completed:
        receipt["status"] = "NO_COMPLETED_REGULAR_GAMES"
        return receipt
    for game_id, home, away in completed[:max_events]:
        entry = {"event_id": game_id, "home": home, "away": away}
        try:
            detail, meta = fetch_json(SUMMARY + game_id, opener)
            entry["fetch"] = meta
            rows = rows_from_summary(game_id, date, home, away, detail)
            receipt["staged_rows"].extend(rows)
            entry["status"] = "PARSED_UNVERIFIED"
            entry["players"] = len(rows)
        except (urllib.error.URLError, ValueError, TimeoutError, OSError, TypeError) as exc:
            entry["status"] = "UNAVAILABLE_OR_INVALID"
            entry["error"] = type(exc).__name__ + ": " + str(exc)[:200]
        receipt["events"].append(entry)
    receipt["status"] = ("PARTIAL_STAGING" if receipt["staged_rows"] and any(e["status"] != "PARSED_UNVERIFIED" for e in receipt["events"])
                         else "PARSED_UNVERIFIED" if receipt["staged_rows"] else "SUMMARY_UNAVAILABLE")
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=(dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=1)).isoformat())
    p.add_argument("--max-events", type=int, default=2)
    p.add_argument("--out-dir", default="receipts/espn_live")
    p.add_argument("--strict", action="store_true", help="Return exit 2 for missing or partially collected completed games")
    args = p.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = fetch_staged(args.date, args.max_events)
    rows = data.pop("staged_rows")
    data["parsed_rows"] = len(rows)
    if rows:
        # Create an isolated secondary-source staging SQLite. Never write production games.
        db = str(out / "espn_staging.sqlite")
        connection = connect(db)
        staged = stage(connection, "espn", rows)
        data["sqlite_staging"] = staged
        connection.close()
    data["player_rows_sha256"] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest() if rows else None
    (out / "source_receipt.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"status": data["status"], "date": args.date, "parsed_rows": data["parsed_rows"],
                      "official_verified_rows": 0, "promoted_to_games": 0}, indent=2))
    if args.strict and data["status"] not in ("PARSED_UNVERIFIED", "NO_COMPLETED_REGULAR_GAMES"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
