"""Normalize captured public prop rows into an immutable BENFRANK v5.2 board.

Inputs are JSON rows from a lawful public source or manually supplied screenshot
extraction. No claim of native PrizePicks authenticated live-line access.
Requires authoritative schedule entries with UTC tipoff times and team IDs.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

ALIASES={"pts":"points","points":"points","reb":"rebounds","rebounds":"rebounds",
 "ast":"assists","assists":"assists","3pm":"threes","threes":"threes",
 "pra":"pra","points+rebounds+assists":"pra","fantasy score":"fantasy_score",
 "fantasy_score":"fantasy_score","steals":"steals","blocks":"blocks",
 "turnovers":"turnovers"}
REQUIRED=("player","market","line","team","opponent","game_date",
          "tipoff_utc","source","captured_at_utc")

def timestamp(value):
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("TIMEZONE_REQUIRED")
    return d.astimezone(timezone.utc)

def normalize(rows, *, cutoff_utc, max_age_hours=24):
    cutoff=timestamp(cutoff_utc)
    accepted=[]; rejected=[]; seen=set()
    for index,row in enumerate(rows):
        try:
            missing=[k for k in REQUIRED if not row.get(k) and row.get(k)!=0]
            if missing: raise ValueError("MISSING_FIELDS:"+",".join(missing))
            market=ALIASES.get(str(row["market"]).strip().lower())
            if not market: raise ValueError("UNSUPPORTED_MARKET")
            line=row["line"]
            if isinstance(line,bool) or not isinstance(line,(int,float)) or not math.isfinite(line) or line<0:
                raise ValueError("INVALID_EXACT_LINE")
            tipoff=timestamp(row["tipoff_utc"])
            captured=timestamp(row["captured_at_utc"])
            if tipoff<=cutoff: raise ValueError("NOT_PREGAME")
            age=(cutoff-captured).total_seconds()
            if age<0: raise ValueError("FUTURE_LINE_CAPTURE")
            if age>max_age_hours*3600: raise ValueError("STALE_LINE")
            if str(row["game_date"])!=tipoff.date().isoformat() and str(row["game_date"])!=(tipoff.date()).isoformat():
                # The league game date can be local, so do not infer it from UTC.
                pass
            if row["team"]==row["opponent"]: raise ValueError("TEAM_OPPONENT_CONFLICT")
            key=(str(row["player"]).casefold(),market,line,row["game_date"],row["team"],row["opponent"])
            if key in seen: raise ValueError("DUPLICATE_EXACT_LINE")
            seen.add(key)
            snapshot=sha256(json.dumps([*key,str(captured),str(row["source"])],default=str).encode()).hexdigest()[:20]
            accepted.append({"snapshot_id":"public_"+snapshot,"player":row["player"],
                "market":market,"line":line,"team":row["team"],"opponent":row["opponent"],
                "game_date":row["game_date"],"tipoff_utc":row["tipoff_utc"],
                "line_capture_utc":row["captured_at_utc"],"source":row["source"],
                "line_authority":"PUBLIC_DISCOVERY_UNATTESTED",
                "native_platform_line_capture_utc":None})
        except (ValueError,TypeError,KeyError) as exc:
            rejected.append({"row":index,"reason":str(exc)})
    return {"board":accepted,"rejected":rejected,"cutoff_utc":cutoff_utc,
            "certified_live_board":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--cutoff-utc",required=True)
    p.add_argument("--max-age-hours",type=float,default=24)
    args=p.parse_args()
    result=normalize(json.loads(Path(args.input).read_text()),
                     cutoff_utc=args.cutoff_utc,max_age_hours=args.max_age_hours)
    root=Path(args.output)
    root.mkdir(parents=True,exist_ok=False)
    (root/"board.json").write_text(json.dumps(result["board"],indent=2)+"\n")
    (root/"discovery_audit.json").write_text(json.dumps({k:v for k,v in result.items() if k!="board"},indent=2)+"\n")
    print(json.dumps({"accepted":len(result["board"]),"rejected":len(result["rejected"])}))
    return 0 if result["board"] else 2

if __name__=="__main__":
    raise SystemExit(main())
