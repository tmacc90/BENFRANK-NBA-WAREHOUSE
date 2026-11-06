"""Strict inputs, time boundaries, market rules, and source identities."""
import datetime as dt
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "architecture/benfrank_multisport_catalog.json"
SPORTS = {s["id"]: s for s in json.loads(CATALOG.read_text())["sports"]}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def timestamp(value):
    value = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value.astimezone(dt.timezone.utc)


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else canonical(data)).hexdigest()


def key(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower())


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return float(value)


COMPOSITES = {
    "pra": {"points": 1, "rebounds": 1, "assists": 1},
    "points_rebounds": {"points": 1, "rebounds": 1},
    "points_assists": {"points": 1, "assists": 1},
    "rebounds_assists": {"rebounds": 1, "assists": 1},
    "hrrbi": {"hits": 1, "runs": 1, "rbis": 1},
    "hits_walks_allowed": {"hits_allowed": 1, "walks_allowed": 1},
}

EXTRA_MARKETS = {
    "NBA": ["pra", "points_rebounds", "points_assists", "rebounds_assists", "steals", "blocks", "turnovers"],
    "WNBA": ["points_rebounds", "points_assists", "rebounds_assists", "steals", "blocks", "turnovers"],
    "NCAAB": ["pra", "points_rebounds", "points_assists", "rebounds_assists", "steals", "blocks", "turnovers"],
    "NFL": ["receiving_yards", "targets", "passing_touchdowns", "passing_attempts", "completions", "rushing_attempts", "receiving_touchdowns", "rushing_touchdowns"],
    "CFB": ["receptions", "targets", "passing_touchdowns", "passing_attempts", "completions", "rushing_attempts"],
    "MLB": ["earned_runs", "hits_allowed", "walks_allowed", "pitches", "runs_allowed", "hits_walks_allowed", "runs", "rbis", "singles", "doubles", "triples", "home_runs", "batter_strikeouts", "batter_walks", "stolen_bases"],
}

# These fields define comparable units, rather than merely providing commentary.
CONTEXT_KEYS = {
    "TENNIS": ["surface", "best_of"], "SOCCER": ["competition", "extra_time"],
    "COD": ["title", "patch", "series_format", "mode"],
    "CS2": ["title", "patch", "series_format"],
    "LOL": ["patch", "series_format"], "DOTA2": ["patch", "series_format"],
    "VALORANT": ["patch", "series_format"],
    "MMA": ["weight_class", "scheduled_rounds"], "BOXING": ["scheduled_rounds"],
    "TABLETENNIS": ["best_of"], "GOLF": ["round", "course"], "F1": ["session"],
}


def validate_prop(raw, cutoff, mode):
    p = dict(raw)
    required = ["sport", "player", "player_id", "market", "line", "opponent", "event_id", "event_start_utc", "captured_at_utc", "line_source", "scope", "rules"]
    missing = [k for k in required if k not in p or p[k] in (None, "")]
    if missing:
        raise ValueError("MISSING_PROP_FIELDS:" + ",".join(missing))
    if p["sport"] not in SPORTS:
        raise ValueError("UNKNOWN_SPORT_NO_FALLBACK")
    allowed = SPORTS[p["sport"]]["markets"] + EXTRA_MARKETS.get(p["sport"], [])
    if p["market"] not in allowed:
        raise ValueError("UNSUPPORTED_SPORT_MARKET")
    p["line"] = number(p["line"])
    if timestamp(p["event_start_utc"]) <= timestamp(cutoff):
        raise ValueError("EVENT_MUST_START_AFTER_FORECAST_CUTOFF")
    age = (timestamp(cutoff) - timestamp(p["captured_at_utc"])).total_seconds()
    if age < 0 or age > 24 * 3600:
        raise ValueError("FUTURE_OR_STALE_EXACT_LINE")
    if mode not in ("PREGAME", "RESEARCH_REPLAY", "SOFTWARE_TEST"):
        raise ValueError("INVALID_RUN_MODE")
    if mode == "PREGAME" and abs((timestamp(now()) - timestamp(cutoff)).total_seconds()) > 300:
        raise ValueError("PREGAME_CUTOFF_MUST_BE_CURRENT_USE_EXPLICIT_RESEARCH_REPLAY")
    if not isinstance(p["rules"], dict) or p["rules"].get("push") != "PUSH" or not p["rules"].get("void"):
        raise ValueError("EXPLICIT_PUSH_AND_VOID_RULES_REQUIRED")
    for k in CONTEXT_KEYS.get(p["sport"], []):
        if k not in p["rules"]:
            raise ValueError("SPORT_RULE_REQUIRED:" + k)
    if p["market"] == "fantasy_score":
        weights = p["rules"].get("scoring_weights")
        if not isinstance(weights, dict) or not weights:
            raise ValueError("EXPLICIT_PLATFORM_FANTASY_SCORING_REQUIRED")
        for v in weights.values():
            number(v)
    # Hash the frozen request, including source, rules, player ID and exact line.
    p["cutoff_utc"] = cutoff
    p["prop_id"] = sha(p)[:24]
    return p


