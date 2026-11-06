"""Pregame schedule/role captures and observed opponent allowance summaries."""
import statistics

from .contracts import CONTEXT_KEYS, key, stat_value, timestamp
from .sources import ESPN, espn_route, espn_stats, normalized_document


def collect(prop, capture, cutoff, mode):
    context = {"schedule_verified": False, "opponent": {}, "availability": {}, "gaps": []}
    if prop["sport"] not in ESPN:
        if mode == "PREGAME" and prop.get("event_source"):
            document, receipt = normalized_document(prop["event_source"], capture)
            event = document["event"]
            if any(str(event.get(k)) != str(prop[k]) for k in ("sport", "player_id", "opponent", "event_id")) or key(event.get("player")) != key(prop["player"]):
                raise ValueError("SPECIALIST_EVENT_IDENTITY_MISMATCH")
            if event.get("status") != "SCHEDULED" or timestamp(event["start_utc"]) != timestamp(prop["event_start_utc"]):
                raise ValueError("SPECIALIST_EVENT_NOT_SCHEDULED_AT_REQUESTED_TIME")
            if event.get("scope") != prop["scope"] or any(event.get("rules", {}).get(k) != prop["rules"][k] for k in CONTEXT_KEYS.get(prop["sport"], [])):
                raise ValueError("SPECIALIST_EVENT_SCOPE_OR_RULES_MISMATCH")
            context.update(schedule_verified=True, schedule_source=receipt)
            context["gaps"].append("SPECIALIST_EVENT_SOURCE_ATTESTED_NOT_INDEPENDENTLY_CONFIRMED")
        else:
            context["gaps"].append("SPECIALIST_EVENT_ROLE_AND_OPPONENT_CONTEXT_REQUIRES_SOURCE")
        return context
    discipline, league = espn_route(prop)
    base = f"https://site.api.espn.com/apis/site/v2/sports/{discipline}/{league}/"
    if mode == "PREGAME":
        if not prop.get("team_id"):
            raise ValueError("ESPN_PREGAME_TEAM_ID_REQUIRED")
        data, receipt = capture.get(base + "summary?event=" + str(prop["event_id"]))
        competition = data["header"]["competitions"][0]
        ids = {str(c["team"]["id"]) for c in competition["competitors"]}
        if ids != {str(prop["team_id"]), str(prop["opponent"])} or len(ids) != 2:
            raise ValueError("SOURCE_EVENT_TEAM_OR_OPPONENT_MISMATCH")
        if abs((timestamp(competition["date"]) - timestamp(prop["event_start_utc"])).total_seconds()) > 60:
            raise ValueError("SOURCE_EVENT_START_MISMATCH")
        status = competition["status"]["type"]
        if status.get("state") != "pre" or any(x in status.get("name", "").upper() for x in ("POSTPONE", "CANCEL", "SUSPEND")):
            raise ValueError("SOURCE_EVENT_NOT_SCHEDULED_PREGAME")
        context.update(schedule_verified=True, schedule_source=receipt)
        try:
            roster, receipt = capture.get(base + "teams/" + str(prop["team_id"]) + "/roster")
            athletes = roster.get("athletes", [])
            flat = []
            for item in athletes:
                flat.extend(item.get("items", [item]))
            candidates = [a for a in flat if str(a.get("id")) == str(prop["player_id"])]
            if len(candidates) != 1 or key(candidates[0].get("displayName")) != key(prop["player"]):
                raise ValueError("CURRENT_TEAM_ROSTER_IDENTITY_MISMATCH")
            context["availability"] = {"roster_member": True, "injuries": candidates[0].get("injuries", []), "source": receipt, "confirmed_active": False}
        except (ValueError, KeyError, TypeError) as exc:
            context["gaps"].append("CURRENT_ROSTER_OR_INJURY:" + str(exc))
        if prop["sport"] in ("NBA", "WNBA", "NCAAB", "NFL", "CFB"):
            try:
                _, receipt = capture.get(base + "teams/" + str(prop["team_id"]) + "/depthcharts")
                context["projected_role_source"] = receipt
            except (ValueError, KeyError, TypeError) as exc:
                context["gaps"].append("PROJECTED_DEPTH_CHART:" + str(exc))
        context["gaps"].append("AVAILABILITY_AND_MINUTE_RESTRICTIONS_NOT_INDEPENDENTLY_CONFIRMED")
    else:
        context["gaps"].append("REPLAY_DOES_NOT_RECONSTRUCT_HISTORICAL_PREGAME_AVAILABILITY")
    # Team-defense evidence from completed individual games, never future season aggregates.
    try:
        if mode == "PREGAME":
            profile, _ = capture.get(f"https://site.web.api.espn.com/apis/common/v3/sports/{discipline}/{league}/athletes/{prop['player_id']}")
            year = prop.get("opponent_season", profile.get("season", {}).get("year"))
            if type(year) is not int:
                raise ValueError("OPPONENT_SOURCE_SEASON_UNAVAILABLE")
        else:
            year = prop.get("opponent_season")
            if year is None:
                raise ValueError("REPLAY_OPPONENT_SEASON_MUST_BE_EXPLICIT")
        schedule, _ = capture.get(base + "teams/" + str(prop["opponent"]) + "/schedule?season=" + str(year))
        events = [e for e in schedule.get("events", []) if timestamp(e["date"]) < timestamp(cutoff) and e.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed")]
        events.sort(key=lambda e: timestamp(e["date"]))
        evidence = []
        for event in events[-3:]:
            data, receipt = capture.get(base + "summary?event=" + str(event["id"]))
            other = [t for t in data.get("boxscore", {}).get("players", []) if str(t["team"]["id"]) != str(prop["opponent"])]
            if len(other) != 1:
                continue
            observed = []
            for group in other[0].get("statistics", []):
                for athlete in group.get("athletes", []):
                    if athlete.get("didNotPlay"):
                        continue
                    stats = espn_stats(group.get("keys", []), athlete.get("stats", []), prop["sport"], prop["rules"].get("role", "hitter"))
                    try:
                        observed.append(stat_value({"stats": stats}, prop))
                    except (KeyError, ValueError):
                        pass
            if observed:
                evidence.append({"event_id": event["id"], "start_utc": event["date"], "opposing_player_n": len(observed), "sum_observed_opponent_stat": sum(observed), "source": receipt})
        if evidence:
            context["opponent"] = {"games": evidence, "mean_observed_team_total_allowed": statistics.mean(e["sum_observed_opponent_stat"] for e in evidence), "model_multiplier_applied": False, "interpretation": "Observed opposing player totals; no positional defense, league rank, or causal adjustment inferred"}
        else:
            context["gaps"].append("NO_COMPARABLE_OPPONENT_BOX_SCORE_EVIDENCE")
    except (ValueError, KeyError, TypeError) as exc:
        context["gaps"].append("OPPONENT_BOX_SCORES:" + str(exc))
    context["gaps"].append("DEFENSIVE_SCHEME_TRACKING_AND_LEAGUE_RANK_NOT_VERIFIED")
    return context
