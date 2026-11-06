"""Reproducible software checks and separately labelled live-data replays.

All sample lines here are declared test thresholds, not sportsbook quotes.
This script never turns retrospective results into forward calibration data.
"""
import argparse
import datetime as dt
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benfrank_omni import VERSION
from benfrank_omni.contracts import CONTEXT_KEYS, SPORTS, canonical, now, sha, timestamp, validate_prop
from benfrank_omni.runner import run
from benfrank_omni.sources import Capture, collect_history

SAMPLES = {
    "NBA": ("Stephen Curry", "3975", "points", 24.5, {}),
    "NFL": ("Patrick Mahomes", "3139477", "passing_yards", 249.5, {}),
    "NHL": ("Leon Draisaitl", "3114727", "shots_on_goal", 3.5, {}),
    "WNBA": ("A'ja Wilson", "3149391", "points", 25.5, {}),
    "MLB": ("Aaron Judge", "33192", "hits", 1.5, {"role": "hitter"}),
    "NCAAB": ("Cooper Flagg", "5041939", "points", 19.5, {}),
    "CFB": ("Arch Manning", "4870906", "passing_yards", 249.5, {}),
    "SOCCER": ("Erling Haaland", "253989", "shots", 3.5, {"competition": "uefa.champions", "extra_time": "INCLUDED_IF_PLAYED"}),
    "F1": ("Max Verstappen", "max_verstappen", "finishing_position", 3.5, {"session": "RACE"}),
    "TENNIS": ("Novak Djokovic", "104925", "aces", 5.5, {"surface": "Hard", "best_of": 3}),
}


def initial(sport, player, pid, market, line, rules):
    stamp = now()
    return {"sport": sport, "player": player, "player_id": pid, "market": market, "line": line, "opponent": "TEST_OPPONENT", "event_id": "TEST_ONLY_EVENT", "event_start_utc": (timestamp(stamp) + dt.timedelta(days=1)).isoformat(), "captured_at_utc": stamp, "line_source": "DECLARED_SOFTWARE_TEST_THRESHOLD_NOT_A_BOOK_QUOTE", "scope": "FULL_MATCH" if sport == "TENNIS" else "FULL_RACE" if sport == "F1" else "FULL_GAME", "rules": {"push": "PUSH", "void": "DNP_OR_PLATFORM_VOID_RULE", **rules}}


def software(root):
    root.mkdir(parents=True, exist_ok=False)
    props = []
    cutoff = "2025-12-01T18:00:00Z"
    for sport, spec in SPORTS.items():
        market = spec["markets"][0]
        p = initial(sport, "Software Test Player", "fixture", market, 10.5, {k: "TEST_RULE" for k in CONTEXT_KEYS.get(sport, [])})
        p.update(event_start_utc="2025-12-02T18:00:00Z", captured_at_utc=cutoff)
        start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
        rows = [{"sport": sport, "player": p["player"], "player_id": p["player_id"], "game_id": str(i), "start_utc": (start + dt.timedelta(days=i)).isoformat(), "season": "2025", "scope": p["scope"], "opponent": "TEST_OPPONENT", "stats": {market: i%20}, "workload": 25+i%5, "workload_unit": "TEST_OPPORTUNITIES", "completed": True, "context": {k: "TEST_RULE" for k in CONTEXT_KEYS.get(sport, [])}} for i in range(60)]
        source = root / (sport.lower() + "_fixture.json")
        source.write_bytes(canonical({"sport": sport, "captured_at_utc": "2025-11-30T18:00:00Z", "generation_history": "SYNTHETIC_SOFTWARE_FIXTURE_NOT_REAL_ATHLETE_DATA", "games": rows}))
        p["history_sources"] = [{"provider": "normalized_json", "file": str(source.resolve()), "sha256": sha(source.read_bytes())}]
        props.append(p)
    manifest = root / "batch.json"
    manifest.write_bytes(canonical({"mode": "SOFTWARE_TEST", "cutoff_utc": cutoff, "collect_opponent_context": False, "props": props}))
    summary, code = run(manifest, root / "run", root / "state")
    if summary["completed_props"] != len(SPORTS):
        code = 2
    return summary, code


