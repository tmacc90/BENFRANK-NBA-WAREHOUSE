"""Additive BENFRANK 60-question interrogation and receipt integrity layer.

This module does not claim that upstream checks ran. Call evaluate() only with
actual stage results and source-backed answers; missing answers stay pending.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Mapping, Any
import json

QUESTIONS = [["proof","What verified results support OVER and UNDER?"],["facts","What verified player facts apply?"],["findings","What did historical logs reveal?"],["support","Which statistics support each side?"],["verification","Are identity market line opponent and date verified?"],["confirmation","Do independent sources agree?"],["documentation","Can statistics be traced to records?"],["validation","Were calculations reproduced?"],["indicators","What indicators favor each side?"],["observations","Which patterns recur?"],["records","What are exact-line over under push counts?"],["testimony","What credible team reports affect role?"],["substantiation","Are claims measurement-backed?"],["corroboration","Do independent sources agree?"],["data","Is coverage complete and recent?"],["predictive_signals","Which signals forecast either side?"],["statistical_indicators","What do distribution and percentiles show?"],["analytical_findings","How do windows compare?"],["historical_intelligence","What happened under comparable conditions?"],["data_insights","What do averages conceal?"],["probability_indicators","What are estimated side probabilities?"],["predictive_intelligence","What does the pregame model forecast?"],["model_validation","Was model tested out of sample?"],["quantitative_support","How large is the edge?"],["statistical_confirmation","Could the pattern be noise?"],["pattern_recognition","Which past games are genuinely comparable?"],["performance_indicators","How are minutes usage and efficiency changing?"],["confidence_signals","Which independent signals agree?"],["decision_intelligence","Which side wins after conflicts?"],["empirical_findings","Do held-out tests support accuracy?"],["signal_intelligence","Are signals predictive or correlated?"],["historical_verification","Was exact-line performance verified?"],["statistical_validation","Are results robust to assumptions?"],["predictive_indicators","Which indicators historically work?"],["decision_synthesis","What remains after conflicting evidence?"],["probability_confirmation","Do independent estimates agree?"],["adversarial_verification","What is the strongest opposing case?"],["outcome_intelligence","Which minutes opportunities conversion are required?"],["confidence_assessment","How uncertain is the forecast?"],["analytical_corroboration","Do independent analytical layers converge?"],["exact_line","What exact line is frozen?"],["cutoff","What was known before game start?"],["windows","What are L5 L10 L15 L20 L25 L32 L52 covers?"],["push_counts","What are over under push counts by window?"],["baselines","Do recent windows match season and career?"],["player_dna","Which player conditions explain covers and misses?"],["workload","What minutes and opportunities are projected?"],["availability","How do injuries and rotations alter opportunities?"],["opponent_dna","How does opponent defense affect production?"],["similar_matchups","How did comparable matchups perform?"],["game_script","How do pace blowouts and fouls affect outcome?"],["simulation","What do genuine 25000 trials estimate?"],["blind_ai","What does independently validated line-blind AI predict?"],["adversarial","Does the opposing case outperform?"],["sensitivity","Does decision survive +0.5 and +1.0?"],["flip_point","At what line does preferred side flip?"],["pro_reasons","What are three strongest reasons for selection?"],["contra_reasons","What are three strongest failure reasons?"],["calibration","Are probabilities calibrated on pregame predictions?"],["final_decision","Which side has higher estimated cover probability?"]]

VALID_STATUSES = {"verified", "failed", "unavailable", "pending"}

@dataclass(frozen=True)
class Answer:
    question_id: int
    key: str
    question: str
    status: str
    answer: str
    source: str
    measurement: str
    over_impact: str
    under_impact: str
    execution_receipt: str

def evaluate(stage_answers: Mapping[str, Mapping[str, Any]], *,
             sport: str, player: str, market: str, line: float,
             cutoff_utc: str, preferred_side: str | None = None) -> dict:
    """Produce an auditable report without fabricating verification."""
    if preferred_side not in (None, "OVER", "UNDER"):
        raise ValueError("preferred_side must be OVER, UNDER, or None")
    rows = []
    for i, (key, question) in enumerate(QUESTIONS, 1):
        raw = dict(stage_answers.get(key) or {})
        status = raw.get("status", "pending")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status for {key}: {status}")
        fields = ("answer", "source", "measurement", "execution_receipt")
        if status == "verified" and not all(str(raw.get(f, "")).strip() for f in fields):
            status = "pending"
        rows.append(asdict(Answer(
            i, key, question, status,
            str(raw.get("answer", "")), str(raw.get("source", "")),
            str(raw.get("measurement", "")),
            str(raw.get("over_impact", "")),
            str(raw.get("under_impact", "")),
            str(raw.get("execution_receipt", "")))))
    verified = sum(r["status"] == "verified" for r in rows)
    critical = ("exact_line", "cutoff", "windows", "simulation", "blind_ai",
                "adversarial", "calibration", "final_decision")
    by_key = {r["key"]: r for r in rows}
    certified = all(by_key[k]["status"] == "verified" for k in critical)
    return {
        "schema": "benfrank.interrogation.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sport": sport, "player": player, "market": market, "line": line,
        "cutoff_utc": cutoff_utc, "preferred_side": preferred_side,
        "certified": certified, "verified_count": verified,
        "total_questions": len(rows), "questions": rows,
        "warning": None if certified else "NOT CERTIFIED: critical checks missing or unverified",
    }

def write_report(path: str, report: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
