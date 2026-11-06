"""Bounded live requests, preserved raw bytes, explicit fallback and identity checks.

ESPN is a secondary source, not an official-stat verification claim. Specialist
providers can supply the normalized JSON contract without sharing sport state.
"""
import csv
import datetime as dt
import io
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .contracts import key, now, number, sha, timestamp

ESPN = {
    "NBA": ("basketball", "nba"), "WNBA": ("basketball", "wnba"),
    "NCAAB": ("basketball", "mens-college-basketball"),
    "NFL": ("football", "nfl"), "CFB": ("football", "college-football"),
    "NHL": ("hockey", "nhl"), "MLB": ("baseball", "mlb"),
    "SOCCER": ("soccer", None),
}
NAMES = {
    "points": "points", "totalRebounds": "rebounds", "assists": "assists",
    "steals": "steals", "blocks": "blocks", "turnovers": "turnovers",
    "minutes": "minutes", "timeOnIcePerGame": "ice_time",
    "passingYards": "passing_yards", "passingAttempts": "passing_attempts",
    "passingTouchdowns": "passing_touchdowns", "completions": "completions",
    "rushingYards": "rushing_yards", "rushingAttempts": "rushing_attempts",
    "rushingTouchdowns": "rushing_touchdowns", "receivingYards": "receiving_yards",
    "receivingTouchdowns": "receiving_touchdowns", "receptions": "receptions",
    "receivingTargets": "targets", "totalGoals": "goals", "goalAssists": "assists",
    "totalShots": "shots", "shotsOnTarget": "shots_on_target", "goals": "goals",
    "shotsTotal": "shots_on_goal", "saves": "saves", "atBats": "at_bats",
    "plateAppearances": "plate_appearances", "hits": "hits", "runs": "runs",
    "doubles": "doubles", "triples": "triples", "homeRuns": "home_runs",
    "RBIs": "rbis", "walks": "batter_walks", "hitByPitch": "hit_by_pitch",
    "strikeouts": "batter_strikeouts", "stolenBases": "stolen_bases",
    "earnedRuns": "earned_runs", "hitsAllowed": "hits_allowed",
    "walksAllowed": "walks_allowed", "totalPitches": "pitches",
    "runsAllowed": "runs_allowed", "pitchesThrown": "pitches",
}


def public_https(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("PUBLIC_HTTPS_SOURCE_REQUIRED")
    if parsed.port not in (None, 443):
        raise ValueError("STANDARD_HTTPS_PORT_REQUIRED")
    if any(k.lower() in ("token", "api_key", "apikey", "secret", "access_token") for k, _ in urllib.parse.parse_qsl(parsed.query)):
        raise ValueError("SOURCE_CREDENTIALS_MUST_NOT_APPEAR_IN_ARCHIVED_URLS")
    # Some managed environments resolve public hosts at the HTTPS proxy rather
    # than in the process. These fixed provider names do not need local DNS.
    if parsed.hostname in {"site.web.api.espn.com", "site.api.espn.com", "api.jolpi.ca", "raw.githubusercontent.com"}:
        return url
    for entry in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(entry[4][0]).is_global:
            raise ValueError("PRIVATE_NETWORK_SOURCE_REJECTED")
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Capture:
    def __init__(self, root, timeout=12):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.receipts, self.cache = [], {}

    def get(self, url, kind="json"):
        if url in self.cache:
            return self.cache[url]
        public_https(url)
        opener = urllib.request.build_opener(SafeRedirect())
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "BENFRANK-OMNI/1.0", "Accept": "application/json,text/csv"})
                with opener.open(req, timeout=self.timeout) as response:
                    raw = response.read(12_000_001)
                if len(raw) > 12_000_000:
                    raise ValueError("SOURCE_BODY_SIZE_LIMIT")
                receipt = {"source_url": url, "source_sha256": sha(raw), "retrieved_at_utc": now(), "bytes": len(raw), "status": "CAPTURED"}
                path = self.root / (receipt["source_sha256"] + "." + kind)
                if not path.exists():
                    path.write_bytes(raw)
                receipt["raw_file"] = path.name
                self.receipts.append(receipt)
                # A parsed response never substitutes for the archived original bytes.
                data = json.loads(raw) if kind == "json" else raw.decode("utf-8-sig")
                self.cache[url] = data, receipt
                return data, receipt
            except (urllib.error.URLError, TimeoutError) as exc:
                code = getattr(exc, "code", None)
                if attempt == 0 and (code is None or code in (429, 500, 502, 503, 504)):
                    time.sleep(.2)
                    continue
                self.receipts.append({"source_url": url, "status": "FAILED", "reason": str(exc), "retrieved_at_utc": now()})
                raise ValueError("SOURCE_REQUEST_FAILED:" + str(code or type(exc).__name__)) from exc

    def save(self):
        (self.root / "source_manifest.json").write_text(json.dumps(self.receipts, indent=2) + "\n")


