"""Read-only warehouse audit and separate NBA/ESPN shooting evidence rebuild.

Only pinned, independently produced NBA and ESPN archive rows can agree. This
does not promote a secondary feed, infer historical rotations, or certify picks.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from acquire_history import fetch_source, flag, number, team_key, verification_relation, name_key
from engine import FIELDS

SHOT_FIELDS = {"fgm": "field_goals_made", "fga": "field_goals_attempted",
               "fg3m": "three_pointers_made", "fg3a": "three_pointers_attempted",
               "ftm": "free_throws_made", "fta": "free_throws_attempted"}
ESPN_FIELDS = {**SHOT_FIELDS, "fg3m": "three_point_field_goals_made",
               "fg3a": "three_point_field_goals_attempted"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def readonly(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def archive_minutes(value):
    """Permit the archive's explicit :60 rounding carry, never missing minutes."""
    text = str(value).strip()
    if ":" in text:
        m, sec = text.split(":")
        m, sec = number(m, True), number(sec, True)
        if sec > 60:
            raise ValueError("Invalid archive second component")
        result = m + sec / 60
    else:
        result = number(value)
    if not 0 <= result <= 70:
        raise ValueError("Minutes outside 0..70")
    return result


def shots(row, fields):
    values = {key: number(row[field], True) for key, field in fields.items()}
    if any(values[m] > values[a] for m, a in
           (("fgm", "fga"), ("fg3m", "fg3a"), ("ftm", "fta"))):
        raise ValueError("Made shots exceed attempts")
    values.update(fg2m=values["fgm"] - values["fg3m"],
                  fg2a=values["fga"] - values["fg3a"])
    if not 0 <= values["fg2m"] <= values["fg2a"]:
        raise ValueError("Two/three-point accounting conflict")
    if 2 * values["fg2m"] + 3 * values["fg3m"] + values["ftm"] != number(row["points"], True):
        raise ValueError("Shot ledger does not reproduce points")
    return values


def unique_index(rows, keys):
    result = collections.defaultdict(list)
    for row in rows:
        result[tuple(str(row[key]) for key in keys)].append(row)
    return result


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n")


