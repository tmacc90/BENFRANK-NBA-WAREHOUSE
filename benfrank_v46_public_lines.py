"""Recover published pregame PrizePicks captures from a pinned public collector.

This is a SECONDARY collector archive, not a native authenticated platform feed.
Commit dates are publication metadata, not independent timestamp attestations.
Raw files, receipt hashes, exclusions and the original player names are retained.
"""
import argparse
import collections
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from acquire_history import name_key, team_key, verification_relation
from benfrank_v44_calibration import instant
from benfrank_v44_snapshot_ledger import ingest
from benfrank_v45_evidence import digest, readonly, write_json

REPOSITORY = "enkday/prizepicks-data-mirror"
SOURCE_PATH = "data/prizepicks-nba-today.json"
MARKETS = {"Points": "points", "Rebounds": "rebounds", "Assists": "assists",
           "3-PT Made": "threes", "Blocked Shots": "blocks", "Steals": "steals",
           "Turnovers": "turnovers", "Pts+Rebs+Asts": "pra", "Pts+Rebs": "pr",
           "Pts+Asts": "pa", "Rebs+Asts": "ra"}
SOURCE_TIER = "SECONDARY_PUBLIC_COLLECTOR_NOT_PLATFORM_ATTESTED"


def source_url(commit):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("PINNED_COMMIT_REQUIRED")
    return "https://raw.githubusercontent.com/" + REPOSITORY + "/" + commit + "/" + SOURCE_PATH


