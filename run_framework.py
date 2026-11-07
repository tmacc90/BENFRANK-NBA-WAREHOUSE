"""One-command NBA framework entrypoint with auditable evidence-only fallback.
Examples:
 python run_framework.py --input verified_props.json --output runs/20261103
 python run_framework.py --config v52_config.json --output runs/20261103
The first mode is historical NBA MLB-mirror research, NOT simulated forecasts.
The second executes the existing physical v6 pipeline, never silently substitutes.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

def execute(args):
    if getattr(args,"auto",None):
        if args.input or args.config or getattr(args,"omni",None):
            raise ValueError("AUTO_REQUIRES_EXCLUSIVE_INPUT_MODE")
        from benfrank_auto_runner import run
        result,code=run(args.auto,args.output,getattr(args,"state_dir","auto_state"),
            getattr(args,"trials",25000),getattr(args,"stress_trials",2000))
        return code
    if getattr(args,"omni",None):
        if args.input or args.config:
            raise ValueError("OMNI_REQUIRES_EXCLUSIVE_INPUT_MODE")
        from benfrank_omni.runner import run
        result,code=run(args.omni,args.output,getattr(args,"state_dir","omni_state"),
                        getattr(args,"trials",25000),getattr(args,"seed",1729))
        print(json.dumps(result,indent=2))
        return code
    if bool(args.input)==bool(args.config):
        raise ValueError("SUPPLY_EXACTLY_ONE_OF_INPUT_OR_CONFIG")
    root=Path(args.output)
    if root.exists(): raise FileExistsError("IMMUTABLE_RUN_DIRECTORY_EXISTS")
    root.mkdir(parents=True)
    source=Path(args.input or args.config)
    raw=source.read_bytes()
    mode="historical_research" if args.input else "physical_pipeline"
    command=[sys.executable,str(Path(__file__).with_name(
        "benfrank_nba_run_framework.py" if args.input else "benfrank_v60_run.py"))]
    if args.input:
        command+=["--input",str(source),"--output",str(root/"research.json")]
    else:
        command+=["--config",str(source),"--output",str(root/"physical")]
    result=subprocess.run(command,capture_output=True,text=True,check=False)
    (root/"stdout.txt").write_text(result.stdout)
    (root/"stderr.txt").write_text(result.stderr)
    receipt={"mode":mode,"input_sha256":hashlib.sha256(raw).hexdigest(),
             "exit_code":result.returncode,"certified":False,
             "physical_simulations_verified":False,
             "blind_ai_independence_verified":False}
    if args.input and (root/"research.json").exists():
        data=json.loads((root/"research.json").read_text())
        lines=["# 🏀 BENFRANK NBA — Run Framework","",
               "**Research only:** historical rates are not calibrated prediction probabilities.",""]
        for prop in data["results"]:
            lines.extend([f"## 📊 {prop['player']} — {prop['market']} {prop['line']}",
                f"**Historical directional lean:** {prop['side'] or 'INSUFFICIENT DATA'}","",
                "| Window | OVER | UNDER | PUSH | Sample |",
                "|---|---:|---:|---:|---:|"])
            for name,window in prop["windows"].items():
                lines.append(f"| {name} | {window['over']} | {window['under']} | {window['push']} | {window['n']} |")
            lines+=["","**🔄 Alternative-line sensitivity (historical counts):**","",
                "| Line | OVER | UNDER | PUSH |","|---|---:|---:|---:|"]
            for item in prop["sensitivity"]:
                lines.append(f"| {item['line']} | {item['over']} | {item['under']} | {item['push']} |")
            lines+=["","**⚠️ Risk / missing context:** "+(", ".join(prop["risks"]) or "No listed gaps"),
                "**🧪 25K sequential simulations:** NOT EXECUTED",
                "**🧠 Independent Blind AI:** NOT EXECUTED",""]
        (root/"report.md").write_text("\n".join(lines)+"\n")
        receipt["props"]=len(data["results"])
    (root/"execution_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(result.stdout)
    if result.returncode: print(result.stderr,file=sys.stderr)
    return result.returncode

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--config")
    parser.add_argument("--omni",help="Execute the isolated multi-sport manifest")
    parser.add_argument("--auto",help="Acquire and reconcile real player histories, run v5.2 and freeze a forward slate")
    parser.add_argument("--state-dir",default="omni_state")
    parser.add_argument("--trials",type=int,default=25000)
    parser.add_argument("--seed",type=int,default=1729)
    parser.add_argument("--stress-trials",type=int,default=2000)
    parser.add_argument("--output",required=True)
    raise SystemExit(execute(parser.parse_args()))