def numeric_text(value):
    text = str(value).replace(",", "")
    if ":" in text:
        minute, second = text.split(":")
        return float(minute) + float(second) / 60
    value = float(text)
    return number(value)


def espn_stats(names, values, sport, role="hitter"):
    if len(names) != len(values):
        raise ValueError("ESPN_STAT_COLUMN_COUNT_MISMATCH")
    stats = {}
    for name, value in zip(names, values):
        if value in (None, "", "--", "DNP", "NaN", "N/A"):
            continue
        try:
            if name in ("fieldGoalsMade-fieldGoalsAttempted", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted"):
                made, attempts = [float(x) for x in str(value).split("-")]
                a, b = {"fieldGoalsMade-fieldGoalsAttempted": ("fg_made", "fg_attempts"), "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("threes", "three_attempts"), "freeThrowsMade-freeThrowsAttempted": ("ft_made", "ft_attempts")}[name]
                if made < 0 or attempts < made:
                    raise ValueError("INVALID_SHOOTING_IDENTITY")
                stats[a], stats[b] = made, attempts
            elif sport == "MLB" and role == "pitcher" and name in ("innings", "inningsPitched"):
                inning, _, fraction = str(value).partition(".")
                if fraction not in ("", "0", "1", "2"):
                    raise ValueError("INVALID_BASEBALL_INNINGS")
                stats["outs"] = 3 * int(inning) + int(fraction or 0)
            elif sport == "MLB" and role == "pitcher" and name == "strikeouts":
                stats["pitcher_strikeouts"] = numeric_text(value)
            elif sport == "MLB" and role == "pitcher" and name == "walks":
                stats["walks_allowed"] = numeric_text(value)
            elif name in NAMES:
                stats[NAMES[name]] = numeric_text(value)
        except (ValueError, TypeError):
            # Missing stats remain missing. Neither DNP nor unavailable stats become 0.
            continue
    if sport == "MLB" and role == "hitter" and all(k in stats for k in ("hits", "doubles", "triples", "home_runs")):
        stats["singles"] = stats["hits"] - stats["doubles"] - stats["triples"] - stats["home_runs"]
        stats["total_bases"] = stats["hits"] + stats["doubles"] + 2 * stats["triples"] + 3 * stats["home_runs"]
    return stats


def espn_route(prop):
    if prop["sport"] not in ESPN:
        raise ValueError("NO_ESPN_ADAPTER_FOR_SPORT")
    discipline, league = ESPN[prop["sport"]]
    league = league or prop["rules"].get("competition")
    if not league or not re.fullmatch(r"[a-z0-9.-]+", league):
        raise ValueError("EXPLICIT_ESPN_COMPETITION_REQUIRED")
    if not re.fullmatch(r"[0-9]+", str(prop["player_id"])):
        raise ValueError("ESPN_NUMERIC_PLAYER_ID_REQUIRED")
    return discipline, league


def espn_history(prop, config, capture):
    discipline, league = espn_route(prop)
    base = f"https://site.web.api.espn.com/apis/common/v3/sports/{discipline}/{league}/athletes/{prop['player_id']}"
    profile, _ = capture.get(base)
    athlete = profile.get("athlete", {})
    if str(athlete.get("id")) != str(prop["player_id"]) or key(athlete.get("displayName", "")) != key(prop["player"]):
        raise ValueError("ESPN_ATHLETE_IDENTITY_MISMATCH")
    seasons = config.get("seasons")
    if seasons is None:
        source_year = profile.get("season", {}).get("year")
        if type(source_year) is not int:
            raise ValueError("SOURCE_CURRENT_SEASON_UNAVAILABLE_SUPPLY_EXPLICIT_SEASONS")
        seasons = [source_year - 1, source_year]
    if not isinstance(seasons, list) or not 1 <= len(seasons) <= 20 or any(type(y) is not int or not 1900 <= y <= 2100 for y in seasons):
        raise ValueError("ONE_TO_TWENTY_EXPLICIT_SEASONS_REQUIRED")
    games = []
    for year in seasons:
        data, receipt = capture.get(base + "/gamelog?season=" + str(year) + ("&league=" + league if prop["sport"] == "SOCCER" else ""))
        league_codes = {}
        for filter_ in data.get("filters", []):
            if filter_.get("name") == "league":
                for option in filter_.get("options", []):
                    for label in ("displayValue", "shortDisplayName"):
                        if option.get(label):
                            league_codes[key(option[label])] = option["value"]
        for season in data.get("seasonTypes", []):
            for category in season.get("categories", []):
                for row in category.get("events", []):
                    event = data.get("events", {}).get(str(row.get("eventId")), {})
                    # Soccer gamelogs may ignore the requested competition: filter it.
                    event_league = str(event.get("leagueAbbreviation", league))
                    competition = league_codes.get(key(event.get("leagueName", event_league)), event_league.lower())
                    if prop["sport"] == "SOCCER" and competition != league:
                        continue
                    stats = espn_stats(data.get("names", []), row.get("stats", []), prop["sport"], prop["rules"].get("role", "hitter"))
                    field = prop["rules"].get("workload_field")
                    if not field:
                        if prop["sport"] in ("NBA", "WNBA", "NCAAB"):
                            field = "minutes"
                        elif prop["sport"] == "NHL":
                            field = "ice_time"
                        elif prop["sport"] in ("NFL", "CFB"):
                            if prop["market"].startswith("passing") or prop["market"] == "completions":
                                field = "passing_attempts"
                            elif prop["market"].startswith("rushing"):
                                field = "rushing_attempts"
                            elif prop["market"].startswith("receiving") or prop["market"] in ("receptions", "targets"):
                                field = "targets"
                        elif prop["sport"] == "MLB":
                            field = "pitches" if prop["rules"].get("role") == "pitcher" else "plate_appearances"
                    workload = stats.get(field) if field else None
                    no_extra_time = competition in {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "ned.1", "por.1", "bra.1", "bra.2"}
                    games.append({"sport": prop["sport"], "player": athlete["displayName"], "player_id": str(athlete["id"]), "game_id": str(row["eventId"]), "start_utc": event.get("gameDate"), "season": str(year), "season_type": season.get("displayName"), "scope": "FULL_GAME", "opponent": str(event.get("opponent", {}).get("id", "")), "opponent_name": event.get("opponent", {}).get("displayName"), "team_id": str(event.get("team", {}).get("id", "")), "stats": stats, "workload": workload, "workload_unit": field, "context": {"competition": competition, "extra_time": "EXCLUDED" if no_extra_time else "INCLUDED_IF_PLAYED"} if prop["sport"] == "SOCCER" else {}, "completed": event.get("gameResult") in ("W", "L", "T", "D"), **receipt})
    if not games:
        raise ValueError("ESPN_NO_COMPLETED_GAMES_RETURNED")
    return games


def normalized_document(config, capture):
    if "file" in config:
        path = Path(config["file"])
        raw = path.read_bytes()
        expected = config.get("sha256")
        if not expected or sha(raw) != expected:
            raise ValueError("NORMALIZED_FILE_HASH_REQUIRED_OR_MISMATCH")
        data = json.loads(raw)
        receipt = {"source_url": "uploaded:" + path.name, "source_sha256": sha(raw), "retrieved_at_utc": data.get("captured_at_utc", now()), "status": "UPLOADED_SOURCE_NOT_INDEPENDENTLY_VERIFIED"}
        capture.receipts.append(receipt)
        target = capture.root / (receipt["source_sha256"] + ".json")
        if not target.exists():
            target.write_bytes(raw)
    else:
        data, receipt = capture.get(config["url"])
    return data, receipt


def normalized_history(prop, config, capture):
    data, receipt = normalized_document(config, capture)
    if data.get("sport") != prop["sport"]:
        raise ValueError("NORMALIZED_SOURCE_SPORT_MISMATCH")
    # Source metadata is assigned by the collector, never trusted from each row.
    games = [{**g, **receipt} for g in data["games"]]
    return games


def f1_history(prop, config, capture):
    driver = str(prop["player_id"])
    if not re.fullmatch(r"[a-z_]+", driver):
        raise ValueError("JOLPI_DRIVER_ID_REQUIRED")
    games = []
    for year in config["seasons"]:
        endpoint = "qualifying" if prop["rules"].get("session") == "QUALIFYING" else "results"
        data, receipt = capture.get(f"https://api.jolpi.ca/ergast/f1/{int(year)}/drivers/{driver}/{endpoint}.json?limit=100")
        for race in data["MRData"]["RaceTable"]["Races"]:
            result = race["QualifyingResults" if endpoint == "qualifying" else "Results"][0]
            person = result["Driver"]
            if key(person["givenName"] + " " + person["familyName"]) != key(prop["player"]):
                raise ValueError("JOLPI_DRIVER_IDENTITY_MISMATCH")
            date = race["date"] + "T" + race.get("time", "00:00:00Z")
            games.append({"sport": "F1", "player_id": driver, "player": prop["player"], "game_id": f"{year}-{race['round']}-{endpoint}", "start_utc": date, "date_precision": "DAY", "completed": True, "season": str(year), "scope": prop["scope"], "opponent": "FIELD", "stats": {"qualifying_position" if endpoint == "qualifying" else "finishing_position": float(result["position"])}, "context": {"session": prop["rules"]["session"], "circuit": race["Circuit"]["circuitId"]}, **receipt})
    return games


def tennis_history(prop, config, capture):
    if config.get("urls"):
        if not isinstance(config["urls"], list) or not 1 <= len(config["urls"]) <= 20:
            raise ValueError("ONE_TO_TWENTY_TENNIS_SOURCE_FILES_REQUIRED")
        return [g for url in config["urls"] for g in tennis_history(prop, {"url": url}, capture)]
    text, receipt = capture.get(config["url"], "csv")
    games = []
    for row in csv.DictReader(io.StringIO(text)):
        side = next((s for s in ("winner", "loser") if str(row.get(s + "_id")) == str(prop["player_id"])), None)
        if not side:
            continue
        if key(row[side + "_name"]) != key(prop["player"]):
            raise ValueError("TENNIS_PLAYER_IDENTITY_MISMATCH")
        score = row.get("score", "")
        if any(x in score.upper() for x in ("RET", "W/O", "DEF", "ABN")):
            continue
        prefix = "w_" if side == "winner" else "l_"
        stats = {}
        for source, target in (("ace", "aces"), ("df", "double_faults")):
            if row.get(prefix + source) not in (None, ""):
                stats[target] = float(row[prefix + source])
        sets = re.findall(r"(\d+)-(\d+)(?:\(\d+\))?", score)
        # Standard matches only; match tiebreak scoring requires its own adapter.
        if sets and all(int(a) <= 7 and int(b) <= 7 for a, b in sets):
            stats["games"] = sum(int(a) + int(b) for a, b in sets)
            stats["sets"] = len(sets)
        day = dt.datetime.strptime(row["tourney_date"], "%Y%m%d").replace(tzinfo=dt.timezone.utc)
        other = "loser" if side == "winner" else "winner"
        games.append({"sport": "TENNIS", "player_id": str(prop["player_id"]), "player": prop["player"], "game_id": row["tourney_id"] + ":" + row["match_num"], "start_utc": day.isoformat(), "available_after_utc": (day + dt.timedelta(days=21)).isoformat(), "date_precision": "TOURNAMENT", "completed": True, "season": str(day.year), "scope": "FULL_MATCH", "opponent": str(row[other + "_id"]), "stats": stats, "context": {"surface": row["surface"], "best_of": int(row["best_of"])}, **receipt})
    return games


PROVIDERS = {"espn": espn_history, "normalized_json": normalized_history, "jolpi": f1_history, "tennis_csv": tennis_history}


def collect_history(prop, configs, capture):
    if not configs:
        if prop["sport"] in ESPN:
            # The source's season year differs from calendar year in NBA/NHL.
            configs = [{"provider": "espn"}]
        elif prop["sport"] == "F1":
            configs = [{"provider": "jolpi", "seasons": [timestamp(now()).year - 1, timestamp(now()).year]}]
        else:
            raise ValueError("SPECIALIST_SOURCE_REQUIRED:" + prop["sport"] + ":SUPPLY_NORMALIZED_JSON_URL_OR_HASHED_EXPORT")
    failures = []
    for config in configs:
        try:
            if config.get("provider") not in PROVIDERS:
                raise ValueError("UNKNOWN_DATA_PROVIDER")
            result = PROVIDERS[config["provider"]](prop, config, capture)
            if not result:
                raise ValueError("SOURCE_RETURNED_NO_GAMES")
            return result, failures
        except (ValueError, KeyError, OSError, TypeError) as exc:
            failures.append({"provider": config.get("provider"), "reason": str(exc)})
    raise ValueError("ALL_HISTORY_SOURCES_FAILED:" + json.dumps(failures, sort_keys=True))
