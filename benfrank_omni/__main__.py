"""CLI for execution, verification, settlement and calibration."""
import argparse
import json
from pathlib import Path

from .contracts import SPORTS, now, sha
from .ledger import calibrate, settle
from .runner import run, verify_run


def main():
    p = argparse.ArgumentParser(prog="python -m benfrank_omni")
    sub = p.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--input", required=True)
    execute.add_argument("--output", required=True)
    execute.add_argument("--state-dir", default="omni_state")
    execute.add_argument("--trials", type=int, default=25000)
    execute.add_argument("--seed", type=int, default=1729)
    verify = sub.add_parser("verify")
    verify.add_argument("--run", required=True)
    cal = sub.add_parser("calibrate")
    cal.add_argument("--sport", choices=SPORTS, required=True)
    cal.add_argument("--market", required=True)
    cal.add_argument("--state-dir", default="omni_state")
    grade = sub.add_parser("settle")
    grade.add_argument("--sport", choices=SPORTS, required=True)
    grade.add_argument("--input", required=True)
    grade.add_argument("--state-dir", default="omni_state")
    catalog = sub.add_parser("status")
    args = p.parse_args()
    if args.command == "run":
        result, code = run(args.input, args.output, args.state_dir, args.trials, args.seed)
    elif args.command == "verify":
        result, code = verify_run(args.run), 0
    elif args.command == "calibrate":
        result = calibrate(args.state_dir, args.sport, args.market)
        code = 0 if all(r["status"] == "VALIDATED_HOLDOUT" for r in result) else 2
    elif args.command == "settle":
        data = json.loads(Path(args.input).read_text())
        result, code = settle(args.state_dir, args.sport, data["outcomes"]), 0
    else:
        from .sources import ESPN
        result = [{"sport": sport, "repository_target": spec["repository"], "runtime": "IMPLEMENTED", "automatic_history_provider": "espn" if sport in ESPN else "jolpi" if sport == "F1" else "CONFIGURED_SPECIALIST_SOURCE_REQUIRED", "normalized_json_adapter": "IMPLEMENTED", "model_namespace": spec["model_id"], "accuracy_certified": False, "independent_repository_deployed": False} for sport, spec in SPORTS.items()]
        code = 0
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