def rebuild(archive_dir, out_dir, manifest="sources.json", crosswalks="identity_crosswalks.json"):
    archive, out = Path(archive_dir).resolve(), Path(out_dir).resolve()
    source_db = archive / "nba_warehouse.sqlite"
    before = digest(source_db)
    if out == archive or archive in out.parents:
        raise ValueError("Output must be separate from the immutable input archive")
    out.mkdir(parents=True, exist_ok=False)
    report = {"version": "4.5", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "auditor_source_sha256": digest(__file__), "source_manifest_sha256": digest(manifest),
              "input_database_sha256": before, "certification": "NOT_CERTIFIED",
              "ticket_authority": "NO_TICKET", "source_authorities": ["NBA_STATS", "ESPN"],
              "full_history_coverage": False, "full_rotation_evidence": False}
    issues = []
    try:
        conn = readonly(source_db)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
            if not {"games", "game_verifications", "source_files"} <= tables:
                raise ValueError("Warehouse is missing source-verification tables")
            integrity = [r[0] for r in conn.execute("PRAGMA integrity_check")]
            relation = verification_relation(conn)
            games = [dict(r) for r in conn.execute("SELECT * FROM games ORDER BY date,team,player")]
            verifications = [dict(r) for r in conn.execute("SELECT * FROM " + relation)]
            stored_files = {r["sha256"] for r in conn.execute("SELECT sha256 FROM source_files")}
            duplicate_ids = conn.execute("SELECT COUNT(*) FROM (SELECT nba_game_id,nba_player_id "
                "FROM " + relation + " GROUP BY 1,2 HAVING COUNT(*)>1)").fetchone()[0]
        finally:
            conn.close()
        verification = {(r["player"], r["date"], r["team"]): r for r in verifications}
        missing_receipts, mismatched_receipts = 0, 0
        for game in games:
            v = verification.get((game["player"], game["date"], game["team"]))
            if not v:
                missing_receipts += 1
                continue
            original = json.loads(v["canonical_json"])
            if any(game[k] != original.get(k) for k in FIELDS):
                mismatched_receipts += 1
        report.update(input_player_games=len(games), sqlite_integrity=integrity,
                      duplicate_official_identities=duplicate_ids,
                      missing_verification_receipts=missing_receipts,
                      canonical_receipt_disagreements=mismatched_receipts)
        if integrity != ["ok"] or any((duplicate_ids, missing_receipts, mismatched_receipts)) or not games:
            raise ValueError("Input warehouse integrity/identity/receipt gate failed")
        specs = json.loads(Path(manifest).read_text())["sources"]
        sources, source_receipts, authority_hashes = {}, [], {}
        for spec in specs:
            rows, meta = fetch_source(spec, archive / "source", offline=True)
            if meta["actual_sha256"] not in stored_files:
                raise ValueError("Pinned source absent from original database source manifest")
            sources[(spec["kind"], spec.get("year"))] = rows
            authority_hashes[(spec["kind"], spec.get("year"))] = meta["actual_sha256"]
            source_receipts.append({k: meta[k] for k in ("name", "provider", "url", "actual_sha256", "input_rows")})
        report["source_files"] = source_receipts
        nba_rows = [r for (kind, _), rows in sources.items() if kind == "nba_box" for r in rows]
        espn_rows = [r for (kind, _), rows in sources.items() if kind == "espn_box" for r in rows]
        nindex = unique_index(nba_rows, ("game_id", "person_id"))
        eindex = unique_index(espn_rows, ("game_id", "athlete_id"))
        schedule = {str(r["game_id"]): r for r in sources[("schedule", None)]
                    if str(r["season_type_id"]) == "2" and r["game_status"] == 3}
        output_db = out / "verified_evidence.sqlite"
        dest = sqlite3.connect(output_db)
        dest.executescript("""
        CREATE TABLE verified_shooting (
          nba_game_id TEXT,nba_player_id TEXT,espn_game_id TEXT,espn_player_id TEXT,
          player TEXT,game_date TEXT,team TEXT,opponent TEXT,minutes REAL,starter INTEGER,
          fgm INTEGER,fga INTEGER,fg3m INTEGER,fg3a INTEGER,ftm INTEGER,fta INTEGER,
          fg2m INTEGER,fg2a INTEGER,nba_sha256 TEXT,espn_sha256 TEXT,
          authority TEXT NOT NULL,PRIMARY KEY(nba_game_id,nba_player_id));
        CREATE TABLE verified_starting_fives (
          nba_game_id TEXT,team TEXT,game_date TEXT,nba_player_ids_json TEXT,
          espn_player_ids_json TEXT,authority TEXT NOT NULL,PRIMARY KEY(nba_game_id,team));
        CREATE TABLE evidence_manifest (key TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
        """)
        starter_nba = collections.defaultdict(list)
        starter_espn = collections.defaultdict(list)
        id_map = collections.defaultdict(set)
        game_map = collections.defaultdict(set)
        for v in verifications:
            id_map[v["nba_player_id"]].add(v["espn_player_id"])
            game_map[v["nba_game_id"]].add(v["espn_game_id"])
        report["identity_crosswalks_used"] = []
        if crosswalks and Path(crosswalks).is_file():
            crosswalk_document = json.loads(Path(crosswalks).read_text())
            report["identity_crosswalk_manifest_sha256"] = digest(crosswalks)
            for mapping in crosswalk_document["entries"]:
                nid, eid = mapping["nba_player_id"], mapping["espn_player_id"]
                expected_url = "https://www.nba.com/player/" + nid
                if (mapping["nba_profile_url"] != expected_url or
                        mapping["nba_profile_name_observed"] != mapping["canonical_name"] or
                        mapping["espn_archive_sha256"] not in stored_files):
                    raise ValueError("Identity crosswalk missing authoritative source linkage")
                archived_names = {(str(n["first_name"]) + " " + str(n["family_name"])).strip()
                                  for n in nba_rows if str(n["person_id"]) == nid}
                if not archived_names or not archived_names <= {mapping["archived_nba_name"], mapping["canonical_name"]}:
                    raise ValueError("Identity crosswalk does not identify the actual archived NBA player")
                candidates = {str(e["athlete_id"]) for e in espn_rows
                              if name_key(e["athlete_display_name"]) == name_key(mapping["canonical_name"])}
                if candidates != {eid} or (id_map[nid] and id_map[nid] != {eid}):
                    raise ValueError("Identity crosswalk is ambiguous or contradicts verified stable IDs")
                id_map[nid].add(eid)
                report["identity_crosswalks_used"].append(mapping)
        for n in nba_rows:
            if str(n.get("position") or "").strip() and str(n.get("season_type_id")) == "2":
                starter_nba[(str(n["game_id"]), team_key(n["team_tricode"]))].append(str(n["person_id"]))
        for e in espn_rows:
            if str(e.get("season_type")) == "2" and str(e.get("starter")).lower() == "true":
                starter_espn[(str(e["game_id"]), team_key(e["team_abbreviation"]))].append(str(e["athlete_id"]))
        confirmed_teams = set()
        for (gid, team), players in starter_nba.items():
            if gid not in schedule or len(players) != 5 or len(set(players)) != 5 or len(game_map[gid]) != 1:
                continue
            if any(len(id_map[p]) != 1 for p in players):
                continue
            egid = next(iter(game_map[gid]))
            eplayers = starter_espn[(egid, team)]
            mapped = {next(iter(id_map[p])) for p in players}
            if len(eplayers) == 5 and len(set(eplayers)) == 5 and mapped == set(eplayers):
                dest.execute("INSERT INTO verified_starting_fives VALUES (?,?,?,?,?,?)",
                             (gid, team, str(schedule[gid]["game_date_est"])[:10],
                              json.dumps(sorted(players)), json.dumps(sorted(eplayers)),
                              "NBA_STATS_ARCHIVE_AND_ESPN_ARCHIVE_CROSSCHECKED"))
                confirmed_teams.add((gid, team))
        carried = 0
        for game in games:
            v = verification[(game["player"], game["date"], game["team"])]
            identity = {k: v[k] for k in ("nba_game_id", "nba_player_id", "espn_game_id", "espn_player_id")}
            try:
                nn = nindex[(v["nba_game_id"], v["nba_player_id"])]
                ee = eindex[(v["espn_game_id"], v["espn_player_id"])]
                if len(nn) != 1 or len(ee) != 1:
                    raise ValueError("Source player/game identity is missing or ambiguous")
                n, e = nn[0], ee[0]
                if str(n["season_type_id"]) != "2" or str(e["season_type"]) != "2" or flag(e["did_not_play"]):
                    raise ValueError("Appearance not explicitly regular-season played")
                if team_key(n["team_tricode"]) != game["team"] or team_key(e["team_abbreviation"]) != game["team"]:
                    raise ValueError("Source team identity conflict")
                if e["game_date"] != game["date"] or team_key(e["opponent_team_abbreviation"]) != game["opponent"]:
                    raise ValueError("Source date/opponent conflict")
                if v["official_file_sha256"] not in stored_files or v["espn_file_sha256"] not in stored_files:
                    raise ValueError("Missing original source hash")
                if (v["official_file_sha256"] != authority_hashes[("nba_box", int(n["season"]))] or
                        v["espn_file_sha256"] != authority_hashes[("espn_box", int(e["season"]))]):
                    raise ValueError("Receipt source hash does not identify the actual season input")
                scheduled = schedule[v["nba_game_id"]]
                side, other = ("home", "away") if game["home"] else ("away", "home")
                if (str(scheduled["game_date_est"])[:10] != game["date"] or n["side"] != side or e["home_away"] != side
                        or team_key(scheduled[side + "_team_tricode"]) != game["team"]
                        or team_key(scheduled[other + "_team_tricode"]) != game["opponent"]
                        or number(e["team_score"], True) != scheduled[side + "_team_score"]
                        or number(e["opponent_team_score"], True) != scheduled[other + "_team_score"]):
                    raise ValueError("Official schedule/home-away/final-score crosscheck failed")
                for core, nba_field, espn_field in (("pts", "points", "points"),
                        ("reb", "rebounds_total", "rebounds"), ("ast", "assists", "assists"),
                        ("stl", "steals", "steals"), ("blk", "blocks", "blocks"), ("tov", "turnovers", "turnovers")):
                    if number(n[nba_field], True) != game[core] or number(e[espn_field], True) != game[core]:
                        raise ValueError("Original counting-stat source conflict: " + core)
                minutes = archive_minutes(n["minutes"])
                if abs(minutes - archive_minutes(e["minutes"])) > 1 or minutes != game["minutes"]:
                    raise ValueError("Source minutes conflict")
                if (int(bool(str(n["position"] or "").strip())) != game["starter"] or
                        flag(e["starter"]) != game["starter"] or
                        (v["nba_game_id"], game["team"]) not in confirmed_teams):
                    raise ValueError("Independent starting-five crosscheck incomplete")
                ns, es = shots(n, SHOT_FIELDS), shots(e, ESPN_FIELDS)
                if ns != es or number(n["points"], True) != game["pts"]:
                    raise ValueError("NBA/ESPN shot-attempt conflict")
                if str(n["minutes"]).endswith(":60"):
                    carried += 1
                dest.execute("INSERT INTO verified_shooting VALUES (" + ",".join("?" * 21) + ")",
                             (*identity.values(), game["player"], game["date"], game["team"], game["opponent"],
                              minutes, game["starter"], *(ns[k] for k in ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "fg2m", "fg2a")),
                              v["official_file_sha256"], v["espn_file_sha256"],
                              "NBA_STATS_ARCHIVE_AND_ESPN_ARCHIVE_CROSSCHECKED"))
            except (KeyError, TypeError, ValueError) as exc:
                issues.append({**identity, "reason": str(exc)})
        verified_ids = {(v["nba_game_id"], v["nba_player_id"]) for v in verifications}
        missing_ids, uncertain_zero = [], []
        for n in nba_rows:
            gid, pid = str(n["game_id"]), str(n["person_id"])
            if gid not in schedule or not str(n.get("minutes") or "").strip():
                continue
            try:
                m = archive_minutes(n["minutes"])
                if m == 0:
                    uncertain_zero.append({"nba_game_id": gid, "nba_player_id": pid})
                elif (gid, pid) not in verified_ids:
                    missing_ids.append({"nba_game_id": gid, "nba_player_id": pid})
            except ValueError as exc:
                missing_ids.append({"nba_game_id": gid, "nba_player_id": pid, "reason": str(exc)})
        count = dest.execute("SELECT COUNT(*) FROM verified_shooting").fetchone()[0]
        report.update(verified_shooting_player_games=count,
                      shooting_rejections=len(issues), verified_starting_team_games=len(confirmed_teams),
                      missing_positive_minute_player_games=len(missing_ids),
                      zero_minute_rows_requiring_explicit_played_evidence=len(uncertain_zero),
                      archive_second_carries=carried,
                      shot_rejection_reasons=dict(collections.Counter(x["reason"] for x in issues)),
                      source_coverage_status="PARTIAL" if missing_ids or uncertain_zero else "COMPLETE_IN_PINNED_ARCHIVE",
                      status="AUDITED_PARTIAL_COVERAGE" if missing_ids or uncertain_zero or issues else "AUDITED_ARCHIVE_SCOPE")
        report["warning"] = "Starting fives are verified postgame facts, not historical pregame forecasts or full substitution rotations."
        write_json(out / "shooting_rejections.json", issues)
        write_json(out / "missing_player_games.json", missing_ids)
        write_json(out / "zero_minute_review.json", uncertain_zero)
        dest.execute("INSERT INTO evidence_manifest VALUES (?,?)", ("audit", json.dumps(report, sort_keys=True)))
        dest.commit()
        dest.close()
        report["evidence_database_sha256"] = digest(output_db)
    except Exception as exc:
        report.update(status="FAILED_INTEGRITY_OR_SOURCE_GATE", error=type(exc).__name__ + ": " + str(exc))
    finally:
        report["input_database_sha256_after"] = digest(source_db)
        report["input_database_unchanged"] = before == report["input_database_sha256_after"]
        write_json(out / "audit.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--manifest", default="sources.json")
    p.add_argument("--identity-crosswalks", default="identity_crosswalks.json")
    args = p.parse_args()
    result = rebuild(args.archive_dir, args.out_dir, args.manifest, args.identity_crosswalks)
    print(json.dumps(result, indent=2))
    if result["status"] == "FAILED_INTEGRITY_OR_SOURCE_GATE" or not result["input_database_unchanged"]:
        raise SystemExit(1)
    if result["status"] == "AUDITED_PARTIAL_COVERAGE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
