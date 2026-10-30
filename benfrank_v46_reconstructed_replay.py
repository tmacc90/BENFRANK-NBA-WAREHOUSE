"""Real-data research replay using only games at least two days before target.

The forecast is constructed NOW from prior history. It is not an archived live
pregame forecast. Injuries/coach news are unknown; no FULL certification follows.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

from acquire_history import team_key
from benfrank_v44_twon import trial_run, validate
from benfrank_v45_evidence import archive_minutes, digest, readonly, write_json


def allocate_minutes(weights):
    if (not 7 <= len(weights) <= 15 or any(isinstance(v, bool) or not math.isfinite(v) or v < 0
                                        for v in weights.values()) or sum(weights.values()) <= 0):
        raise ValueError("INVALID_FORECAST_ROTATION_WEIGHTS")
    targets = {name: 0 for name in weights}
    # Deterministic proportional apportionment, with the legal 48-minute cap.
    for _ in range(240):
        possible = [n for n in weights if targets[n] < 48 and weights[n] > 0]
        if not possible:
            raise ValueError("NO_FEASIBLE_240_MINUTE_FORECAST")
        name = max(possible, key=lambda n: (weights[n] / (targets[n] + .5), n))
        targets[name] += 1
    return targets


def build_context(warehouse, shooting_database, snapshot):
    through = (dt.date.fromisoformat(snapshot["game_date"]) - dt.timedelta(days=2)).isoformat()
    cutoff = through + "T23:59:59+00:00"
    conn, shots = readonly(warehouse), readonly(shooting_database)
    max_feature_date = ""
    rosters, team_rates, paces, histories = {}, {}, [], {}
    try:
        target = conn.execute("SELECT home FROM games WHERE player=? AND date=? AND team=? AND opponent=?",
            (snapshot["player"], snapshot["game_date"], snapshot["team"], snapshot["opponent"])).fetchall()
        # Target result is used ONLY to identify schedule orientation, never player stats.
        if len(target) != 1:
            raise ValueError("TARGET_GAME_IDENTITY_REQUIRED")
        home, away = ((snapshot["team"], snapshot["opponent"]) if target[0][0] else
                      (snapshot["opponent"], snapshot["team"]))
        provenance = "RECONSTRUCTED_PRIOR_HISTORY_NOT_AN_ARCHIVED_FORECAST"
        selected_ids = set()
        for team in (home, away):
            dates = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM games WHERE team=? AND date<=? ORDER BY date DESC LIMIT 5", (team, through))]
            if len(dates) != 5:
                raise ValueError("FIVE_PRIOR_TEAM_GAMES_REQUIRED")
            placeholders = ",".join("?" for _ in dates)
            recent = [dict(r) for r in conn.execute(
                "SELECT * FROM games WHERE team=? AND date IN (" + placeholders + ")", (team, *dates))]
            weights = collections.Counter()
            for r in recent:
                weights[r["player"]] += r["minutes"] / len(dates)
            weights = dict(sorted(weights.items(), key=lambda x: (-x[1], x[0]))[:10])
            targets = allocate_minutes(weights)
            profiles = []
            for player in sorted(weights):
                prior = [dict(r) for r in conn.execute(
                    "SELECT * FROM games WHERE player=? AND date<=? ORDER BY date DESC LIMIT 32", (player, through))]
                paired = []
                for r in prior:
                    options = shots.execute("SELECT * FROM verified_shooting WHERE player=? AND game_date=? AND team=?",
                                            (player, r["date"], r["team"])).fetchall()
                    if len(options) == 1 and r["minutes"] > 0:
                        paired.append((r, dict(options[0])))
                if len(paired) < 12:
                    raise ValueError("INSUFFICIENT_CROSSCHECKED_PRIOR_SHOTS: " + player)
                total_minutes = sum(r["minutes"] for r, _ in paired)
                max_feature_date = max(max_feature_date, max(r["date"] for r, _ in paired))
                totals = {k: sum(s[k] for _, s in paired) for k in ("fg2m", "fg2a", "fg3m", "fg3a", "ftm", "fta")}
                profiles.append({"player": player, "minutes_target": targets[player], "source": provenance,
                    "asof": cutoff, "fg2a_per36": totals["fg2a"] * 36 / total_minutes,
                    "fg3a_per36": totals["fg3a"] * 36 / total_minutes,
                    "fta_per36": totals["fta"] * 36 / total_minutes,
                    "fg2_pct": (totals["fg2m"] + 1) / (totals["fg2a"] + 2),
                    "fg3_pct": (totals["fg3m"] + 1) / (totals["fg3a"] + 2),
                    "ft_pct": (totals["ftm"] + 1) / (totals["fta"] + 2),
                    **{out: sum(r[key] for r, _ in paired) * 36 / total_minutes for out, key in
                       (("ast_per36", "ast"), ("reb_per36", "reb"), ("stl_per36", "stl"),
                        ("blk_per36", "blk"), ("tov_per36", "tov"))}})
            rosters[team] = profiles
            histories[team] = dates
            selected_ids.update(r[0] for r in conn.execute(
                "SELECT DISTINCT nba_game_id FROM verified_history WHERE team=? AND date IN (" + placeholders + ")",
                (team, *dates)))
        totals = collections.defaultdict(collections.Counter)
        fields = ("field_goals_made", "field_goals_attempted", "free_throws_attempted", "rebounds_offensive",
                  "rebounds_defensive", "turnovers", "assists", "blocks")
        placeholders = ",".join("?" for _ in selected_ids)
        for row in conn.execute("SELECT payload_json FROM source_records WHERE file_sha256 IN "
            "(SELECT sha256 FROM source_files WHERE name LIKE 'player_boxscores_%.parquet') "
            "AND json_extract(payload_json,'$.game_id') IN (" + placeholders + ")", tuple(selected_ids)):
            r = json.loads(row[0])
            if not r.get("minutes"):
                continue
            minutes = archive_minutes(r["minutes"])
            if not minutes:
                continue
            key = str(r["game_id"]), team_key(r["team_tricode"])
            totals[key]["minutes"] += minutes
            for k in fields:
                value = r[k]
                if value is None or value < 0:
                    raise ValueError("MISSING_PRIOR_TEAM_STAT")
                totals[key][k] += value
        for team in (home, away):
            games = [dict(r) for r in conn.execute(
                "SELECT DISTINCT v.nba_game_id,g.opponent FROM games g JOIN verified_history v USING(player,date,team) "
                "WHERE g.team=? AND g.date IN (" + ",".join("?" for _ in histories[team]) + ")", (team, *histories[team]))]
            aggregate, opposite = collections.Counter(), collections.Counter()
            team_paces = []
            for game in games:
                own, other = totals[(game["nba_game_id"], team)], totals[(game["nba_game_id"], game["opponent"])]
                if own["minutes"] < 235 or other["minutes"] < 235:
                    raise ValueError("INCOMPLETE_PRIOR_TEAM_BOX_SCORE")
                aggregate.update(own)
                opposite.update(other)
                for t in (own, other):
                    p = t["field_goals_attempted"] + .44 * t["free_throws_attempted"] - t["rebounds_offensive"] + t["turnovers"]
                    team_paces.append(p * 240 / t["minutes"])
            paces.append(statistics.mean(team_paces))
            poss = aggregate["field_goals_attempted"] + .44 * aggregate["free_throws_attempted"] - aggregate["rebounds_offensive"] + aggregate["turnovers"]
            rates = {"off_reb_probability": aggregate["rebounds_offensive"] / (aggregate["rebounds_offensive"] + opposite["rebounds_defensive"]),
                     "assist_probability": aggregate["assists"] / aggregate["field_goals_made"],
                     "block_on_missed_fg_probability": aggregate["blocks"] / (opposite["field_goals_attempted"] - opposite["field_goals_made"]),
                     "shooting_foul_probability": aggregate["free_throws_attempted"] / (2 * poss)}
            team_rates[team] = {**rates, "source": provenance, "asof": cutoff}
        context = {"game_id": snapshot["game_id"], "game_date": snapshot["game_date"],
            "tipoff_utc": snapshot["tipoff_utc"], "home": home, "away": away,
            "pace_per_team": statistics.mean(paces), "pace_source": "PRIOR_BOX_SCORE_POSSESSION_ESTIMATOR_NOT_PBP",
            "pace_asof": cutoff, "rosters": rosters, "team_rates": team_rates,
            "input_mode": "RETROSPECTIVE_PRIOR_HISTORY_RECONSTRUCTION", "history_through_date": through,
            "max_feature_game_date": max_feature_date,
            "constructed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "warehouse_sha256": digest(warehouse), "shooting_database_sha256": digest(shooting_database),
            "context_builder_sha256": digest(__file__), "prior_team_dates": histories,
            "historical_availability_verified": False,
            "limitations": ["No archived pregame injuries, coach or roster forecast evidence",
                            "Top-ten rotation and minute allocation are unvalidated prior-history forecasts",
                            "Possessions and shooting foul rate are box-score estimators",
                            "Historical stat corrections may not reflect first published values"],
            "certification": "NOT_CERTIFIED", "ticket_authority": "NO_TICKET"}
        validate(context)
        return context
    finally:
        conn.close()
        shots.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--shooting-database", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--player", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--trials", type=int, default=25000)
    args = parser.parse_args()
    ledger = readonly(args.ledger)
    try:
        row = ledger.execute("SELECT payload_json FROM exact_line_snapshots WHERE player=? AND market='points' "
                             "ORDER BY game_date,captured_at,snapshot_id LIMIT 1", (args.player,)).fetchone()
        if row is None:
            raise ValueError("NO_ACTUAL_POINTS_SNAPSHOT_FOR_PLAYER")
        snapshot = json.loads(row[0])
    finally:
        ledger.close()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    context = build_context(args.warehouse, args.shooting_database, snapshot)
    write_json(out / "context.json", context)
    write_json(out / "snapshot.json", snapshot)
    result = trial_run(context, snapshot["player"], snapshot["market"], snapshot["line"], args.trials, seed=20261030)
    result.update(input_mode=context["input_mode"], prediction_origin="RETROSPECTIVE_RESEARCH_NOT_A_LIVE_PREGAME_PICK",
                  snapshot_id=snapshot["snapshot_id"], source_tier=snapshot["source_tier"],
                  constructed_at=context["constructed_at"], limitations=context["limitations"],
                  selection_policy="FIRST_ARCHIVED_POINTS_CAPTURE_FOR_REQUESTED_PLAYER_NO_OUTCOME_FILTER")
    write_json(out / "simulation.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