def stat_value(game, prop):
    stats = game["stats"]
    weights = prop["rules"].get("scoring_weights") if prop["market"] == "fantasy_score" else COMPOSITES.get(prop["market"])
    if weights:
        return sum(number(stats[k]) * number(w) for k, w in weights.items())
    return number(stats[prop["market"]])


def eligible_games(games, prop, cutoff, mode):
    selected, rejected, by_id = [], [], {}
    for row in games:
        g = dict(row)
        try:
            for k in ("sport", "player_id", "player", "game_id", "start_utc", "season", "scope", "opponent", "stats", "source_sha256", "source_url", "retrieved_at_utc"):
                if k not in g:
                    raise ValueError("MISSING_GAME_FIELD:" + k)
            if g["sport"] != prop["sport"] or str(g["player_id"]) != str(prop["player_id"]) or key(g["player"]) != key(prop["player"]):
                raise ValueError("SPORT_OR_PLAYER_IDENTITY_MISMATCH")
            if not g.get("completed"):
                raise ValueError("GAME_NOT_COMPLETED")
            if not re.fullmatch(r"[a-f0-9]{64}", str(g["source_sha256"])) or not g["source_url"]:
                raise ValueError("VALID_RAW_SOURCE_HASH_AND_URL_REQUIRED")
            if g.get("completed_utc") and timestamp(g["completed_utc"]) >= timestamp(cutoff):
                raise ValueError("GAME_NOT_COMPLETED_BY_CUTOFF")
            if not g.get("completed_utc") and timestamp(g["retrieved_at_utc"]) > timestamp(cutoff) and timestamp(g["start_utc"]) + dt.timedelta(hours=18) >= timestamp(cutoff):
                raise ValueError("REPLAY_CANNOT_ESTABLISH_COMPLETION_BEFORE_CUTOFF")
            if timestamp(g["start_utc"]) >= timestamp(cutoff) or str(g["game_id"]) == str(prop["event_id"]):
                raise ValueError("TARGET_OR_FUTURE_GAME_EXCLUDED")
            if g.get("available_after_utc") and timestamp(g["available_after_utc"]) >= timestamp(cutoff):
                raise ValueError("SOURCE_DATE_PRECISION_CANNOT_ESTABLISH_PRIOR_COMPLETION")
            # Date-only feeds cannot establish that a same-day game finished earlier.
            if g.get("date_precision") == "DAY" and timestamp(g["start_utc"]).date() >= timestamp(cutoff).date():
                raise ValueError("SAME_DAY_DATE_ONLY_GAME_EXCLUDED")
            if mode == "PREGAME" and timestamp(g["retrieved_at_utc"]) > timestamp(cutoff):
                raise ValueError("SOURCE_CAPTURE_AFTER_CUTOFF")
            if g["scope"] != prop["scope"]:
                raise ValueError("MARKET_SCOPE_MISMATCH")
            for k in CONTEXT_KEYS.get(prop["sport"], []):
                if g.get("context", {}).get(k) != prop["rules"][k]:
                    raise ValueError("INCOMPARABLE_SPORT_CONTEXT:" + k)
            value = stat_value(g, prop)
            if g.get("workload") is not None and number(g["workload"]) < 0:
                raise ValueError("INVALID_OBSERVED_WORKLOAD")
            if g.get("workload") is not None and not g.get("workload_unit"):
                raise ValueError("OBSERVED_WORKLOAD_UNIT_REQUIRED")
            g["value"] = value
            identity = str(g["game_id"])
            if identity in by_id:
                previous = by_id[identity]
                if previous["stats"] != g["stats"] or previous.get("workload") != g.get("workload"):
                    raise ValueError("CONFLICTING_DUPLICATE_GAME:" + identity)
                continue
            by_id[identity] = g
        except (ValueError, KeyError, TypeError) as exc:
            if str(exc).startswith("CONFLICTING_DUPLICATE_GAME"):
                raise
            rejected.append({"game_id": g.get("game_id"), "reason": str(exc)})
    selected = sorted(by_id.values(), key=lambda r: (timestamp(r["start_utc"]), str(r["game_id"])))
    if len(selected) < 8:
        raise ValueError("EIGHT_COMPARABLE_COMPLETED_GAMES_REQUIRED:" + str(len(selected)))
    return selected, rejected
