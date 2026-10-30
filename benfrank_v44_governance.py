"""Authoritative BENFRANK NBA v4.4 66-stage governing checklist.

Unlike low-level technical signals, these 66 stages match the published v4.4
master. Partial computation never implies that a whole governing stage passed.
"""
import datetime as dt
import hashlib
import json

STAGES = [
  "Capture all uploaded props without an artificial maximum; assign isolated IDs.",
  "Extract full name, team, market, platform, exact line, game and cutoff time.",
  "Resolve screenshot ambiguity; never infer unreadable lines.",
  "Check duplicates, correlated markets and changed lines; create new snapshots.",
  "Verify NBA game ID, venue, date, opponent and current player team.",
  "Verify stat definition, platform scoring, overtime and push/void rules.",
  "Freeze evidence as-of timestamp and source provenance.",
  "Check official availability, injury designation and late scratches.",
  "Verify starters, probable rotation and coach quotes with timestamps.",
  "Check line movement and preserve immutable earlier lines.",
  "Import and reconcile official player-game logs and missingness.",
  "Calculate L5/L10/L15/L20/L25/L32/L52, season and career windows.",
  "Compute exact-line and adjacent-line hit rates with denominators.",
  "Adjust for sample size, opponent strength and role changes.",
  "Measure per-minute and per-possession opportunities and efficiency.",
  "Separate starter/bench, home/away, rest and travel splits.",
  "Model teammate-on/off and lineup combinations with sample shrinkage.",
  "Translate rookies from college/G League only with uncertainty.",
  "Check recent minutes, restrictions, conditioning and foul tendencies.",
  "Assess coach substitution, closing lineup and overtime eligibility.",
  "Estimate team possessions, pace, game total and spread without equating total to opportunities.",
  "Inspect opponent defensive efficiency by possession and lineup.",
  "Evaluate primary/secondary defender assignments and switching schemes.",
  "Analyze rim deterrence, paint, midrange, perimeter and shot quality.",
  "Estimate opponent FGA/3PA/FTA and missed-shot opportunities.",
  "Measure offensive/defensive rebound chance distribution and box-out competition.",
  "Evaluate potential assists allowed, passes, pressure and turnover creation.",
  "Check opponent foul rates, free-throw opportunities and foul-drawing matchup.",
  "Account for opponent injuries, bench units, and expected replacement defenders.",
  "Analyze game script, competitive minutes, blowout and overtime tails.",
  "Conserve team minutes, possessions and usage shares across teammates.",
  "Points: model FGA by zone, 3PA, FTA, expected efficiency and scoring distribution.",
  "Assists: model touches, passes, potential assists and teammate conversion.",
  "Rebounds: model missed shots, contested chances, positioning and rebound share.",
  "Threes: model 3PA attempts, quality, defensive contests and make variance.",
  "Steals/blocks: model defensive events, role, opponent ball security and fouls.",
  "Turnovers: model touches, passes, pressure and live-ball/dead-ball events.",
  "PRA and combos: model correlated components without independence shortcuts.",
  "Fantasy score: implement exact platform weights and negative events.",
  "For every other registered market, require a validated opportunity-to-stat adapter.",
  "Build full predictive distribution, not just a point estimate.",
  "Estimate variance and tail behavior with sample-aware uncertainty.",
  "Evaluate OVER, UNDER and push/void probability at the exact line.",
  "Compare historical exact-line route and adjacent lines without cherry-picking.",
  "Apply small-sample shrinkage and shooting/rebound/assist regression.",
  "Check independent public projections and explain disagreement where available.",
  "Test minutes floor, median, ceiling and substitution paths.",
  "Test opponent scheme, teammate return, foul trouble, poor efficiency and low pace.",
  "Test high-usage, hot shooting, overtime and extended-minute threats to UNDER.",
  "Run P25 opportunity and P25 conversion downside tests.",
  "Run opposite-side HELL prosecution and identify strongest kill shot.",
  "Measure edge robustness; fragile margins cannot earn high certification.",
  "Run at least 25,000 actual sequential 5-on-5 Digital Twon trials per exact line for simulation certification.",
  "Verify trial counts, seeds, hashes, convergence and 240-minute regulation conservation.",
  "Run independent Blind AI isolated from primary final direction.",
  "Reconcile primary, Blind AI, historical and stress-model disagreements.",
  "Perform leak-free walk-forward calibration by market and line band.",
  "Test calibration, coverage, Brier/log loss and selection bias on held-out games.",
  "Run integrity checks for stale feeds, conflicting sources and missing data.",
  "Recheck official availability and line at the final pregame cutoff.",
  "Issue mandatory MORE/LESS directional verdict with provisional flag when evidence insufficient.",
  "Issue separate ticket eligibility; NO TICKET if required gates fail.",
  "Record per-stage PASS/FAIL/BLOCKED/NOT APPLICABLE with reason, source and fix.",
  "Freeze final evidence receipt, prediction, uncertainty, and timestamp.",
  "After game, reconcile official settlement and diagnose failure without rewriting picks.",
  "Promote new thresholds only after out-of-sample champion/challenger evaluation."
]
GROUPS = ((1,10,"intake_and_truth"),(11,20,"player_DNA"),(21,30,"opponent_DNA"),
          (31,40,"market_opportunities"),(41,52,"probability_and_challenge"),
          (53,66,"execution_and_release"))

def group_for(index):
    return next(g for start,end,g in GROUPS if start <= index <= end)

def governing_receipt(prop, technical_checks, direction, ticket_authority):
    checks = {item["id"]: item for item in technical_checks}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    stages = []
    for n, desc in enumerate(STAGES, 1):
        sid=f"G{n:02d}"
        item={"id":sid,"number":n,"group":group_for(n),"requirement":desc,
              "status":"BLOCKED","source":None,"asof":None,
              "reason":"Full governing requirement is not yet substantiated",
              "next_fix":"Attach source-backed, timestamped execution evidence for this complete requirement"}
        # Only prove a full governing stage when its ENTIRE described behavior is verified.
        if n==61 and direction in ("MORE","LESS"):
            item.update(status="PASS",source="benfrank_v44_batch.py provisional direction rule",
                        asof=now,reason="Direction issued as PROVISIONAL_NO_TICKET; not predictive certification",
                        next_fix=None)
        elif n==62 and ticket_authority=="NO_TICKET":
            item.update(status="PASS",source="benfrank_v44_batch.py fail-closed ticket rule",
                        asof=now,reason="Ticket eligibility separated and set to NO_TICKET when certification absent",
                        next_fix=None)
        elif n==63:
            item.update(status="PASS",source="benfrank_v44_governance.py enumerated status schema",
                        asof=now,reason="All 66 requirements appear with explicit status and next fix",
                        next_fix=None)
        stages.append(item)
    out={"framework":"BENFRANK NBA v4.4 governing 66-stage contract",
         "prop":{"player":prop["player"],"market":prop["market"],"line":prop["line"],
                 "opponent":prop["opponent"],"game_date":prop["game_date"]},
         "stages":stages,
         "counts":{"PASS":sum(x["status"]=="PASS" for x in stages),
                   "BLOCKED":sum(x["status"]=="BLOCKED" for x in stages),
                   "FAIL":sum(x["status"]=="FAIL" for x in stages),
                   "NOT_APPLICABLE":sum(x["status"]=="NOT_APPLICABLE" for x in stages)},
         "certification":"NOT_CERTIFIED", "ticket_authority":"NO_TICKET"}
    out["receipt_sha256"]=hashlib.sha256(json.dumps(out,sort_keys=True).encode()).hexdigest()
    return out