def live(root, sports):
    root.mkdir(parents=True, exist_ok=False)
    results = []
    for sport in sports:
        capture = Capture(root / sport.lower() / "live_sources")
        try:
            if sport not in SAMPLES:
                raise ValueError("NO_CONFIGURED_LIVE_SAMPLE_FOR_SPECIALIST_FEED")
            player, pid, market, line, rules = SAMPLES[sport]
            p = initial(sport, player, pid, market, line, rules)
            if sport == "F1":
                configs = [{"provider": "jolpi", "seasons": [2024, 2025]}]
            elif sport == "TENNIS":
                configs = [{"provider": "tennis_csv", "urls": [f"https://raw.githubusercontent.com/farhadGithub/tennis-atp-data/main/data/raw/atp_matches_{year}.csv" for year in (2022, 2023, 2024)]}]
            else:
                configs = [{"provider": "espn", "seasons": [2024, 2025]}]
            rows, failures = collect_history(p, configs, capture)
            usable = [g for g in rows if g.get("completed") and g.get("start_utc")]
            # Test a held-out historical game, with its result excluded by ID and time.
            latest = max(usable, key=lambda g: timestamp(g["start_utc"]))
            cutoff = (timestamp(latest["start_utc"]) - dt.timedelta(hours=18, minutes=1)).isoformat()
            p.update(event_id=latest["game_id"], event_start_utc=latest["start_utc"], captured_at_utc=cutoff, opponent=latest["opponent"])
            source = root / sport.lower() / "captured_history.json"
            source.write_bytes(canonical({"sport": sport, "captured_at_utc": now(), "upstream_captures": capture.receipts, "games": rows}))
            p["history_sources"] = [{"provider": "normalized_json", "file": str(source.resolve()), "sha256": sha(source.read_bytes())}]
            manifest = root / sport.lower() / "replay_request.json"
            manifest.write_bytes(canonical({"mode": "RESEARCH_REPLAY", "cutoff_utc": cutoff, "collect_opponent_context": False, "props": [p]}))
            summary, code = run(manifest, root / sport.lower() / "replay", root / "state")
            results.append({"sport": sport, "status": "LIVE_CAPTURE_AND_RETROSPECTIVE_MODEL_VERIFIED" if code == 0 else "MODEL_BLOCKED", "captured_games": len(rows), "upstream_source_count": len(capture.receipts), "summary": summary, "forward_prediction": False, "line_is_platform_quote": False})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            results.append({"sport": sport, "status": "SOURCE_OR_MODEL_BLOCKED", "reason": str(exc), "forward_prediction": False})
        finally:
            capture.save()
        print(json.dumps(results[-1]), flush=True)
    result = {"version": VERSION, "created_at_utc": now(), "results": results, "accuracy_certified": False, "calibration_training_from_replays": False}
    (root / "live_validation.json").write_bytes(canonical(result))
    return result, 0 if all(r["status"] == "LIVE_CAPTURE_AND_RETROSPECTIVE_MODEL_VERIFIED" for r in results) else 2


def export(root):
    root.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    catalog = json.loads((repo / "architecture/benfrank_multisport_catalog.json").read_text())
    for sport, spec in SPORTS.items():
        isolated = {**catalog, "sports": [spec]}
        with zipfile.ZipFile(root / (spec["repository"] + "_runtime.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("architecture/benfrank_multisport_catalog.json", json.dumps(isolated, indent=2))
            for path in sorted((repo / "benfrank_omni").glob("*.py")):
                archive.write(path, "benfrank_omni/" + path.name)
            archive.write(repo / "benfrank_v44_blind_worker.py", "benfrank_v44_blind_worker.py")
            archive.write(repo / "docs/OMNI_EXECUTION.md", "docs/OMNI_EXECUTION.md")
            archive.write(repo / "run_framework.py", "run_framework.py")
            archive.writestr("README.md", f"# {sport} isolated BENFRANK runtime\n\nRun `python -m benfrank_omni run --input props.json --output runs/new --state-dir state`.\nOnly {sport} is registered in this package. See docs/OMNI_EXECUTION.md for input and verification requirements.\nThe runtime uses Python 3.11+ and the standard library. Exporting does not create a repository or certify betting accuracy.\n")
            archive.writestr("DEPLOYMENT.json", json.dumps({"sport": sport, "version": VERSION, "target_repository": spec["repository"], "separate_credentials_data_models_calibration_ledger": True, "accuracy_certified": False}, indent=2))
    return {"isolated_sport_packages": len(SPORTS), "output": str(root)}, 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("software", "live", "export"), default="software")
    parser.add_argument("--sports", default=",".join(SAMPLES))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    result, code = live(root, args.sports.split(",")) if args.mode == "live" else export(root) if args.mode == "export" else software(root)
    print(json.dumps(result, indent=2))
    raise SystemExit(code)