def read_url(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BENFRANK-NBA-Evidence/4.6"})
    with urllib.request.urlopen(req, timeout=35) as response:
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("CAPTURE_TOO_LARGE")
    return raw


def normalize(document, receipt, source_file, receipt_file, receipt_sha256):
    if (receipt.get("repository") != REPOSITORY or receipt.get("path") != SOURCE_PATH or
            receipt.get("source_url") != source_url(receipt.get("commit_sha"))):
        raise ValueError("COLLECTOR_OR_PINNED_SOURCE_CONFLICT")
    if document.get("sport") != "NBA" or document.get("source") != "PrizePicks API":
        raise ValueError("UNSUPPORTED_COLLECTOR_DOCUMENT")
    observed = instant(document["scrapedAt"])
    published = instant(receipt["committed_at"])
    if published < observed:
        raise ValueError("COMMIT_PRECEDES_COLLECTOR_CAPTURE")
    captured = max(observed, published)
    rows, rejections = [], collections.Counter()
    for index, prop in enumerate(document.get("props", [])):
        try:
            if prop.get("oddsType") != "standard" or prop.get("sport") != "NBA":
                raise ValueError("NONSTANDARD_OR_OTHER_SPORT")
            if prop.get("status") not in (None, "pre_game"):
                raise ValueError("NOT_PREGAME")
            if prop.get("stat") not in MARKETS:
                raise ValueError("UNSUPPORTED_OR_UNVERIFIED_MARKET_CONTRACT")
            tipoff = instant(prop["startTimeIso"])
            if captured >= tipoff:
                raise ValueError("NOT_PUBLISHED_BEFORE_PROVIDER_TIPOFF")
            line = prop["line"]
            if isinstance(line, bool):
                raise ValueError("INVALID_EXACT_LINE")
            line = float(line)
            if not math.isfinite(line) or line < 0:
                raise ValueError("INVALID_EXACT_LINE")
            player = prop["player"]
            if not isinstance(player, str) or not player.strip():
                raise ValueError("MISSING_PLAYER")
            team, opponent = team_key(prop["teamCode"]), team_key(prop["opponentCode"])
            if team == opponent or len(team) != 3 or len(opponent) != 3:
                raise ValueError("INVALID_EVENT_TEAMS")
            sid = "pp-archive-" + hashlib.sha256((receipt["raw_sha256"] + "|" + str(index)).encode()).hexdigest()
            rows.append({"snapshot_id": sid, "platform": "PrizePicks", "player": player,
                "source_player": player, "market": MARKETS[prop["stat"]], "line": line,
                "team": team, "opponent": opponent, "game_id": "pp-" + str(prop["gameId"]),
                "game_date": tipoff.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
                "captured_at": captured.isoformat(), "collector_captured_at": observed.isoformat(),
                "tipoff_utc": tipoff.isoformat(), "provider_tipoff_utc": tipoff.isoformat(),
                "source_type": "PUBLIC_COLLECTOR_ARCHIVE", "source_provider": "ENKDAY_PRIZEPICKS_ARCHIVE",
                "source_sha256": receipt["raw_sha256"], "source_file": source_file,
                "source_receipt_file": receipt_file, "source_receipt_sha256": receipt_sha256,
                "source_row_index": index, "source_commit": receipt["commit_sha"],
                "source_tier": SOURCE_TIER, "platform_authenticity_independently_attested": False})
        except (KeyError, ValueError, TypeError) as exc:
            rejections[str(exc)] += 1
    return rows, dict(rejections)


def resolve_games(rows, warehouse):
    conn = readonly(warehouse)
    before = digest(warehouse)
    try:
        relation = verification_relation(conn)
        players = collections.defaultdict(list)
        for r in conn.execute("SELECT g.player,g.date,g.team,g.opponent,v.nba_game_id FROM games g JOIN " +
                              relation + " v USING(player,date,team)"):
            players[(name_key(r["player"]), r["date"], r["team"], r["opponent"])].append(dict(r))
        schedule = {}
        sources = conn.execute("SELECT sha256 FROM source_files WHERE name='nba_stats_schedule_master.parquet'").fetchall()
        if len(sources) != 1:
            raise ValueError("UNIQUE_OFFICIAL_SCHEDULE_REQUIRED")
        for raw in conn.execute("SELECT payload_json FROM source_records WHERE file_sha256=?", (sources[0][0],)):
            game = json.loads(raw[0])
            if str(game.get("season_type_id")) == "2" and game.get("game_status") == 3:
                schedule[str(game["game_id"])] = game
        accepted, rejected = [], []
        for s in rows:
            try:
                matches = players.get((name_key(s["player"]), s["game_date"], s["team"], s["opponent"]), [])
                if len(matches) != 1:
                    raise ValueError("NO_UNIQUE_VERIFIED_PLAYER_GAME_SETTLEMENT")
                match = matches[0]
                game = schedule[match["nba_game_id"]]
                if {team_key(game["home_team_tricode"]), team_key(game["away_team_tricode"])} != {s["team"], s["opponent"]}:
                    raise ValueError("OFFICIAL_EVENT_TEAM_CONFLICT")
                official_tipoff = instant(game["game_date_time_utc"])
                if abs((official_tipoff - instant(s["provider_tipoff_utc"])).total_seconds()) > 1800:
                    raise ValueError("MATERIAL_PROVIDER_OFFICIAL_TIPOFF_CONFLICT")
                if instant(s["captured_at"]) >= official_tipoff:
                    raise ValueError("NOT_PUBLISHED_BEFORE_OFFICIAL_TIPOFF")
                accepted.append({**s, "source_snapshot_id": s["snapshot_id"],
                    "snapshot_id": s["snapshot_id"] + "-nba", "player": match["player"],
                    "game_id": match["nba_game_id"], "tipoff_utc": official_tipoff.isoformat(),
                    "official_schedule_sha256": sources[0][0], "mapping_warehouse_sha256": before})
            except (KeyError, ValueError, TypeError) as exc:
                rejected.append({"snapshot_id": s["snapshot_id"], "reason": str(exc)})
        return accepted, rejected
    finally:
        conn.close()
        if before != digest(warehouse):
            raise ValueError("WAREHOUSE_CHANGED_DURING_READ_ONLY_RESOLUTION")


def capture_matches(snapshot, path, evidence_root, cache=None):
    if (snapshot.get("source_tier") != SOURCE_TIER or
            snapshot.get("source_provider") != "ENKDAY_PRIZEPICKS_ARCHIVE" or
            snapshot.get("platform_authenticity_independently_attested") is not False):
        return False
    root = Path(evidence_root).resolve()
    receipt_path = (root / snapshot["source_receipt_file"]).resolve()
    if (root not in receipt_path.parents or not receipt_path.is_file() or
            digest(receipt_path) != snapshot["source_receipt_sha256"]):
        return False
    receipt = json.loads(receipt_path.read_text())
    if receipt["raw_sha256"] != digest(path):
        return False
    cache_key = (str(path), receipt["raw_sha256"], snapshot["source_receipt_file"], snapshot["source_receipt_sha256"])
    if cache is None:
        cache = {}
    if cache_key not in cache:
        rows, _ = normalize(json.loads(path.read_text()), receipt, snapshot["source_file"],
                            snapshot["source_receipt_file"], snapshot["source_receipt_sha256"])
        cache[cache_key] = {r["snapshot_id"]: r for r in rows}
    original = cache[cache_key].get(snapshot.get("source_snapshot_id", snapshot["snapshot_id"]))
    if original is None:
        return False
    keys = ("market", "line", "platform", "source_player", "team", "opponent", "game_date",
            "captured_at", "collector_captured_at", "provider_tipoff_utc", "source_commit", "source_row_index")
    return (all(snapshot.get(k) == original[k] for k in keys) and
            name_key(snapshot["player"]) == name_key(original["player"]) and
            instant(snapshot["captured_at"]) < instant(snapshot["tipoff_utc"]))


def recover(commits, warehouse, out_dir):
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "captures").mkdir()
    if not isinstance(commits, list) or not 1 <= len(commits) <= 100:
        raise ValueError("ONE_TO_100_PINNED_CAPTURE_COMMITS_REQUIRED")
    all_rows, failures, rejected_counts = [], [], collections.Counter()
    def fetch(commit):
        url = source_url(commit["sha"])
        raw = read_url(url)
        receipt = {"repository": REPOSITORY, "path": SOURCE_PATH, "commit_sha": commit["sha"],
                   "committed_at": commit["committed_at"], "source_url": url,
                   "raw_sha256": hashlib.sha256(raw).hexdigest(),
                   "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(), "source_tier": SOURCE_TIER}
        return raw, receipt
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch, c): c for c in commits}
        for future in concurrent.futures.as_completed(futures):
            commit = futures[future]
            try:
                raw, receipt = future.result()
                name = "captures/" + commit["sha"] + ".json"
                receipt_name = "captures/" + commit["sha"] + ".receipt.json"
                (out / name).write_bytes(raw)
                write_json(out / receipt_name, receipt)
                rows, rejected = normalize(json.loads(raw), receipt, name, receipt_name, digest(out / receipt_name))
                all_rows.extend(rows)
                rejected_counts.update(rejected)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failures.append({"commit": commit["sha"], "reason": str(exc)})
    resolved, rejected = resolve_games(all_rows, warehouse)
    rejected_counts.update(r["reason"] for r in rejected)
    saved = {"inserted": 0}
    if resolved:
        with sqlite3.connect(out / "snapshots.sqlite") as conn:
            saved = ingest(conn, sorted(resolved, key=lambda s: (s["captured_at"], s["snapshot_id"])))
    report = {"status": "RECOVERED_SECONDARY_PREGAME_ARCHIVE" if resolved else "BLOCKED_NO_RESOLVED_CAPTURES",
        "requested_captures": len(commits), "capture_fetch_failures": failures,
        "supported_pregame_rows": len(all_rows), "verified_settlement_linked_rows": len(resolved),
        "exclusion_reasons": dict(rejected_counts), "ledger": saved, "source_tier": SOURCE_TIER,
        "unique_games": len({s["game_id"] for s in resolved}),
        "per_market": dict(collections.Counter(s["market"] for s in resolved)),
        "date_range": [min(s["game_date"] for s in resolved), max(s["game_date"] for s in resolved)] if resolved else None,
        "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
        "warning": "Public collector provenance supports research; platform authenticity and historical injuries/rotations are not independently attested. Selection excludes unresolved, unplayed and unsupported rows; measure this selection bias."}
    write_json(out / "rejected_game_mappings.json", rejected)
    write_json(out / "recovery.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commits", required=True, help="JSON array of sha and committed_at from GitHub path history")
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(recover(json.loads(Path(args.commits).read_text()), args.warehouse, args.out_dir), indent=2))


if __name__ == "__main__":
    main()
