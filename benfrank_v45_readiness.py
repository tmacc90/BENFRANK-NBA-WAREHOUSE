"""Audit the separate immutable snapshot ledger without altering it."""
import argparse
import collections
import json
from pathlib import Path

from benfrank_v44_calibration import check_snapshot
from benfrank_v44_snapshot_ledger import fingerprint
from benfrank_v45_evidence import digest, readonly, write_json


def inspect_ledger(ledger=None, evidence_root=None, minimum=50):
    result = {"status": "BLOCKED_NO_SNAPSHOT_LEDGER", "total_snapshots": 0,
              "eligible_metadata_snapshots": 0, "source_linked_snapshots": 0,
              "selected_outcomes": 0, "minimum_for_exploratory_evaluation": minimum,
              "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET",
              "selection_policy": "FIRST_CAPTURE_PER_PLATFORM_PLAYER_MARKET_GAME",
              "warning": "50 is an execution minimum, not a certification threshold. A hash alone does not attest platform authenticity.",
              "eligible_snapshots": [], "rejections": []}
    if not ledger or not Path(ledger).is_file():
        result["next_fix"] = "Supply the separate exact_line_snapshots ledger and original capture files."
        return result
    before = digest(ledger)
    conn = readonly(ledger)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='exact_line_snapshots'").fetchone():
            result["status"] = "BLOCKED_WRONG_LEDGER_SCHEMA"
            return result
        entries = [dict(r) for r in conn.execute("SELECT * FROM exact_line_snapshots ORDER BY captured_at,snapshot_id")]
    finally:
        conn.close()
    result["total_snapshots"] = len(entries)
    valid = []
    for row in entries:
        try:
            snapshot = json.loads(row["payload_json"])
            capture, tipoff = check_snapshot(snapshot)
            if fingerprint(snapshot) != row["immutable_sha256"]:
                raise ValueError("IMMUTABLE_PAYLOAD_HASH_MISMATCH")
            for key in ("snapshot_id", "platform", "player", "market", "line", "opponent",
                        "game_date", "captured_at", "tipoff_utc", "source_type", "source_sha256"):
                if snapshot.get(key) != row.get(key):
                    raise ValueError("LEDGER_COLUMN_PAYLOAD_CONFLICT: " + key)
            result["eligible_metadata_snapshots"] += 1
            raw_hash, relative = snapshot.get("source_sha256"), snapshot.get("source_file")
            if not evidence_root or not raw_hash or not relative:
                raise ValueError("ORIGINAL_CAPTURE_FILE_REQUIRED")
            root = Path(evidence_root).resolve()
            source = (root / relative).resolve()
            if root not in source.parents or not source.is_file():
                raise ValueError("CAPTURE_FILE_OUTSIDE_EVIDENCE_ROOT_OR_MISSING")
            if digest(source) != raw_hash:
                raise ValueError("ORIGINAL_CAPTURE_HASH_MISMATCH")
            if not snapshot.get("game_id"):
                raise ValueError("STABLE_GAME_ID_REQUIRED")
            if str(snapshot["opponent"]).startswith("UNRESOLVED_"):
                raise ValueError("PLAYER_GAME_TEAM_MAPPING_REQUIRED")
            if snapshot["source_type"] not in ("PLATFORM_API", "SCREENSHOT_CAPTURE"):
                raise ValueError("MANUAL_ENTRY_REQUIRES_INDEPENDENT_CAPTURE")
            if snapshot["source_type"] == "PLATFORM_API":
                from benfrank_v45_odds import capture_matches
                if snapshot.get("source_provider") != "THE_ODDS_API" or not capture_matches(snapshot, source):
                    raise ValueError("PLATFORM_LINE_DOES_NOT_MATCH_ORIGINAL_RESPONSE")
            result["source_linked_snapshots"] += 1
            valid.append((capture, row["snapshot_id"], snapshot))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            result["rejections"].append({"snapshot_id": row["snapshot_id"], "reason": str(exc)})
    chosen = {}
    for _, _, snapshot in sorted(valid, key=lambda x: (x[0], x[1])):
        key = (snapshot["platform"].strip().casefold(), snapshot["player"], snapshot["market"],
               snapshot["game_id"], snapshot.get("scoring_contract"))
        chosen.setdefault(key, snapshot)
    selected = sorted(chosen.values(), key=lambda s: (check_snapshot(s)[1], s["snapshot_id"]))
    result.update(selected_outcomes=len(selected), eligible_snapshots=selected,
                  duplicate_or_moved_line_captures_excluded=len(valid) - len(selected),
                  per_platform_market=dict(collections.Counter(s["platform"] + "|" + s["market"] for s in selected)),
                  ledger_sha256=before, ledger_unchanged=before == digest(ledger),
                  status="READY_FOR_UNCERTIFIED_BACKTEST" if len(selected) >= minimum
                  else "BLOCKED_INSUFFICIENT_SOURCE_LINKED_SNAPSHOTS",
                  next_fix="Collect original pregame exact-line captures across independent games; review per-market coverage.")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger")
    p.add_argument("--evidence-root")
    p.add_argument("--out", required=True)
    p.add_argument("--require-ready", action="store_true")
    a = p.parse_args()
    result = inspect_ledger(a.ledger, a.evidence_root)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    write_json(a.out, result)
    print(json.dumps({k: v for k, v in result.items() if k != "eligible_snapshots"}, indent=2))
    if a.require_ready and result["status"] != "READY_FOR_UNCERTIFIED_BACKTEST":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
