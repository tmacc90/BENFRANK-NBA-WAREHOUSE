"""BENFRANK possession/lineup/WOWY acquisition.

Free-source order:
1) NBA public CDN liveData play-by-play + box score (preferred game-level route)
2) stats.nba.com PlayByPlayV3/BoxScoreTraditionalV3 fallback
3) cached copies from either route

The public CDN action schema includes a possession team id. Five-man stints are
reconstructed from starters + substitutions and are accepted only after official
box-score minute reconciliation. Bad reconstructions are quarantined, never
silently promoted to FULL evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests

CDN = "https://cdn.nba.com/static/json/liveData"
STATS = "https://stats.nba.com/stats"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Referer": "https://www.nba.com/",
    "Accept": "application/json, text/plain, */*",
}
CLOCK = re.compile(r"PT(?:(\d+)M)?([0-9.]+)S")
SUB_RE = re.compile(r"SUB:\s*(.+?)\s+FOR\s+(.+)$", re.I)


def name_key(value):
    s = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c.lower() for c in s if c.isalnum())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def iso_seconds(value):
    m = CLOCK.fullmatch(str(value or ""))
    if not m:
        raise ValueError("BAD_ISO_CLOCK:" + str(value))
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def elapsed(period, clock):
    qlen = 720 if int(period) <= 4 else 300
    prior = min(int(period) - 1, 4) * 720 + max(int(period) - 5, 0) * 300
    return prior + (qlen - iso_seconds(clock))


def _get_json(url, cache, params=None, timeout=25):
    cache = Path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        return json.loads(cache.read_text()), "CACHE"
    last = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            raw = response.content
            data = response.json()
            cache.write_bytes(raw)
            cache.with_suffix(cache.suffix + ".meta.json").write_text(json.dumps({
                "url": response.url,
                "sha256": sha(raw),
                "retrieved_unix": time.time(),
                "status": response.status_code,
            }, indent=2) + "\n")
            return data, "NETWORK"
        except Exception as exc:
            last = exc
            time.sleep(1.25 * (attempt + 1))
    raise RuntimeError("SOURCE_FETCH_FAILED:" + type(last).__name__ + ":" + str(last))


def _result_rows(data, wanted):
    sets = data.get("resultSets") or data.get("resultSet") or []
    if isinstance(sets, dict):
        sets = [sets]
    for item in sets:
        if str(item.get("name", "")).lower() == wanted.lower():
            headers = item.get("headers", [])
            return [dict(zip(headers, row)) for row in item.get("rowSet", [])]
    return []


def fetch_game_sources(game_id, root):
    root = Path(root)
    failures = []
    try:
        pbp, pr = _get_json(
            f"{CDN}/playbyplay/playbyplay_{game_id}.json",
            root / "raw" / "cdn_playbyplay.json",
        )
        box, br = _get_json(
            f"{CDN}/boxscore/boxscore_{game_id}.json",
            root / "raw" / "cdn_boxscore.json",
        )
        if pbp.get("game", {}).get("actions") and box.get("game", {}).get("homeTeam"):
            return pbp, box, {"pbp": "NBA_CDN_" + pr, "box": "NBA_CDN_" + br, "failures": failures}
        failures.append("NBA_CDN_EMPTY_SCHEMA")
    except Exception as exc:
        failures.append("NBA_CDN:" + type(exc).__name__ + ":" + str(exc))

    try:
        pbp, pr = _get_json(
            STATS + "/playbyplayv3",
            root / "raw" / "stats_playbyplayv3.json",
            {"GameID": game_id, "StartPeriod": 0, "EndPeriod": 0},
        )
        box, br = _get_json(
            STATS + "/boxscoretraditionalv3",
            root / "raw" / "stats_boxscoretraditionalv3.json",
            {"GameID": game_id, "StartPeriod": 0, "EndPeriod": 0,
             "StartRange": 0, "EndRange": 0, "RangeType": 0},
        )
        if _result_rows(pbp, "PlayByPlay") and _result_rows(box, "PlayerStats"):
            return pbp, box, {"pbp": "NBA_STATS_" + pr, "box": "NBA_STATS_" + br, "failures": failures}
        failures.append("NBA_STATS_EMPTY_SCHEMA")
    except Exception as exc:
        failures.append("NBA_STATS:" + type(exc).__name__ + ":" + str(exc))
    raise RuntimeError("ALL_GAME_SOURCES_FAILED|" + "|".join(failures))


def parse_actions(data):
    if isinstance(data.get("game"), dict):
        actions = list(data["game"].get("actions", []))
    else:
        actions = _result_rows(data, "PlayByPlay")
    actions.sort(key=lambda a: (
        int(a.get("period", a.get("PERIOD", 0)) or 0),
        int(a.get("orderNumber", a.get("actionId", a.get("actionNumber", 0))) or 0),
    ))
    return actions


def parse_players(data):
    players = []
    if isinstance(data.get("game"), dict) and data["game"].get("homeTeam"):
        game = data["game"]
        for side in ("homeTeam", "awayTeam"):
            team = game[side]
            for p in team.get("players", []):
                players.append({
                    "team_id": int(team["teamId"]),
                    "team": team.get("teamTricode"),
                    "player_id": int(p["personId"]),
                    "name": p.get("name") or (str(p.get("firstName", "")) + " " + str(p.get("familyName", ""))).strip(),
                    "starter": str(p.get("starter", "0")) == "1" or bool(p.get("starter") is True),
                    "minutes": iso_seconds(p.get("statistics", {}).get("minutes", "PT0M0S")) / 60,
                    "official": p.get("statistics", {}),
                })
        return players

    for p in _result_rows(data, "PlayerStats"):
        first = p.get("firstName", "")
        last = p.get("familyName", "")
        players.append({
            "team_id": int(p["teamId"]),
            "team": p.get("teamTricode"),
            "player_id": int(p["personId"]),
            "name": (first + " " + last).strip() or p.get("nameI"),
            "starter": bool(str(p.get("position", "")).strip()),
            "minutes": iso_seconds(p.get("minutes", "PT0M0S")) / 60,
            "official": p,
        })
    return players


def _action_period(a):
    return int(a.get("period", a.get("PERIOD", 0)) or 0)


def _action_clock(a):
    return a.get("clock", a.get("PCTIMESTRING"))


def _action_type(a):
    return str(a.get("actionType", a.get("EVENTMSGTYPE", ""))).lower()


def _sub_names(action):
    desc = str(action.get("description") or action.get("HOMEDESCRIPTION") or action.get("VISITORDESCRIPTION") or "")
    match = SUB_RE.search(desc)
    return (match.group(1).strip(), match.group(2).strip()) if match else (None, None)


def infer_period_starters(actions, players, team_id, period, previous=None):
    roster = {p["player_id"]: p for p in players if p["team_id"] == team_id}
    if period == 1:
        ids = [p["player_id"] for p in players if p["team_id"] == team_id and p["starter"]]
        if len(ids) == 5:
            return ids, "BOX_STARTERS"

    period_actions = [a for a in actions if _action_period(a) == period]
    first_sub_index = None
    first_sub_clock = None
    for idx, a in enumerate(period_actions):
        if _action_type(a) in ("substitution", "8") and int(a.get("teamId", a.get("PLAYER1_TEAM_ID", 0)) or 0) == team_id:
            first_sub_index = idx
            first_sub_clock = _action_clock(a)
            break
    candidates = []
    stop = len(period_actions) if first_sub_index is None else first_sub_index
    for a in period_actions[:stop]:
        ids = [a.get("personId"), a.get("PLAYER1_ID")]
        ids += list(a.get("personIdsFilter") or [])
        for pid in ids:
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                continue
            if pid in roster and pid not in candidates:
                candidates.append(pid)

    if first_sub_index is not None:
        for a in period_actions[first_sub_index:]:
            if _action_clock(a) != first_sub_clock:
                break
            if int(a.get("teamId", a.get("PLAYER1_TEAM_ID", 0)) or 0) != team_id:
                continue
            incoming_name, outgoing_name = _sub_names(a)
            outgoing = next((p["player_id"] for p in players
                             if p["team_id"] == team_id and name_key(p["name"]) == name_key(outgoing_name)), None)
            raw_out = a.get("PLAYER2_ID")
            if raw_out:
                outgoing = int(raw_out)
            if outgoing is None:
                # In modern NBA PBP the action person is commonly the outgoing player.
                pid = a.get("personId") or a.get("PLAYER1_ID")
                if pid and int(pid) in roster:
                    outgoing = int(pid)
            if outgoing and outgoing not in candidates:
                candidates.append(outgoing)

    if len(candidates) < 5 and previous:
        for pid in previous:
            if pid in roster and pid not in candidates:
                candidates.append(pid)
            if len(candidates) == 5:
                break
        method = "PBP_PARTICIPANTS_PLUS_PREVIOUS_PERIOD_FILL"
    else:
        method = "PBP_PARTICIPANTS_AND_FIRST_SUB_OUTGOING"

    if len(candidates) != 5:
        raise ValueError(f"PERIOD_STARTERS_UNRESOLVED:{period}:{team_id}:{len(candidates)}")
    return candidates, method


def reconstruct_stints(actions, players):
    team_ids = sorted({p["team_id"] for p in players})
    if len(team_ids) != 2:
        raise ValueError("BOX_TEAM_COUNT_NOT_TWO")
    periods = sorted({_action_period(a) for a in actions if _action_period(a) > 0})
    stints = []
    previous = {}
    name_maps = {
        tid: {name_key(p["name"]): p["player_id"] for p in players if p["team_id"] == tid}
        for tid in team_ids
    }

    for period in periods:
        current = {}
        methods = {}
        for tid in team_ids:
            current[tid], methods[tid] = infer_period_starters(
                actions, players, tid, period, previous.get(tid)
            )
        qlen = 720 if period <= 4 else 300
        stint_start = elapsed(period, f"PT{qlen // 60}M00.00S")
        period_actions = [a for a in actions if _action_period(a) == period]

        for action in period_actions:
            if _action_type(action) not in ("substitution", "8"):
                continue
            tid = int(action.get("teamId", action.get("PLAYER1_TEAM_ID", 0)) or 0)
            if tid not in current:
                continue
            t = elapsed(period, _action_clock(action))
            if t > stint_start:
                stints.append({
                    "period": period, "start": stint_start, "end": t,
                    "lineups": {str(k): sorted(v) for k, v in current.items()},
                    "period_start_methods": methods,
                })
            incoming_name, outgoing_name = _sub_names(action)
            incoming = name_maps[tid].get(name_key(incoming_name))
            outgoing = name_maps[tid].get(name_key(outgoing_name))
            if action.get("PLAYER2_ID"):
                outgoing = int(action["PLAYER2_ID"])
            if outgoing is None:
                raw = action.get("personId") or action.get("PLAYER1_ID")
                if raw and int(raw) in current[tid]:
                    outgoing = int(raw)
            if incoming is None or outgoing is None or outgoing not in current[tid]:
                raise ValueError("SUBSTITUTION_UNRESOLVED:" + str(action.get("description", "")))
            current[tid].remove(outgoing)
            current[tid].append(incoming)
            if len(set(current[tid])) != 5:
                raise ValueError("LINEUP_NOT_FIVE")
            stint_start = t

        end = elapsed(period, "PT0M00.00S")
        if end > stint_start:
            stints.append({
                "period": period, "start": stint_start, "end": end,
                "lineups": {str(k): sorted(v) for k, v in current.items()},
                "period_start_methods": methods,
            })
        previous = {tid: list(current[tid]) for tid in team_ids}
    return stints


def _score(action):
    def n(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return n(action.get("scoreHome")), n(action.get("scoreAway"))


def enrich_stints(stints, actions, players, box):
    by_id = {p["player_id"]: p for p in players}
    team_ids = sorted({p["team_id"] for p in players})
    home_id = int(box.get("game", {}).get("homeTeam", {}).get("teamId") or team_ids[0])
    last_possession = None

    for stint in stints:
        stint["possession_segments"] = {str(t): 0 for t in team_ids}
        stint["player_stats"] = {}
        stint["score_start"] = None
        stint["score_end"] = None
        relevant = []
        for action in actions:
            if _action_period(action) != stint["period"]:
                continue
            try:
                t = elapsed(stint["period"], _action_clock(action))
            except Exception:
                continue
            if stint["start"] <= t < stint["end"] or (math.isclose(t, stint["end"]) and _action_type(action) == "period"):
                relevant.append(action)
        relevant.sort(key=lambda a: int(a.get("orderNumber", a.get("actionId", a.get("actionNumber", 0))) or 0))

        for action in relevant:
            hs, as_ = _score(action)
            if hs is not None and as_ is not None:
                if stint["score_start"] is None:
                    stint["score_start"] = [hs, as_]
                stint["score_end"] = [hs, as_]

            poss = action.get("possession")
            try:
                poss = int(poss)
            except (TypeError, ValueError):
                poss = 0
            if poss in team_ids and poss != last_possession:
                stint["possession_segments"][str(poss)] += 1
                last_possession = poss

            pid = action.get("personId") or action.get("PLAYER1_ID")
            try:
                pid = int(pid)
            except (TypeError, ValueError):
                pid = 0
            typ = _action_type(action)
            if pid in by_id:
                stats = stint["player_stats"].setdefault(str(pid), {
                    "pts": 0, "fga": 0, "fg3a": 0, "fta": 0,
                    "reb": 0, "ast": 0, "tov": 0,
                })
                is_fg = int(action.get("isFieldGoal", 0) or 0) == 1
                if is_fg:
                    stats["fga"] += 1
                    shot_value = int(action.get("shotValue", 0) or 0)
                    if shot_value == 3:
                        stats["fg3a"] += 1
                    if str(action.get("shotResult", "")).lower() == "made" or "made shot" in typ:
                        stats["pts"] += shot_value or 2
                if typ in ("freethrow", "free throw"):
                    stats["fta"] += 1
                    if str(action.get("shotResult", "")).lower() == "made":
                        stats["pts"] += 1
                if typ == "rebound":
                    stats["reb"] += 1
                if "turnover" in typ:
                    stats["tov"] += 1

            for key in ("assistPersonId", "assistPlayerId"):
                aid = action.get(key)
                try:
                    aid = int(aid)
                except (TypeError, ValueError):
                    continue
                if aid in by_id:
                    stint["player_stats"].setdefault(str(aid), {
                        "pts": 0, "fga": 0, "fg3a": 0, "fta": 0,
                        "reb": 0, "ast": 0, "tov": 0,
                    })["ast"] += 1

        if stint["score_start"] is None:
            stint["score_start"] = stint.get("_previous_score", [0, 0])
        if stint["score_end"] is None:
            stint["score_end"] = stint["score_start"]
        for later in stints:
            if later is stint:
                continue
            if later["start"] == stint["end"] and later["period"] == stint["period"]:
                later["_previous_score"] = stint["score_end"]
    for stint in stints:
        stint.pop("_previous_score", None)
        stint["home_team_id"] = home_id
    return stints


def validate_minutes(stints, players):
    reconstructed = defaultdict(float)
    for stint in stints:
        minutes = (stint["end"] - stint["start"]) / 60
        for ids in stint["lineups"].values():
            if len(ids) != 5 or len(set(ids)) != 5:
                raise ValueError("INVALID_FIVE_MAN_STINT")
            for pid in ids:
                reconstructed[int(pid)] += minutes

    official_total = sum(p["minutes"] for p in players if p["minutes"] > 0)
    absolute_error = sum(abs(reconstructed[p["player_id"]] - p["minutes"])
                         for p in players if p["minutes"] > 0)
    error_pct = 100 * absolute_error / official_total if official_total else 100.0
    per_player = {
        str(p["player_id"]): {
            "official": round(p["minutes"], 3),
            "reconstructed": round(reconstructed[p["player_id"]], 3),
            "absolute_error": round(abs(reconstructed[p["player_id"]] - p["minutes"]), 3),
        }
        for p in players if p["minutes"] > 0
    }
    quality = "FULL" if error_pct <= 1 else "FALLBACK" if error_pct <= 3 else "QUARANTINED"
    return {
        "quality": quality,
        "minute_error_pct": round(error_pct, 4),
        "official_player_minutes_total": round(official_total, 3),
        "reconstructed_player_minutes_total": round(sum(reconstructed.values()), 3),
        "per_player": per_player,
    }


def summarize_game(stints, players, validation):
    player_minutes = defaultdict(float)
    lineup_minutes = defaultdict(float)
    closing = defaultdict(lambda: [0.0, 0.0])
    team_possessions = defaultdict(int)

    for stint in stints:
        dur = (stint["end"] - stint["start"]) / 60
        score = stint.get("score_start") or [0, 0]
        competitive_close = stint["period"] == 4 and stint["end"] >= 2520 and abs(score[0] - score[1]) <= 10
        for tid, ids in stint["lineups"].items():
            lineup_minutes[tid + ":" + "_".join(map(str, ids))] += dur
            for pid in ids:
                player_minutes[int(pid)] += dur
            if competitive_close:
                roster_ids = [p["player_id"] for p in players if str(p["team_id"]) == tid]
                for pid in roster_ids:
                    closing[pid][1] += dur
                for pid in ids:
                    closing[int(pid)][0] += dur
        for tid, count in stint.get("possession_segments", {}).items():
            team_possessions[tid] += int(count)

    return {
        "validation": validation,
        "player_minutes": {str(k): round(v, 3) for k, v in player_minutes.items()},
        "lineup_minutes": {k: round(v, 3) for k, v in lineup_minutes.items()},
        "team_possession_segments": dict(team_possessions),
        "closing_share": {str(k): (v[0] / v[1] if v[1] else None) for k, v in closing.items()},
    }


def acquire_game(game_id, out):
    if not re.fullmatch(r"\d{10}", str(game_id)):
        raise ValueError("GAME_ID_MUST_BE_10_DIGITS")
    root = Path(out) / str(game_id)
    if (root / "receipt.json").exists() and (root / "stints.json").exists():
        return json.loads((root / "receipt.json").read_text())

    pbp, box, routes = fetch_game_sources(str(game_id), root)
    actions = parse_actions(pbp)
    players = parse_players(box)
    if not actions or len(players) < 10:
        raise ValueError("RAW_GAME_INPUT_INCOMPLETE")

    stints = reconstruct_stints(actions, players)
    stints = enrich_stints(stints, actions, players, box)
    validation = validate_minutes(stints, players)
    summary = summarize_game(stints, players, validation)

    root.mkdir(parents=True, exist_ok=True)
    (root / "players.json").write_text(json.dumps(players, indent=2) + "\n")
    (root / "stints.json").write_text(json.dumps(stints, indent=2) + "\n")
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    status = "FULL_RECONSTRUCTION" if validation["quality"] == "FULL" else (
        "FALLBACK_RECONSTRUCTION" if validation["quality"] == "FALLBACK" else "QUARANTINED"
    )
    receipt = {
        "game_id": str(game_id),
        "status": status,
        "quality": validation["quality"],
        "routes": routes,
        "events": len(actions),
        "players": len(players),
        "stints": len(stints),
        "five_man_units": len(summary["lineup_minutes"]),
        "minute_error_pct": validation["minute_error_pct"],
        "possession_field_used": any(a.get("possession") for a in actions),
        "source_contract": "NBA_CDN_PRIMARY_STATS_NBA_FALLBACK",
    }
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def _nba_game_ids(record):
    ids = []
    direct = record.get("source_game_id")
    if direct and re.fullmatch(r"\d{10}", str(direct)):
        ids.append(str(direct))
    for values in (record.get("source_game_ids") or {}).values():
        for value in values or []:
            if re.fullmatch(r"\d{10}", str(value)):
                ids.append(str(value))
    return ids


def _add_stats(dst, src):
    for key in ("pts", "fga", "fg3a", "fta", "reb", "ast", "tov"):
        dst[key] += src.get(key, 0)


def _rate(stats, possessions):
    if not possessions:
        return None
    return {key + "_per100": 100 * stats[key] / possessions
            for key in ("pts", "fga", "fg3a", "fta", "reb", "ast", "tov")}


def acquire_history_context(player, records, cache_root, max_games=12):
    ordered = sorted(records, key=lambda r: (r.get("date", ""), r.get("game_id", "")), reverse=True)
    game_ids = []
    for record in ordered:
        for gid in _nba_game_ids(record):
            if gid not in game_ids:
                game_ids.append(gid)
        if len(game_ids) >= max_games:
            break

    result = {
        "player": player,
        "requested_games": len(game_ids),
        "games": [],
        "usable_games": 0,
        "full_games": 0,
        "fallback_games": 0,
        "quarantined_games": 0,
        "target": {},
        "teammates": {},
        "five_man_units": {},
        "stage_receipts": {},
    }
    total = {k: 0 for k in ("pts", "fga", "fg3a", "fta", "reb", "ast", "tov")}
    total_poss = 0
    total_minutes = 0.0
    closing_on = closing_eligible = 0.0
    teammate_acc = {}
    lineup_acc = {}

    for gid in game_ids:
        try:
            receipt = acquire_game(gid, cache_root)
            root = Path(cache_root) / gid
            players = json.loads((root / "players.json").read_text())
            stints = json.loads((root / "stints.json").read_text())
            matches = [p for p in players if name_key(p["name"]) == name_key(player)]
            if len(matches) != 1:
                raise ValueError("TARGET_PLAYER_NOT_UNIQUE_IN_BOX")
            target = matches[0]
            pid = target["player_id"]
            tid = str(target["team_id"])
            game_status = receipt["quality"]
            result["games"].append({"game_id": gid, "quality": game_status,
                                    "minute_error_pct": receipt["minute_error_pct"]})
            if game_status == "QUARANTINED":
                result["quarantined_games"] += 1
                continue
            result["usable_games"] += 1
            result["full_games"] += int(game_status == "FULL")
            result["fallback_games"] += int(game_status == "FALLBACK")
            teammate_names = {p["player_id"]: p["name"] for p in players if str(p["team_id"]) == tid}

            for stint in stints:
                ids = list(map(int, stint["lineups"].get(tid, [])))
                if pid not in ids:
                    continue
                dur = (stint["end"] - stint["start"]) / 60
                poss = int(stint.get("possession_segments", {}).get(tid, 0))
                stats = stint.get("player_stats", {}).get(str(pid), {})
                total_minutes += dur
                total_poss += poss
                _add_stats(total, stats)

                lineup_key = "_".join(map(str, sorted(ids)))
                la = lineup_acc.setdefault(lineup_key, {
                    "minutes": 0.0, "possessions": 0,
                    "stats": {k: 0 for k in total},
                    "players": [teammate_names.get(x, str(x)) for x in ids],
                })
                la["minutes"] += dur
                la["possessions"] += poss
                _add_stats(la["stats"], stats)

                for mate in ids:
                    if mate == pid:
                        continue
                    ta = teammate_acc.setdefault(mate, {
                        "name": teammate_names.get(mate, str(mate)),
                        "minutes_with": 0.0, "possessions_with": 0,
                        "stats_with": {k: 0 for k in total},
                    })
                    ta["minutes_with"] += dur
                    ta["possessions_with"] += poss
                    _add_stats(ta["stats_with"], stats)

                score = stint.get("score_start") or [0, 0]
                if stint["period"] == 4 and stint["end"] >= 2520 and abs(score[0] - score[1]) <= 10:
                    close_dur = dur
                    closing_eligible += close_dur
                    closing_on += close_dur

            # eligible closing time while target is off
            for stint in stints:
                score = stint.get("score_start") or [0, 0]
                if stint["period"] != 4 or stint["end"] < 2520 or abs(score[0] - score[1]) > 10:
                    continue
                ids = list(map(int, stint["lineups"].get(tid, [])))
                if pid not in ids:
                    closing_eligible += (stint["end"] - stint["start"]) / 60
        except Exception as exc:
            result["games"].append({"game_id": gid, "quality": "FAILED",
                                    "reason": type(exc).__name__ + ":" + str(exc)})

    result["target"] = {
        "minutes": round(total_minutes, 3),
        "possessions": total_poss,
        "stats": total,
        "rates": _rate(total, total_poss),
        "closing_share": closing_on / closing_eligible if closing_eligible else None,
        "closing_minutes_on": round(closing_on, 3),
        "closing_minutes_eligible": round(closing_eligible, 3),
    }

    for mate, acc in teammate_acc.items():
        without_poss = max(0, total_poss - acc["possessions_with"])
        without_stats = {k: total[k] - acc["stats_with"][k] for k in total}
        with_rate = _rate(acc["stats_with"], acc["possessions_with"])
        without_rate = _rate(without_stats, without_poss)
        ratios = {}
        for stat in ("fga", "pts", "reb", "ast"):
            a = with_rate and with_rate.get(stat + "_per100")
            b = without_rate and without_rate.get(stat + "_per100")
            raw = a / b if a is not None and b not in (None, 0) else None
            weight = acc["possessions_with"] / (acc["possessions_with"] + 200) if acc["possessions_with"] else 0
            ratios[stat + "_ratio_shrunk"] = (1 + (raw - 1) * weight) if raw is not None else None
        result["teammates"][str(mate)] = {
            **acc,
            "with_rates": with_rate,
            "without_rates": without_rate,
            **ratios,
        }

    result["five_man_units"] = {
        key: {
            "minutes": round(value["minutes"], 3),
            "possessions": value["possessions"],
            "players": value["players"],
            "rates": _rate(value["stats"], value["possessions"]),
        }
        for key, value in sorted(lineup_acc.items(), key=lambda kv: kv[1]["minutes"], reverse=True)
    }

    if result["usable_games"] >= 8 and total_poss >= 250:
        quality = "FULL"
    elif result["usable_games"] >= 3 and total_poss >= 75:
        quality = "FALLBACK"
    else:
        quality = "LIMITED"
    result["quality"] = quality
    result["stage_receipts"] = {
        "33": {"stage": "Teammate WOWY", "execution": "EXECUTED", "quality": quality,
               "games": result["usable_games"], "possessions": total_poss,
               "teammates": len(result["teammates"])},
        "34": {"stage": "Five-Man Lineups", "execution": "EXECUTED", "quality": quality,
               "games": result["usable_games"], "five_man_units": len(result["five_man_units"])},
        "35": {"stage": "Closing Lineup", "execution": "EXECUTED",
               "quality": quality if closing_eligible else "LIMITED",
               "competitive_closing_minutes": round(closing_eligible, 3),
               "closing_share": result["target"]["closing_share"]},
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-id", action="append")
    parser.add_argument("--history-json")
    parser.add_argument("--player")
    parser.add_argument("--max-games", type=int, default=12)
    parser.add_argument("--output", default="lineup_cache")
    args = parser.parse_args()
    if args.history_json:
        if not args.player:
            raise SystemExit("--player required with --history-json")
        records = json.loads(Path(args.history_json).read_text())
        result = acquire_history_context(args.player, records, args.output, args.max_games)
        print(json.dumps(result, indent=2))
        return 0
    if not args.game_id:
        raise SystemExit("--game-id or --history-json required")
    results = []
    for gid in args.game_id:
        try:
            results.append(acquire_game(gid, args.output))
        except Exception as exc:
            results.append({"game_id": gid, "status": "FAILED",
                            "reason": type(exc).__name__ + ":" + str(exc)})
    print(json.dumps(results, indent=2))
    return 0 if all(r.get("status") != "FAILED" for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
