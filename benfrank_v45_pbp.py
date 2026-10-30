"""Acquire and crosscheck real PBP Stats game evidence without NBA API requests.

PBP Stats is NBA-derived, not another independent statistical authority. Lineup
period aggregates do not establish chronological substitution sequences.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import re
import statistics
import urllib.parse
import urllib.request
from pathlib import Path

from benfrank_v45_evidence import readonly, digest, write_json

BASE = "https://api.pbpstats.com"


def seconds(clock):
    m, sec = str(clock).split(":")
    if not m.isdigit() or not sec.isdigit() or not 0 <= int(sec) < 60:
        raise ValueError("Invalid game clock")
    return int(m) * 60 + int(sec)


def lineup_players(entity):
    ids = str(entity).split("-")
    if len(ids) != 5 or len(set(ids)) != 5 or not all(x.isdigit() and int(x) > 0 for x in ids):
        raise ValueError("Lineup must contain exactly five distinct official player IDs")
    return ids


def fetch(path, params, out, name, source_dir=None):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BENFRANK-NBA-EvidenceAudit/4.5"})
    if source_dir:
        raw = (Path(source_dir) / name).read_bytes()
    else:
        with urllib.request.urlopen(req, timeout=18) as response:
            raw = response.read(16_000_001)
    if len(raw) > 16_000_000:
        raise ValueError("PBP source exceeds size limit")
    data = json.loads(raw)
    (out / name).write_bytes(raw)
    return data, {"file": name, "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                  "retrieved_at": None if source_dir else dt.datetime.now(dt.timezone.utc).isoformat(),
                  "delivery": "SAVED_SOURCE_REPLAY" if source_dir else "DIRECT_PROVIDER_DOWNLOAD",
                  "authority": "NBA_DERIVED_PBPSTATS"}


def audit_game(game_id, archive_dir, evidence_db, out_dir, source_dir=None):
    if not re.fullmatch(r"002[0-9]{7}", game_id):
        raise ValueError("Explicit regular-season NBA game ID required")
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    before = digest(evidence_db)
    report = {"game_id": game_id, "status": "BLOCKED_SOURCE_UNAVAILABLE", "source_receipts": [],
              "input_evidence_database_sha256": before, "auditor_source_sha256": digest(__file__),
              "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "chronological_rotation_sequence_verified": False, "source_conflicts": [],
              "source_authority": "NBA_DERIVED_PBPSTATS_NOT_INDEPENDENT_OF_NBA_STATS"}
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(Path(archive_dir) / "source" / "nba_stats_schedule_master.parquet",
                              filters=[("game_id", "=", game_id)])
        matches = table.to_pylist()
        if len(matches) != 1 or matches[0]["game_status"] != 3:
            raise ValueError("Unique final official schedule entry required")
        game = matches[0]
        date = str(game["game_date_est"])[:10]
        year = int(game["season"])
        season = f"{year-1}-{str(year)[-2:]}"
        players, meta = fetch("/get-game-stats", {"GameId": game_id, "Type": "Player"}, out, "player.json", source_dir)
        report["source_receipts"].append(meta)
        lineups, meta = fetch("/get-game-stats", {"GameId": game_id, "Type": "Lineup"}, out, "lineups.json", source_dir)
        report["source_receipts"].append(meta)
        for document in (players, lineups):
            if (document.get("date") != date or document.get("league") != "nba" or document.get("season") != season
                    or document.get("home_team_abbreviation") != game["home_team_tricode"]
                    or document.get("away_team_abbreviation") != game["away_team_tricode"]):
                raise ValueError("PBP game date/teams/season conflict")
        conn = readonly(evidence_db)
        try:
            verified = [dict(r) for r in conn.execute("SELECT * FROM verified_shooting WHERE nba_game_id=?", (game_id,))]
        finally:
            conn.close()
        expected = {r["nba_player_id"]: r for r in verified}
        observed_ids = set()
        lineup_count, team_minutes, matching_players = 0, {}, 0
        for side, team in (("Home", game["home_team_tricode"]), ("Away", game["away_team_tricode"])):
            actual = [r for r in players["stats"][side]["FullGame"] if str(r["EntityId"]) != "0"]
            if {str(r["EntityId"]) for r in actual} != {r["nba_player_id"] for r in verified if r["team"] == team}:
                raise ValueError("PBP/independently crosschecked box-score roster mismatch")
            for p in actual:
                pid = str(p["EntityId"])
                if pid in observed_ids:
                    raise ValueError("Duplicate PBP player identity")
                observed_ids.add(pid)
                e = expected[pid]
                counts = {"fgm": p.get("FG2M", 0) + p.get("FG3M", 0),
                          "fga": p.get("FG2A", 0) + p.get("FG3A", 0),
                          "fg3m": p.get("FG3M", 0), "fg3a": p.get("FG3A", 0),
                          "ftm": p.get("FtPoints", 0), "fta": p.get("FTA", 0)}
                differences = {k: {"verified_box": e[k], "pbp": v} for k, v in counts.items() if e[k] != v}
                if abs(seconds(p["Minutes"]) - 60 * e["minutes"]) > 2:
                    differences["minutes_seconds"] = {"verified_box": e["minutes"]*60, "pbp": seconds(p["Minutes"])}
                if differences:
                    report["source_conflicts"].append({"kind": "PLAYER_BOX", "player_id": pid, "fields": differences})
                else:
                    matching_players += 1
            regulation = 0
            for period in range(1, 5):
                combinations = lineups["stats"][side][str(period)]
                total = 0
                for combination in combinations:
                    ids = lineup_players(combination["EntityId"])
                    if not set(ids) <= expected.keys() or any(expected[i]["team"] != team for i in ids):
                        raise ValueError("Unknown or wrong-team player in lineup")
                    total += seconds(combination["Minutes"])
                    lineup_count += 1
                if abs(total - 720) > 2:
                    raise ValueError("Quarter lineup time does not conserve 12 minutes")
                regulation += total * 5 / 60
            team_minutes[team] = regulation
        possession_count, duration, regulation_seconds = 0, [], 0
        for side in ("Offense", "Defense"):
            document, meta = fetch("/get-possessions/nba", {"Season": season, "SeasonType": "Regular Season",
                "TeamId": str(game["home_team_id"]), "FromDate": date, "ToDate": date, "OffDef": side},
                out, side.lower() + ".json", source_dir)
            report["source_receipts"].append(meta)
            possessions = document["possessions"]
            if not possessions or len(possessions) >= 500:
                raise ValueError("Empty or potentially truncated possession source")
            for row in possessions:
                if row["GameId"] != game_id or row["GameDate"] != date:
                    raise ValueError("Possession query returned a different game")
                start, end = seconds(row["StartTime"]), seconds(row["EndTime"])
                period = int(row["Period"])
                if not 1 <= period <= 20 or not 0 <= end <= start <= (720 if period <= 4 else 300):
                    raise ValueError("Possession clock or period is invalid")
                duration.append(start - end)
                if period <= 4:
                    regulation_seconds += start - end
            team = game["home_team_tricode"] if side == "Offense" else game["away_team_tricode"]
            # Sparse PBP event counts omit zeros. The independent box-score total
            # still has to agree exactly; this never fills missing box-score data.
            attempts = sum(p.get("FG2A", 0) + p.get("FG3A", 0) for p in possessions)
            expected_attempts = sum(r["fga"] for r in verified if r["team"] == team)
            if attempts != expected_attempts:
                report["source_conflicts"].append({"kind": "POSSESSION_FGA", "team": team,
                    "verified_box": expected_attempts, "pbp": attempts})
            possession_count += len(possessions)
        if regulation_seconds != 48 * 60:
            raise ValueError("Possession intervals do not conserve 48 minutes of regulation clock")
        report.update(status="PARTIAL_PBP_SOURCE_CONFLICTS" if report["source_conflicts"] else "CROSSCHECKED_REAL_GAME_PBP_AND_LINEUP_AGGREGATES",
                      game_date=date, played_players_checked=len(observed_ids), played_players_crosschecked=matching_players,
                      quarter_lineup_combinations=lineup_count, regulation_team_minutes=team_minutes,
                      observed_possessions=possession_count, regulation_possession_clock_seconds=regulation_seconds,
                      mean_possession_clock_seconds=statistics.mean(duration),
                      note="Postgame historical evidence for model fitting. Quarter lineup aggregates are not ordered stints or pregame rotation forecasts.")
    except Exception as exc:
        report.update(status="BLOCKED_PBP_SOURCE_OR_RECONCILIATION", error=type(exc).__name__ + ": " + str(exc)[:500])
    report["input_evidence_database_unchanged"] = before == digest(evidence_db)
    write_json(out / "pbp-audit.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game", required=True)
    p.add_argument("--archive-dir", required=True)
    p.add_argument("--evidence-db", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--source-dir", help="Replay previously retained raw provider documents, without refetching")
    a = p.parse_args()
    result = audit_game(a.game, a.archive_dir, a.evidence_db, a.out_dir, a.source_dir)
    print(json.dumps(result, indent=2))
    if result["status"] != "CROSSCHECKED_REAL_GAME_PBP_AND_LINEUP_AGGREGATES":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
