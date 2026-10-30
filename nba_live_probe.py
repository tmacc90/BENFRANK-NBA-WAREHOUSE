"""Read-only NBA/ESPN schedule health probe; never asserts data that did not arrive.

The NBA official today scoreboard is only authoritative for the DATE IN ITS PAYLOAD.
ESPN is a secondary independent source, never silently promoted to NBA official truth.
"""
import argparse
import datetime as dt
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

NBA_URL = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates="


def normalize_nba(raw):
    sc = raw.get("scoreboard")
    if not isinstance(sc, dict) or not isinstance(sc.get("games"), list):
        raise ValueError("NBA official scoreboard.games missing or not a list")
    date = str(sc.get("gameDate") or "")
    dt.date.fromisoformat(date)
    games = []
    for g in sc["games"]:
        gid = str(g.get("gameId", ""))
        if len(gid) != 10 or not gid.isdigit():
            raise ValueError("NBA gameId invalid")
        games.append({"game_id": gid, "home": g.get("homeTeam", {}).get("teamTricode"),
                      "away": g.get("awayTeam", {}).get("teamTricode"),
                      "status": g.get("gameStatus"), "start_utc": g.get("gameTimeUTC")})
    return {"date": date, "games": games, "authority": "NBA_OFFICIAL"}


def normalize_espn(raw):
    if not isinstance(raw.get("events"), list):
        raise ValueError("ESPN events missing or not a list")
    games = []
    for ev in raw["events"]:
        competitions = ev.get("competitions") or []
        if not competitions:
            continue
        teams = {}
        for c in competitions[0].get("competitors", []):
            teams[c.get("homeAway")] = (c.get("team") or {}).get("abbreviation")
        games.append({"game_id": str(ev.get("id")), "home": teams.get("home"),
                      "away": teams.get("away"), "status": (ev.get("status") or {}).get("type", {}).get("state"),
                      "start_utc": ev.get("date")})
    return {"games": games, "authority": "ESPN_SECONDARY"}


def attempt(source, url, requested_date, opener=None, timeout=15):
    opener = opener or urllib.request.urlopen
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    entry = {"source": source, "url": url, "retrieved_at": now, "status": "UNAVAILABLE",
             "game_count": None, "sha256": None}
    req = urllib.request.Request(url, headers={"User-Agent": "BENFRANK-NBA-DataAudit/1.0",
                                               "Accept": "application/json"})
    try:
        with opener(req, timeout=timeout) as response:
            body = response.read(5_000_001)
            status = response.status
        entry["http_status"] = status
        if len(body) > 5_000_000:
            raise ValueError("Source body exceeded size limit")
        payload = json.loads(body)
        normalized = normalize_nba(payload) if source == "NBA_OFFICIAL" else normalize_espn(payload)
        if source == "NBA_OFFICIAL" and normalized["date"] != requested_date:
            entry["status"] = "DATE_MISMATCH"
            entry["source_date"] = normalized["date"]
        else:
            entry["status"] = "AVAILABLE"
        entry["sha256"] = hashlib.sha256(body).hexdigest()
        entry["game_count"] = len(normalized["games"])
        entry["games"] = normalized["games"]
    except urllib.error.HTTPError as exc:
        entry.update({"http_status": exc.code, "error": "HTTP " + str(exc.code)})
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, KeyError) as exc:
        entry["error"] = type(exc).__name__ + ": " + str(exc)[:200]
    return entry


def probe(date, opener=None):
    dt.date.fromisoformat(date)
    sources = [
        attempt("NBA_OFFICIAL", NBA_URL, date, opener=opener),
        attempt("ESPN_SECONDARY", ESPN_BASE + date.replace("-", ""), date, opener=opener)
    ]
    return {"requested_date": date,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "sources": sources,
            "official_schedule_status": sources[0]["status"],
            "secondary_schedule_status": sources[1]["status"],
            "official_game_logs_imported": 0,
            "official_injury_reports_imported": 0,
            "player_boxscores_imported": 0,
            "status": "OFFICIAL_AVAILABLE" if sources[0]["status"] == "AVAILABLE"
                      else "SECONDARY_ONLY" if sources[1]["status"] == "AVAILABLE"
                      else "NO_SCHEDULE_SOURCE"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    p.add_argument("--output", default="nba_live_source_receipt.json")
    a = p.parse_args()
    result = probe(a.date)
    Path(a.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"date": a.date, "status": result["status"], "sources":
                      [{"source": s["source"], "status": s["status"], "http_status": s.get("http_status")}
                       for s in result["sources"]]}, indent=2))


if __name__ == "__main__":
    main()
