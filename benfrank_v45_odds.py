"""Capture/import original The Odds API NBA snapshots into the separate ledger.

Historical calls require the user's provider subscription/key. No key, invented
line, screenshot result tile, or public release of licensed data is substituted.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from benfrank_v44_calibration import instant
from benfrank_v44_snapshot_ledger import ingest

MARKETS = {"player_points": "points", "player_rebounds": "rebounds",
           "player_assists": "assists", "player_threes": "threes",
           "player_steals": "steals", "player_blocks": "blocks",
           "player_turnovers": "turnovers", "player_points_rebounds_assists": "pra",
           "player_points_rebounds": "pr", "player_points_assists": "pa",
           "player_rebounds_assists": "ra"}
TEAM_NAMES = dict(zip(("Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
    "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons",
    "Golden State Warriors", "Houston Rockets", "Indiana Pacers", "Los Angeles Clippers",
    "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat", "Milwaukee Bucks", "Minnesota Timberwolves",
    "New Orleans Pelicans", "New York Knicks", "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers",
    "Phoenix Suns", "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors",
    "Utah Jazz", "Washington Wizards"),
    ("ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC",
     "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC",
     "SAS", "TOR", "UTA", "WAS")))
TEAM_NAMES["LA Clippers"] = "LAC"


def normalize(document, source_sha256, source_file):
    """Return exact source rows; historical timestamp is never the request time."""
    response = document.get("response", document)
    if "timestamp" in response:
        captured = instant(response["timestamp"])
        event = response["data"]
    else:
        if document.get("provider") != "THE_ODDS_API" or not document.get("observed_at"):
            raise ValueError("Unwrapped live odds lack original collector timestamp")
        captured, event = instant(document["observed_at"]), response
    if not isinstance(event, dict) or event.get("sport_key") != "basketball_nba":
        raise ValueError("One NBA event response is required")
    tipoff = instant(event["commence_time"])
    if captured >= tipoff:
        raise ValueError("Historical line was captured at/after tipoff")
    home, away = TEAM_NAMES[event["home_team"]], TEAM_NAMES[event["away_team"]]
    if home == away or not event.get("id"):
        raise ValueError("Missing or contradictory game identity")
    date = tipoff.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    rows, seen = [], set()
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market["key"] not in MARKETS:
                continue
            updated = market.get("last_update", book.get("last_update"))
            if updated and instant(updated) > captured:
                raise ValueError("Provider market update is after the archived snapshot")
            for outcome in market.get("outcomes", []):
                if outcome.get("name", "").casefold() not in ("over", "under"):
                    continue
                player, line = outcome.get("description"), outcome.get("point")
                if not isinstance(player, str) or not player.strip() or isinstance(line, bool) or not isinstance(line, (int, float)):
                    raise ValueError("Player/line missing in original outcome")
                identity = (str(event["id"]), book["key"], market["key"], player, line, captured.isoformat())
                if identity in seen:
                    continue
                seen.add(identity)
                sid = "odds-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
                # Provider player props do not encode the player's team. Preserve
                # both event teams; resolve the opponent from verified identities.
                rows.append({"snapshot_id": sid, "game_id": str(event["id"]),
                    "player": player, "market": MARKETS[market["key"]], "line": line,
                    "platform": book["key"], "game_date": date,
                    "opponent": "UNRESOLVED_EVENT_TEAMS_" + home + "_" + away,
                    "home_team": home, "away_team": away,
                    "captured_at": captured.isoformat(), "tipoff_utc": tipoff.isoformat(),
                    "source_type": "PLATFORM_API", "source_provider": "THE_ODDS_API",
                    "source_sha256": source_sha256, "source_file": source_file,
                    "provider_market": market["key"], "provider_last_update": updated})
    if not rows:
        raise ValueError("No supported pregame over/under player props in source")
    return rows


def resolve_opponents(rows, warehouse):
    """Exact player/game-date identity only; no guessed player team or fuzzy names."""
    from benfrank_v45_evidence import readonly
    conn = readonly(warehouse)
    try:
        resolved, rejected = [], []
        for row in rows:
            teams = (row["home_team"], row["away_team"])
            hits = conn.execute("SELECT DISTINCT team,opponent FROM games WHERE player=? AND date=? "
                                "AND team IN (?,?) AND opponent IN (?,?)",
                                (row["player"], row["game_date"], *teams, *teams)).fetchall()
            if len(hits) != 1:
                rejected.append({"snapshot_id": row["snapshot_id"], "reason": "PLAYER_GAME_TEAM_MAPPING_REQUIRED"})
            else:
                mapping = hits[0]["team"] + "|" + hits[0]["opponent"]
                resolved.append({**row, "source_snapshot_id": row["snapshot_id"],
                    "snapshot_id": row["snapshot_id"] + "-id-" + hashlib.sha256(mapping.encode()).hexdigest()[:12],
                    "opponent": hits[0]["opponent"], "team": hits[0]["team"]})
        return resolved, rejected
    finally:
        conn.close()


def capture_matches(snapshot, path):
    original = normalize(json.loads(path.read_text()), snapshot["source_sha256"], snapshot["source_file"])
    keys = ("snapshot_id", "game_id", "player", "platform", "market", "line", "game_date", "captured_at", "tipoff_utc")
    target = {**snapshot, "snapshot_id": snapshot.get("source_snapshot_id", snapshot["snapshot_id"])}
    return any(all(s.get(k) == target.get(k) for k in keys) for s in original)


def collect(event_id, api_key, at=None, markets="player_points", bookmakers="prizepicks"):
    if not api_key:
        raise ValueError("BENFRANK_ODDS_API_KEY is missing; no provider request made")
    if not event_id.isalnum() or any(m not in MARKETS for m in markets.split(",")):
        raise ValueError("Unsupported event ID or market")
    prefix = "/historical" if at else ""
    endpoint = "https://api.the-odds-api.com/v4" + prefix + "/sports/basketball_nba/events/" + event_id + "/odds"
    params = {"apiKey": api_key, "markets": markets, "bookmakers": bookmakers}
    if at:
        params["date"] = instant(at).isoformat()
    request = urllib.request.Request(endpoint + "?" + urllib.parse.urlencode(params), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(16_000_001)
            if len(raw) > 16_000_000:
                raise ValueError("Provider response exceeds size limit")
    except urllib.error.HTTPError as exc:
        raise ValueError("Provider HTTP " + str(exc.code) + "; credentials and query redacted") from None
    except urllib.error.URLError:
        raise ValueError("Provider connection unavailable; credentials and query redacted") from None
    return {"provider": "THE_ODDS_API", "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "endpoint": endpoint, "response": json.loads(raw)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source-json")
    mode.add_argument("--collect-event")
    p.add_argument("--at")
    p.add_argument("--markets", default="player_points")
    p.add_argument("--bookmakers", default="prizepicks")
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--warehouse", help="Optional historical identity reconciliation; never modifies games")
    a = p.parse_args()
    root = Path(a.evidence_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    document = (json.loads(Path(a.source_json).read_text()) if a.source_json else
                collect(a.collect_event, os.environ.get("BENFRANK_ODDS_API_KEY"), a.at, a.markets, a.bookmakers))
    # Save the original response, not a reconstruction of individual line rows.
    raw = Path(a.source_json).read_bytes() if a.source_json else json.dumps(document, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    name = sha + ".json"
    path = root / name
    if path.exists() and path.read_bytes() != raw:
        raise ValueError("Immutable source collision")
    path.write_bytes(raw)
    rows = normalize(document, sha, name)
    rejected = []
    if a.warehouse:
        rows, rejected = resolve_opponents(rows, a.warehouse)
    # Unresolved current-event rows can be stored but cannot pass replay identity.
    ledger = Path(a.ledger).resolve()
    if ledger.name in ("nba_warehouse.sqlite", "nba.sqlite"):
        raise ValueError("Use a separate snapshot ledger")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ledger)
    try:
        result = ingest(conn, rows) if rows else {"status": "BLOCKED_PLAYER_GAME_MAPPING", "inserted": 0}
    finally:
        conn.close()
    print(json.dumps({**result, "source_sha256": sha, "rejected": rejected}, indent=2))


if __name__ == "__main__":
    main()
