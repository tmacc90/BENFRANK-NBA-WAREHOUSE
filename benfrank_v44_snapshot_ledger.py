"""Immutable NBA exact-line snapshot ledger, separate from game warehouse.

Never stores screenshot bytes, account details, odds slips or betting identity.
Stores only player-market exact line/game provenance needed for audit.
The user-supplied snapshot still requires independent platform verification.
"""
import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

from benfrank_v44_calibration import check_snapshot

SCHEMA="""CREATE TABLE IF NOT EXISTS exact_line_snapshots (
snapshot_id TEXT PRIMARY KEY,
platform TEXT NOT NULL,
player TEXT NOT NULL,
market TEXT NOT NULL,
line REAL NOT NULL,
opponent TEXT NOT NULL,
game_date TEXT NOT NULL,
captured_at TEXT NOT NULL,
tipoff_utc TEXT NOT NULL,
source_type TEXT NOT NULL,
source_sha256 TEXT,
immutable_sha256 TEXT NOT NULL,
payload_json TEXT NOT NULL,
inserted_at TEXT NOT NULL
);"""

def fingerprint(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def ingest(conn,snapshots):
    if not isinstance(snapshots,list) or not snapshots:
        raise ValueError("Nonempty exact-line snapshot array required")
    conn.execute(SCHEMA)
    inserted=0
    idempotent=0
    with conn:
        for snapshot in snapshots:
            check_snapshot(snapshot)
            if snapshot.get("source_type") not in ("SCREENSHOT_CAPTURE","PLATFORM_API","MANUAL_ENTRY"):
                raise ValueError("source_type must identify origin")
            digest=fingerprint(snapshot)
            source_hash=snapshot.get("source_sha256")
            if source_hash is not None and (
                not isinstance(source_hash,str) or len(source_hash)!=64
                or any(x not in "0123456789abcdef" for x in source_hash.lower())):
                raise ValueError("source_sha256 must be 64-digit hexadecimal")
            sid=snapshot["snapshot_id"]
            if not isinstance(sid,str) or len(sid)>128:
                raise ValueError("snapshot_id invalid")
            old=conn.execute("SELECT immutable_sha256 FROM exact_line_snapshots WHERE snapshot_id=?",(sid,)).fetchone()
            if old:
                if old[0]!=digest:
                    raise ValueError("IMMUTABLE_SNAPSHOT_CONFLICT: changed data requires a new snapshot_id")
                idempotent+=1
                continue
            now=dt.datetime.now(dt.timezone.utc).isoformat()
            conn.execute("""INSERT INTO exact_line_snapshots (
              snapshot_id,platform,player,market,line,opponent,game_date,
              captured_at,tipoff_utc,source_type,source_sha256,immutable_sha256,payload_json,inserted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
             (sid,snapshot["platform"],snapshot["player"],snapshot["market"],snapshot["line"],
              snapshot["opponent"],snapshot["game_date"],snapshot["captured_at"],snapshot["tipoff_utc"],
              snapshot["source_type"],source_hash,digest,json.dumps(snapshot,sort_keys=True),now))
            inserted+=1
    return {"status":"SAVED_IMMUTABLE_PREGAME_SNAPSHOTS",
            "received":len(snapshots),"inserted":inserted,"idempotent":idempotent,
            "total_snapshots":conn.execute("SELECT COUNT(*) FROM exact_line_snapshots").fetchone()[0],
            "calibration_certification":"NOT_CERTIFIED",
            "warning":"Capture metadata alone does not prove the platform really offered the line"}

def export(conn):
    # Export also supports mode=ro connections. Reading must never create a
    # table or a new, misleadingly empty snapshot ledger.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='exact_line_snapshots'").fetchone():
        return []
    rows=conn.execute("SELECT payload_json FROM exact_line_snapshots ORDER BY captured_at,snapshot_id").fetchall()
    return [json.loads(row[0]) for row in rows]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ledger",required=True,help="Separate snapshot-only SQLite path")
    p.add_argument("--board",help="JSON array containing immutable captured pregame lines")
    p.add_argument("--export",help="Export immutable snapshot array for calibration")
    args=p.parse_args()
    if not args.board and not args.export:
        raise SystemExit("Specify --board and/or --export")
    ledger=Path(args.ledger)
    if ledger.name in ("nba_warehouse.sqlite","nba.sqlite"):
        raise ValueError("Do not use an existing historical games warehouse as the snapshot ledger")
    conn=sqlite3.connect(str(ledger))
    try:
        if args.board:
            r=ingest(conn,json.loads(Path(args.board).read_text()))
            print(json.dumps(r,indent=2))
        if args.export:
            Path(args.export).write_text(json.dumps(export(conn),indent=2)+"\n")
    finally:
        conn.close()

if __name__=="__main__":
    main()
