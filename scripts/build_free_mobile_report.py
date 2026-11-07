"""Turn an authentic BENFRANK execution_receipt.json into an offline mobile HTML report.

No source data, trial evidence, certification or forecasts are manufactured here.
"""
import argparse
import html
import json
from pathlib import Path

STYLE = """body{background:#0b1220;color:#eef2fb;font:16px system-ui,-apple-system,sans-serif;margin:0}
main{max-width:780px;margin:auto;padding:20px 14px 48px}header,.card{background:#192339;border:1px solid #324059;border-radius:14px;padding:16px;margin:12px 0}
h1{font-size:25px}h2{font-size:19px}h3{font-size:16px}p{line-height:1.45}small,.muted{color:#b0c3df}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:8px 5px;vertical-align:top;border-bottom:1px solid #344158;overflow-wrap:anywhere}
b{font-weight:750}.meta{font-size:13px}.warn{color:#ffc17b}.ok{color:#97e2bf}.tag{font-weight:700}
details{margin:8px 0}summary{cursor:pointer;padding:8px 0}code{overflow-wrap:anywhere;color:#d8e8fc}"""

def e(value):
    return html.escape(str(value) if value is not None else "—", quote=True)

def build(receipt):
    status=receipt.get("status","UNKNOWN")
    all_done=receipt.get("all_requested_props_executed") is True
    preserved=receipt.get("preservation_verified") is True
    parts=["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           "<meta name='color-scheme' content='dark'><title>BENFRANK free run report</title>",
           "<style>"+STYLE+"</style></head><body><main>",
           "<header><h1>🏀 BENFRANK — Free Run Framework</h1>",
           "<p><span class='tag'>Pipeline status:</span> "+e(status)+"</p>",
           "<p><b>Completed all requested props:</b> "+e(all_done)+" · <b>Protected files preserved:</b> "+e(preserved)+"</p>",
           "<p class='warn'><b>Research only:</b> An OVER/UNDER side is not evidence of accuracy certification or a guaranteed result.</p>",
           "<p class='meta muted'>Run date: "+e(receipt.get("game_date"))+
             " · Started: "+e(receipt.get("started_utc"))+
             " · Completed: "+e(receipt.get("completed_utc"))+"</p></header>"]
    if receipt.get("fatal_blocker"):
        parts.append("<section class='card'><h2>⚠️ Fatal blocker</h2><p>"+e(receipt["fatal_blocker"])+"</p></section>")
    props=receipt.get("props",[])
    if not props:
        parts.append("<section class='card'><h2>No verified props</h2><p>The run did not produce per-prop execution receipts. Check the fatal blocker and workflow logs.</p></section>")
    for item in props:
        prop=item.get("prop") or {}
        side=item.get("direction")
        if side not in ("OVER","UNDER"): side="NO VERIFIED SIDE"
        stages=item.get("stage_results") or {}
        parts.append("<section class='card'><h2>"+e(prop.get("player"))+"</h2><p><b>"+e(prop.get("market"))+" "+e(prop.get("line"))+
                     "</b> · "+e(prop.get("opponent"))+"</p><p><strong>"+e(side)+"</strong> · "+e(item.get("status"))+"</p>")
        if item.get("exact_blocker"):
            parts.append("<p class='warn'><b>Blocker:</b> "+e(item["exact_blocker"])+"</p>")
        parts.append("<details><summary>View "+e(len(stages))+" execution stages</summary><table><thead><tr><th>Stage</th><th>State</th><th>Evidence / reason</th></tr></thead><tbody>")
        for name, detail in stages.items():
            parts.append("<tr><td>"+e(name)+"</td><td>"+e(detail.get("status"))+
                         "</td><td>"+e(detail.get("exact_reason") or detail.get("receipt") or "")+"</td></tr>")
        parts.append("</tbody></table></details></section>")
    parts.append("<section class='card'><h2>📋 Evidence rules</h2><p>Every result must be judged from the underlying receipt, source timestamps, trial provenance and postgame grading. A successful software workflow or a directional lean does not certify betting accuracy.</p></section></main></body></html>")
    return "".join(parts)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    receipt=json.loads(Path(args.input).read_text(encoding="utf8"))
    path=Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(build(receipt),encoding="utf8")

if __name__=="__main__":
    main()
