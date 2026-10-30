"""Re-audit saved official evidence without rewriting either historical warehouse.

An immutable successful official response can verify historical games offline.
It never establishes current availability, current API access or prediction skill.
"""
import argparse
import collections
import json
from pathlib import Path

from acquire_history import verification_relation
from engine import FIELDS
from verify_direct_nba import compare
from benfrank_v45_evidence import digest, readonly, write_json


def audit_saved_history(package, baseline=None):
    package = Path(package).resolve()
    database = package / "nba_warehouse.sqlite"
    before = digest(database)
    result = {"certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "database_sha256": before, "official_access": "SAVED_RESPONSES_NOT_LIVE_ACCESS",
              "seasons": [], "failures": []}
    conn = readonly(database)
    try:
        result["sqlite_integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        relation = verification_relation(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT g.*,v.nba_game_id,v.nba_player_id,v.canonical_json FROM games g "
            "LEFT JOIN " + relation + " v USING(player,date,team)")]
        result["warehouse_player_games"] = len(rows)
        result["missing_verification_receipts"] = sum(not r["nba_game_id"] for r in rows)
        result["canonical_receipt_conflicts"] = sum(
            any(r[k] != json.loads(r["canonical_json"]).get(k) for k in FIELDS)
            for r in rows if r["canonical_json"])
        identities = [(r["nba_game_id"], r["nba_player_id"]) for r in rows]
        result["duplicate_official_identities"] = len(identities) - len(set(identities))
        manifest = json.loads((package / "DELIVERY_MANIFEST.json").read_text())
        result["delivery_manifest_database_hash_matches"] = manifest["database_sha256"] == before
        schedule_files = conn.execute("SELECT sha256 FROM source_files "
                                      "WHERE name='nba_stats_schedule_master.parquet'").fetchall()
        if len(schedule_files) != 1:
            raise ValueError("UNIQUE_PINNED_SCHEDULE_REQUIRED")
        neutral_ids = set()
        for r in conn.execute("SELECT payload_json FROM source_records WHERE file_sha256=?",
                              (schedule_files[0][0],)):
            schedule = json.loads(r[0])
            if schedule.get("is_neutral") in (True, "true", "1", 1):
                neutral_ids.add(str(schedule["game_id"]))
        receipts = json.loads((package / "official_evidence/fresh_stats/fetch_receipt.json").read_text())
        for season in sorted({r["season"] for r in rows}):
            name = "league_" + season
            source = package / "official_evidence/fresh_stats" / (name + ".json")
            receipt = [r for r in receipts if r.get("name") == name]
            if (len(receipt) != 1 or receipt[0].get("http_status") != 200 or
                    not receipt[0].get("url", "").startswith("https://stats.nba.com/stats/leaguegamelog?") or
                    receipt[0].get("sha256") != digest(source)):
                raise ValueError("ORIGINAL_OFFICIAL_RESPONSE_HASH_OR_ORIGIN_CONFLICT: " + season)
            dataset = json.loads(source.read_text())["resultSets"][0]
            direct = collections.defaultdict(list)
            for values in dataset["rowSet"]:
                r = dict(zip(dataset["headers"], values))
                direct[(str(r["GAME_ID"]), str(r["PLAYER_ID"]))].append(r)
            selected = [r for r in rows if r["season"] == season]
            conflicts, seen = [], set()
            for row in selected:
                key = row["nba_game_id"], row["nba_player_id"]
                seen.add(key)
                options = direct.get(key, [])
                detail = (compare(row, options[0], season, key[0] in neutral_ids)
                          if len(options) == 1 else {"official_identity_matches": len(options)})
                if detail:
                    conflicts.append({"nba_game_id": key[0], "nba_player_id": key[1], "detail": detail})
            missing = sorted(set(direct) - seen)
            item = {"season": season, "official_records": len(dataset["rowSet"]),
                    "warehouse_records": len(selected), "conflicts": conflicts,
                    "official_records_missing": len(missing), "missing_identities": missing,
                    "official_sha256": digest(source), "original_retrieved_at": receipt[0]["started_utc"],
                    "status": "PASS" if selected and not conflicts and not missing else "FAIL"}
            result["seasons"].append(item)
        if baseline:
            baseline = Path(baseline).resolve()
            baseline_before = digest(baseline)
            original = readonly(baseline)
            try:
                prior = [dict(r) for r in original.execute("SELECT * FROM games")]
            finally:
                original.close()
            current = {(r["player"], r["date"], r["team"]): r for r in rows}
            changed, absent = [], []
            for r in prior:
                key = r["player"], r["date"], r["team"]
                if key not in current:
                    absent.append(key)
                elif any(r[k] != current[key][k] for k in FIELDS):
                    changed.append(key)
            result["comparison_to_github_import"] = {
                "baseline_rows": len(prior), "saved_rows": len(rows),
                "additional_rows": len(rows) - len(prior), "missing_baseline_rows": absent,
                "different_baseline_rows": changed, "baseline_sha256": baseline_before,
                "baseline_unchanged": baseline_before == digest(baseline)}
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result["failures"].append(str(exc))
    finally:
        conn.close()
        result["database_unchanged"] = before == digest(database)
    ok = (result["database_unchanged"] and result.get("sqlite_integrity") == "ok" and
          result.get("delivery_manifest_database_hash_matches") and not result["failures"] and
          not any(result.get(k, 1) for k in ("missing_verification_receipts", "canonical_receipt_conflicts",
                                             "duplicate_official_identities")) and result["seasons"] and
          all(r["status"] == "PASS" for r in result["seasons"]))
    result["status"] = "PASS_COMPLETE_SELECTED_SEASONS" if ok else "FAILED_SAVED_HISTORY_AUDIT"
    result["warning"] = "Complete selected-season logs do not certify shots, forecasts, other seasons or predictions."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = audit_saved_history(args.package, args.baseline)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    write_json(args.out, result)
    print(json.dumps(result, indent=2))
    if result["status"] != "PASS_COMPLETE_SELECTED_SEASONS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
