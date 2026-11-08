"""SportsDataverse NBA possession/lineup mirror adapter for BENFRANK.

This adapter exists because stats.nba.com and cdn.nba.com commonly block cloud
runner IPs. SportsDataverse publishes the processed NBA Stats play-by-play,
possession, on-court lineup and player-boxscore season parquets on GitHub.

The adapter resolves the upstream commit before download, caches every parquet,
filters only the exact pre-cutoff NBA game IDs already present in BENFRANK's
historical records, validates on-court minutes against official player boxscore
minutes, and derives scoring WOWY/five-man/competitive-closing evidence.

It is intentionally NOT an independent evidence family: all rows ultimately
derive from NBA Stats and must be tagged LINEUP_PBP_CORRELATED_WITH_ROLE_OPPORTUNITY.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import requests

UPSTREAM_REPO = "sportsdataverse/hoopR-nba-stats-data"
UPSTREAM_API = f"https://api.github.com/repos/{UPSTREAM_REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM_REPO}"
DEFAULT_BRANCH = "main"
HEADERS = {
    "User-Agent": "BENFRANK-NBA-WAREHOUSE/lineup-mirror",
    "Accept": "application/vnd.github+json,application/octet-stream,*/*",
}

DATASETS = {
    "pbp": "nba_stats/pbp/parquet/nba_play_by_play_{season}.parquet",
    "possessions": "nba_stats/possessions/parquet/nba_possessions_{season}.parquet",
    "lineups": "nba_stats/game_lineups/parquet/nba_lineups_{season}.parquet",
    "player_box": "nba_stats/player_boxscores/parquet/player_boxscores_{season}.parquet",
    "team_box": "nba_stats/team_boxscores/parquet/team_boxscores_{season}.parquet",
}

ISO_CLOCK = re.compile(r"PT(?:(\d+)M)?([0-9.]+)S")


def name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch.lower() for ch in text if ch.isalnum())


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _request(url: str, *, timeout: int = 40) -> requests.Response:
    last = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:
            last = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"MIRROR_FETCH_FAILED:{type(last).__name__}:{last}")


def resolve_upstream_commit(cache_root: str | Path, ref: str | None = None) -> str:
    """Resolve an upstream branch/ref once and persist the exact commit receipt."""
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    ref = ref or os.getenv("BENFRANK_SDV_REF") or DEFAULT_BRANCH
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    receipt = root / "sportsdataverse_commit.json"
    # Reuse within a single cached run. Every run receipt therefore has an exact
    # commit even if the configured source is the moving main branch.
    if receipt.exists():
        try:
            data = json.loads(receipt.read_text())
            if data.get("requested_ref") == ref and re.fullmatch(r"[0-9a-f]{40}", data.get("sha", "")):
                return data["sha"]
        except Exception:
            pass
    response = _request(f"{UPSTREAM_API}/commits/{ref}")
    data = response.json()
    sha = str(data["sha"])
    receipt.write_text(json.dumps({
        "provider": "SportsDataverse NBA Stats mirror",
        "repository": UPSTREAM_REPO,
        "requested_ref": ref,
        "sha": sha,
        "commit_date": data.get("commit", {}).get("committer", {}).get("date"),
        "resolved_unix": time.time(),
    }, indent=2) + "\n")
    return sha


def _download_dataset(cache_root: str | Path, season: int, family: str, commit: str) -> Path:
    if family not in DATASETS:
        raise KeyError(family)
    root = Path(cache_root) / "sportsdataverse" / commit / str(season)
    root.mkdir(parents=True, exist_ok=True)
    rel = DATASETS[family].format(season=season)
    dest = root / Path(rel).name
    meta = dest.with_suffix(dest.suffix + ".meta.json")
    if dest.exists() and meta.exists():
        return dest
    url = f"{RAW_BASE}/{commit}/{rel}"
    response = _request(url, timeout=90)
    raw = response.content
    if len(raw) < 100:
        raise RuntimeError(f"MIRROR_DATASET_TOO_SMALL:{family}:{season}")
    dest.write_bytes(raw)
    meta.write_text(json.dumps({
        "provider": "SportsDataverse NBA Stats mirror",
        "upstream_commit": commit,
        "family": family,
        "season": season,
        "url": url,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "retrieved_unix": time.time(),
    }, indent=2) + "\n")
    return dest


def load_season(cache_root: str | Path, season: int, commit: str | None = None) -> dict[str, pd.DataFrame]:
    commit = commit or resolve_upstream_commit(cache_root)
    out = {}
    for family in DATASETS:
        path = _download_dataset(cache_root, season, family, commit)
        out[family] = pd.read_parquet(path)
    out["_commit"] = commit
    return out


def season_end_for_date(date_text: str) -> int:
    year, month, _day = map(int, str(date_text)[:10].split("-"))
    return year + 1 if month >= 7 else year


def _parse_minutes(value: Any) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    text = str(value)
    m = ISO_CLOCK.fullmatch(text)
    if m:
        return int(m.group(1) or 0) + float(m.group(2)) / 60.0
    if ":" in text:
        try:
            mm, ss = text.split(":", 1)
            return float(mm) + float(ss) / 60.0
        except Exception:
            pass
    try:
        return float(text)
    except Exception:
        return 0.0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _score_pair(row: pd.Series) -> tuple[int, int]:
    return _to_int(row.get("score_home"), 0), _to_int(row.get("score_away"), 0)


def _lineup_ids(row: pd.Series, prefix: str) -> list[int]:
    ids = []
    for i in range(1, 6):
        pid = _to_int(row.get(f"{prefix}_player_{i}"), 0)
        if pid:
            ids.append(pid)
    return ids


def _player_event_stats(rows: pd.DataFrame, player_id: int) -> dict[str, float]:
    stats = {"pts": 0.0, "fga": 0.0, "fg3a": 0.0, "fta": 0.0,
             "reb": 0.0, "ast": 0.0, "tov": 0.0}
    if rows.empty:
        return stats
    mine = rows[pd.to_numeric(rows.get("person_id"), errors="coerce").fillna(0).astype("int64") == int(player_id)]
    for _, row in mine.iterrows():
        event = str(row.get("event_type") or "").lower()
        is_fg = _to_int(row.get("is_field_goal"), 0) == 1 or event in {"made_shot", "missed_shot"}
        if is_fg:
            stats["fga"] += 1
            value = _to_int(row.get("shot_value"), 0)
            if value == 3:
                stats["fg3a"] += 1
            if event == "made_shot" or str(row.get("shot_result") or "").lower() == "made":
                stats["pts"] += value or 2
        elif event == "free_throw":
            stats["fta"] += 1
            if str(row.get("shot_result") or "").lower() == "made":
                stats["pts"] += 1
        elif event == "rebound":
            stats["reb"] += 1
        elif event == "turnover":
            stats["tov"] += 1
    # The published v3 event schema does not identify an assisting player in a
    # dedicated field, so assist WOWY is intentionally left unavailable here.
    return stats


def _add_stats(dst: dict[str, float], src: dict[str, float]) -> None:
    for key in dst:
        dst[key] += float(src.get(key, 0.0))


def _rate(stats: dict[str, float], possessions: int) -> dict[str, float] | None:
    if possessions <= 0:
        return None
    return {f"{k}_per100": 100.0 * float(v) / possessions for k, v in stats.items()}


def _game_frames(season_frames: dict[str, pd.DataFrame], game_id: str) -> dict[str, pd.DataFrame]:
    out = {}
    for family in ("pbp", "possessions", "lineups", "player_box"):
        frame = season_frames[family]
        if "game_id" not in frame.columns:
            raise ValueError(f"MIRROR_SCHEMA_MISSING_GAME_ID:{family}")
        series = frame["game_id"].astype(str).str.zfill(10)
        out[family] = frame.loc[series == str(game_id).zfill(10)].copy()
    return out


def validate_game(game: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Validate mirror on-court rows against official player-box minutes."""
    pbp = game["pbp"]
    lineups = game["lineups"]
    box = game["player_box"]
    if pbp.empty or lineups.empty or box.empty:
        return {"quality": "QUARANTINED", "reason": "MIRROR_GAME_COMPONENT_MISSING",
                "minute_error_pct": 100.0, "null_lineup_rate": 1.0}

    required = {"game_id", "action_number", "period"}
    if not required <= set(lineups.columns):
        return {"quality": "QUARANTINED", "reason": "LINEUP_SCHEMA_MISSING_KEYS",
                "minute_error_pct": 100.0, "null_lineup_rate": 1.0}
    needed_slots = [f"home_player_{i}" for i in range(1, 6)] + [f"away_player_{i}" for i in range(1, 6)]
    if any(c not in lineups.columns for c in needed_slots):
        return {"quality": "QUARANTINED", "reason": "LINEUP_SCHEMA_MISSING_SLOTS",
                "minute_error_pct": 100.0, "null_lineup_rate": 1.0}

    clock_col = "seconds_remaining" if "seconds_remaining" in pbp.columns else None
    if clock_col is None:
        return {"quality": "QUARANTINED", "reason": "PBP_SECONDS_REMAINING_MISSING",
                "minute_error_pct": 100.0, "null_lineup_rate": 1.0}

    cols = ["game_id", "action_number", "period", clock_col]
    for c in ("score_home", "score_away"):
        if c in pbp.columns:
            cols.append(c)
    joined = lineups.merge(pbp[cols].drop_duplicates(["game_id", "action_number"]),
                           on=["game_id", "action_number", "period"], how="left")
    joined = joined.sort_values(["period", "action_number"]).reset_index(drop=True)

    reconstructed = defaultdict(float)
    null_rows = 0
    row_count = 0
    for period, group in joined.groupby("period", sort=True):
        group = group.sort_values("action_number").reset_index(drop=True)
        qlen = 720.0 if int(period) <= 4 else 300.0
        previous_clock = qlen
        for _, row in group.iterrows():
            clock = _to_float(row.get(clock_col), previous_clock)
            if clock > previous_clock + 0.01:
                clock = previous_clock
            duration = max(0.0, previous_clock - clock)
            ids = _lineup_ids(row, "home") + _lineup_ids(row, "away")
            row_count += 1
            if len(ids) != 10 or len(set(ids)) != 10:
                null_rows += 1
            else:
                for pid in ids:
                    reconstructed[pid] += duration / 60.0
            previous_clock = clock
        # last lineup covers the final clock-to-zero interval
        if len(group):
            row = group.iloc[-1]
            duration = max(0.0, previous_clock)
            ids = _lineup_ids(row, "home") + _lineup_ids(row, "away")
            if len(ids) == 10 and len(set(ids)) == 10:
                for pid in ids:
                    reconstructed[pid] += duration / 60.0

    official_total = 0.0
    absolute_error = 0.0
    compared = 0
    per_player = {}
    id_col = "person_id" if "person_id" in box.columns else "player_id"
    for _, row in box.iterrows():
        pid = _to_int(row.get(id_col), 0)
        minutes = _parse_minutes(row.get("minutes"))
        if not pid or minutes <= 0:
            continue
        rec = reconstructed.get(pid, 0.0)
        official_total += minutes
        absolute_error += abs(rec - minutes)
        compared += 1
        per_player[str(pid)] = {
            "official": round(minutes, 3),
            "reconstructed": round(rec, 3),
            "absolute_error": round(abs(rec - minutes), 3),
        }
    error_pct = 100.0 * absolute_error / official_total if official_total else 100.0
    null_rate = null_rows / row_count if row_count else 1.0
    if error_pct <= 1.0 and null_rate <= 0.02:
        quality = "FULL"
    elif error_pct <= 3.0 and null_rate <= 0.05:
        quality = "FALLBACK"
    else:
        quality = "QUARANTINED"
    return {
        "quality": quality,
        "minute_error_pct": round(error_pct, 4),
        "null_lineup_rate": round(null_rate, 6),
        "players_compared": compared,
        "per_player": per_player,
    }


def _target_identity(box: pd.DataFrame, player: str) -> dict[str, Any]:
    id_col = "person_id" if "person_id" in box.columns else "player_id"
    matches = []
    for _, row in box.iterrows():
        full = (str(row.get("first_name") or "") + " " + str(row.get("family_name") or "")).strip()
        if name_key(full) == name_key(player):
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"TARGET_PLAYER_NOT_UNIQUE_IN_MIRROR_BOX:{player}:{len(matches)}")
    row = matches[0]
    return {
        "player_id": _to_int(row.get(id_col), 0),
        "team_id": _to_int(row.get("team_id"), 0),
        "side": str(row.get("side") or "").lower(),
        "name": player,
    }


def _game_minutes_and_closing(game: dict[str, pd.DataFrame], target: dict[str, Any]) -> tuple[dict[int, float], dict[str, float]]:
    pbp = game["pbp"]
    lineups = game["lineups"]
    clock_col = "seconds_remaining"
    score_cols = [c for c in ("score_home", "score_away") if c in pbp.columns]
    cols = ["game_id", "action_number", "period", clock_col, *score_cols]
    joined = lineups.merge(pbp[cols].drop_duplicates(["game_id", "action_number"]),
                           on=["game_id", "action_number", "period"], how="left")
    joined = joined.sort_values(["period", "action_number"]).reset_index(drop=True)
    lineup_minutes = defaultdict(float)
    closing_on = 0.0
    closing_eligible = 0.0
    prefix = "home" if target["side"] == "home" else "away"
    target_id = target["player_id"]

    for period, group in joined.groupby("period", sort=True):
        qlen = 720.0 if int(period) <= 4 else 300.0
        previous_clock = qlen
        previous_score = (0, 0)
        for _, row in group.sort_values("action_number").iterrows():
            clock = min(previous_clock, _to_float(row.get(clock_col), previous_clock))
            duration = max(0.0, previous_clock - clock)
            own = _lineup_ids(row, prefix)
            if len(own) == 5:
                key = "_".join(map(str, sorted(own)))
                lineup_minutes[key] += duration / 60.0
            score = _score_pair(row) if score_cols else previous_score
            # Interval from previous clock down to this event. Only overlap with
            # the final-six window counts; score state is the last known state.
            if int(period) == 4 and previous_clock > 0 and clock < 360:
                overlap = max(0.0, min(previous_clock, 360.0) - max(clock, 0.0))
                if overlap and abs(previous_score[0] - previous_score[1]) <= 10:
                    closing_eligible += overlap / 60.0
                    if target_id in own:
                        closing_on += overlap / 60.0
            previous_clock = clock
            previous_score = score
        if len(group) and int(period) == 4 and previous_clock > 0:
            row = group.sort_values("action_number").iloc[-1]
            own = _lineup_ids(row, prefix)
            overlap = max(0.0, min(previous_clock, 360.0))
            if overlap and abs(previous_score[0] - previous_score[1]) <= 10:
                closing_eligible += overlap / 60.0
                if target_id in own:
                    closing_on += overlap / 60.0
    return lineup_minutes, {
        "closing_on": closing_on,
        "closing_eligible": closing_eligible,
        "closing_share": closing_on / closing_eligible if closing_eligible else None,
    }


def _game_scoring_context(game: dict[str, pd.DataFrame], target: dict[str, Any]) -> dict[str, Any]:
    pbp = game["pbp"]
    poss = game["possessions"]
    pid = target["player_id"]
    team_id = target["team_id"]
    required = {f"off_player_{i}" for i in range(1, 6)} | {f"def_player_{i}" for i in range(1, 6)}
    if not required <= set(poss.columns):
        raise ValueError("MIRROR_POSSESSIONS_MISSING_LINEUP_COLUMNS")
    if "possession_number" not in poss.columns or "possession_number" not in pbp.columns:
        raise ValueError("MIRROR_POSSESSION_NUMBER_MISSING")

    target_off = []
    for _, row in poss.iterrows():
        if _to_int(row.get("offense_team_id"), 0) != team_id:
            continue
        off = _lineup_ids(row, "off")
        if pid not in off:
            continue
        if "count_as_possession" in poss.columns and row.get("count_as_possession") is False:
            continue
        target_off.append((int(row["possession_number"]), off))

    events_by_poss = {}
    for poss_no, _ in target_off:
        events_by_poss[poss_no] = pbp[pd.to_numeric(pbp["possession_number"], errors="coerce").fillna(-1).astype("int64") == poss_no]

    total_stats = {"pts": 0.0, "fga": 0.0, "fg3a": 0.0, "fta": 0.0,
                   "reb": 0.0, "ast": 0.0, "tov": 0.0}
    teammate = {}
    units = {}
    for poss_no, off in target_off:
        stats = _player_event_stats(events_by_poss.get(poss_no, pd.DataFrame()), pid)
        _add_stats(total_stats, stats)
        unit_key = "_".join(map(str, sorted(off)))
        ua = units.setdefault(unit_key, {
            "possessions": 0,
            "stats": {k: 0.0 for k in total_stats},
            "players": list(map(int, sorted(off))),
        })
        ua["possessions"] += 1
        _add_stats(ua["stats"], stats)
        for mate in off:
            if mate == pid:
                continue
            ta = teammate.setdefault(mate, {
                "possessions_with": 0,
                "stats_with": {k: 0.0 for k in total_stats},
            })
            ta["possessions_with"] += 1
            _add_stats(ta["stats_with"], stats)

    return {
        "possessions": len(target_off),
        "stats": total_stats,
        "teammates": teammate,
        "units": units,
    }


def _download_schedule_master(cache_root: str | Path, commit: str) -> Path:
    root = Path(cache_root) / "sportsdataverse" / commit
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "nba_stats_schedule_master.parquet"
    meta = dest.with_suffix(".parquet.meta.json")
    if dest.exists() and meta.exists():
        return dest
    rel = "nba_stats/nba_stats_schedule_master.parquet"
    url = f"{RAW_BASE}/{commit}/{rel}"
    response = _request(url, timeout=90)
    raw = response.content
    if len(raw) < 1000:
        raise RuntimeError("MIRROR_SCHEDULE_MASTER_TOO_SMALL")
    dest.write_bytes(raw)
    meta.write_text(json.dumps({
        "provider": "SportsDataverse NBA Stats mirror",
        "upstream_commit": commit,
        "family": "schedule_master",
        "url": url,
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "retrieved_unix": time.time(),
    }, indent=2) + "\n")
    return dest


def recent_team_boxes(teams: list[str] | set[str], day: str, cache_root: str | Path,
                      *, max_games: int = 5, commit: str | None = None) -> dict[str, Any]:
    """Last N completed regular-season team boxes from the pinned public mirror."""
    root = Path(cache_root)
    commit = commit or resolve_upstream_commit(root)
    season = season_end_for_date(day)
    schedule = pd.read_parquet(_download_schedule_master(root, commit))
    required_schedule = {
        "game_id", "game_date", "game_status", "season", "season_type_id",
        "home_team_tricode", "away_team_tricode",
    }
    if not required_schedule <= set(schedule.columns):
        missing = sorted(required_schedule - set(schedule.columns))
        raise ValueError("MIRROR_SCHEDULE_SCHEMA_MISSING:" + ",".join(missing))

    schedule = schedule.copy()
    schedule["_date"] = pd.to_datetime(
        schedule["game_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    schedule = schedule.loc[
        (pd.to_numeric(schedule["season"], errors="coerce") == season)
        & (schedule["season_type_id"].astype(str) == "2")
        & (pd.to_numeric(schedule["game_status"], errors="coerce") == 3)
        & schedule["_date"].notna()
        & (schedule["_date"] < day)
    ].copy()
    schedule["game_id"] = schedule["game_id"].astype(str).str.zfill(10)

    wanted = set(teams)
    selected: dict[str, dict[str, Any]] = {}
    counts = {team: 0 for team in wanted}
    ordered = schedule.sort_values(["_date", "game_id"], ascending=[False, False])
    for _, row in ordered.iterrows():
        home = str(row["home_team_tricode"])
        away = str(row["away_team_tricode"])
        relevant = wanted.intersection({home, away})
        if not relevant:
            continue
        gid = str(row["game_id"])
        needed = [team for team in relevant if counts[team] < max_games]
        if not needed:
            continue
        selected.setdefault(gid, {
            "game_id": gid, "date": str(row["_date"]), "home": home, "away": away,
        })
        for team in needed:
            counts[team] += 1
        if all(v >= max_games for v in counts.values()):
            break

    box_path = _download_dataset(root, season, "team_box", commit)
    frame = pd.read_parquet(box_path)
    if "game_id" not in frame.columns:
        raise ValueError("MIRROR_TEAM_BOX_SCHEMA_MISSING_GAME_ID")
    frame = frame.copy()
    frame["game_id"] = frame["game_id"].astype(str).str.zfill(10)

    outputs = {}
    rejected = []
    for gid, spec in sorted(selected.items(), key=lambda kv: (kv[1]["date"], kv[0]), reverse=True):
        try:
            rows = frame.loc[frame["game_id"] == gid].copy()
            if "season_type_id" in rows.columns:
                rows = rows.loc[rows["season_type_id"].astype(str) == "2"]
            if len(rows) != 2:
                raise ValueError(f"MIRROR_TEAM_BOX_EXPECTED_TWO_ROWS:{gid}:{len(rows)}")
            parsed = {}
            for _, row in rows.iterrows():
                team = str(row.get("team_tricode") or "")
                minutes = _parse_minutes(row.get("minutes"))
                if not team or minutes < 239.0:
                    raise ValueError(f"MIRROR_TEAM_BOX_INVALID_ROW:{gid}:{team}:{minutes}")
                parsed[team] = {
                    "fgm": _to_int(row.get("field_goals_made")),
                    "fga": _to_int(row.get("field_goals_attempted")),
                    "fta": _to_int(row.get("free_throws_attempted")),
                    "orb": _to_int(row.get("rebounds_offensive")),
                    "drb": _to_int(row.get("rebounds_defensive")),
                    "tov": _to_int(row.get("turnovers")),
                    "ast": _to_int(row.get("assists")),
                    "blk": _to_int(row.get("blocks")),
                    "minutes": minutes,
                }
            if set(parsed) != {spec["home"], spec["away"]}:
                raise ValueError(
                    f"MIRROR_TEAM_BOX_SCHEDULE_CONFLICT:{gid}:{sorted(parsed)}:"
                    f"{spec['away']}@{spec['home']}"
                )
            outputs["nba:" + gid] = {
                "event": {
                    "event_id": gid, "date": spec["date"],
                    "home": spec["home"], "away": spec["away"],
                },
                "boxes": parsed,
                "source_document": {
                    "id": f"sdv_team_box:{commit}:{season}:{gid}",
                    "family": "NBA_STATS_TEAM_BOX_MIRROR",
                    "provider": "SportsDataverse NBA Stats mirror",
                    "upstream_commit": commit,
                },
                "authority": "SPORTSDATAVERSE_NBA_STATS_TEAM_BOX_MIRROR",
            }
        except Exception as exc:
            rejected.append({"game_id": gid, "reason": f"{type(exc).__name__}:{exc}"})

    actual_counts = {
        team: sum(1 for item in outputs.values() if team in item["boxes"])
        for team in wanted
    }
    return {
        "boxes": outputs,
        "counts": actual_counts,
        "scheduled_counts": counts,
        "rejected": rejected,
        "upstream_commit": commit,
        "season": season,
        "source": "SPORTSDATAVERSE_NBA_STATS_TEAM_BOX_MIRROR",
    }


def team_boxes_from_records(records: list[dict[str, Any]], teams: list[str] | set[str],
                            day: str, cache_root: str | Path, *, max_games: int = 5,
                            commit: str | None = None) -> dict[str, Any]:
    """Build complete prior team-box inputs from exact NBA game IDs already reconciled.

    This never guesses a game identity. It uses only 10-digit NBA IDs present in
    the pre-cutoff historical records, then requires exactly two regular-season
    team-box rows from the pinned SportsDataverse NBA Stats mirror.
    """
    root = Path(cache_root)
    commit = commit or resolve_upstream_commit(root)
    wanted = set(teams)
    candidates: dict[str, dict[str, Any]] = {}
    per_team: dict[str, set[str]] = {team: set() for team in wanted}

    ordered = sorted(
        (r for r in records if r.get("date") and r["date"] < day),
        key=lambda r: (r["date"], r.get("game_id", "")),
        reverse=True,
    )
    for row in ordered:
        team = str(row.get("team") or "")
        opp = str(row.get("opponent") or "")
        relevant = wanted.intersection({team, opp})
        if not relevant:
            continue
        ids = []
        direct = row.get("source_game_id")
        if direct:
            ids.append(str(direct))
        for values in (row.get("source_game_ids") or {}).values():
            ids.extend(map(str, values or []))
        gid = next((x for x in ids if re.fullmatch(r"\d{10}", x)), None)
        if not gid:
            continue
        home, away = ((team, opp) if row.get("home") else (opp, team))
        spec = candidates.setdefault(gid, {
            "game_id": gid,
            "date": row["date"],
            "home": home,
            "away": away,
            "season": season_end_for_date(row["date"]),
        })
        if (spec["date"], spec["home"], spec["away"]) != (row["date"], home, away):
            raise ValueError(f"MIRROR_TEAM_BOX_GAME_IDENTITY_CONFLICT:{gid}")
        for code in relevant:
            if len(per_team[code]) < max_games:
                per_team[code].add(gid)
        if all(len(v) >= max_games for v in per_team.values()):
            break

    selected_ids = set().union(*per_team.values()) if per_team else set()
    specs = [candidates[gid] for gid in selected_ids if gid in candidates]
    seasons = sorted({s["season"] for s in specs})
    frames = {}
    for season in seasons:
        loaded = load_season(root, season, commit)
        frames[season] = loaded["team_box"]

    outputs = {}
    rejected = []
    for spec in sorted(specs, key=lambda x: (x["date"], x["game_id"]), reverse=True):
        gid = spec["game_id"]
        try:
            frame = frames[spec["season"]]
            rows = frame.loc[frame["game_id"].astype(str).str.zfill(10) == gid].copy()
            if "season_type_id" in rows.columns:
                rows = rows.loc[rows["season_type_id"].astype(str) == "2"]
            if len(rows) != 2:
                raise ValueError(f"MIRROR_TEAM_BOX_EXPECTED_TWO_ROWS:{gid}:{len(rows)}")
            parsed = {}
            for _, row in rows.iterrows():
                team = str(row.get("team_tricode") or "")
                if not team:
                    raise ValueError(f"MIRROR_TEAM_BOX_TEAM_CODE_MISSING:{gid}")
                minutes = _parse_minutes(row.get("minutes"))
                if minutes < 239.0:
                    raise ValueError(f"MIRROR_TEAM_BOX_MINUTES_INVALID:{gid}:{team}:{minutes}")
                parsed[team] = {
                    "fgm": _to_int(row.get("field_goals_made")),
                    "fga": _to_int(row.get("field_goals_attempted")),
                    "fta": _to_int(row.get("free_throws_attempted")),
                    "orb": _to_int(row.get("rebounds_offensive")),
                    "drb": _to_int(row.get("rebounds_defensive")),
                    "tov": _to_int(row.get("turnovers")),
                    "ast": _to_int(row.get("assists")),
                    "blk": _to_int(row.get("blocks")),
                    "minutes": minutes,
                }
            if set(parsed) != {spec["home"], spec["away"]}:
                raise ValueError(
                    f"MIRROR_TEAM_BOX_SCHEDULE_CONFLICT:{gid}:{sorted(parsed)}:"
                    f"{spec['away']}@{spec['home']}"
                )
            doc_id = f"sdv_team_box:{commit}:{spec['season']}:{gid}"
            outputs["nba:" + gid] = {
                "event": {
                    "event_id": gid,
                    "date": spec["date"],
                    "home": spec["home"],
                    "away": spec["away"],
                },
                "boxes": parsed,
                "source_document": {
                    "id": doc_id,
                    "family": "NBA_STATS_TEAM_BOX_MIRROR",
                    "provider": "SportsDataverse NBA Stats mirror",
                    "upstream_commit": commit,
                },
                "authority": "SPORTSDATAVERSE_NBA_STATS_TEAM_BOX_MIRROR",
            }
        except Exception as exc:
            rejected.append({"game_id": gid, "reason": f"{type(exc).__name__}:{exc}"})

    counts = {
        team: sum(
            1 for item in outputs.values()
            if team in item["boxes"] and item["event"]["date"] < day
        )
        for team in wanted
    }
    return {
        "boxes": outputs,
        "counts": counts,
        "requested_team_games": {k: len(v) for k, v in per_team.items()},
        "rejected": rejected,
        "upstream_commit": commit,
        "source": "SPORTSDATAVERSE_NBA_STATS_TEAM_BOX_MIRROR",
    }


def history_context(player: str, game_specs: list[dict[str, Any]], cache_root: str | Path,
                    *, max_games: int = 12, commit: str | None = None) -> dict[str, Any]:
    """Build Stage 33-35 evidence from exact pre-cutoff game IDs in mirror data."""
    root = Path(cache_root)
    commit = commit or resolve_upstream_commit(root)
    specs = []
    seen = set()
    for spec in game_specs:
        gid = str(spec["game_id"]).zfill(10)
        if gid in seen:
            continue
        specs.append({"game_id": gid, "season": int(spec["season"])})
        seen.add(gid)
        if len(specs) >= max_games:
            break

    seasons = {s["season"] for s in specs}
    loaded = {season: load_season(root, season, commit) for season in seasons}

    result = {
        "player": player,
        "source": "SPORTSDATAVERSE_NBA_STATS_MIRROR",
        "upstream_repository": UPSTREAM_REPO,
        "upstream_commit": commit,
        "requested_games": len(specs),
        "games": [],
        "usable_games": 0,
        "full_games": 0,
        "fallback_games": 0,
        "quarantined_games": 0,
        "target": {},
        "teammates": {},
        "five_man_units": {},
        "stage_receipts": {},
        "independence_family": "LINEUP_PBP_CORRELATED_WITH_ROLE_OPPORTUNITY",
    }
    total_stats = {"pts": 0.0, "fga": 0.0, "fg3a": 0.0, "fta": 0.0,
                   "reb": 0.0, "ast": 0.0, "tov": 0.0}
    total_poss = 0
    total_minutes = 0.0
    closing_on = 0.0
    closing_eligible = 0.0
    teammate_acc = {}
    unit_acc = {}
    player_names = {}

    for spec in specs:
        gid = spec["game_id"]
        try:
            game = _game_frames(loaded[spec["season"]], gid)
            validation = validate_game(game)
            result["games"].append({
                "game_id": gid, "season": spec["season"],
                "quality": validation["quality"],
                "minute_error_pct": validation.get("minute_error_pct"),
                "null_lineup_rate": validation.get("null_lineup_rate"),
            })
            if validation["quality"] == "QUARANTINED":
                result["quarantined_games"] += 1
                continue
            target = _target_identity(game["player_box"], player)
            # Name map for teammate display.
            id_col = "person_id" if "person_id" in game["player_box"].columns else "player_id"
            for _, row in game["player_box"].iterrows():
                rid = _to_int(row.get(id_col), 0)
                if rid:
                    player_names[rid] = (
                        str(row.get("first_name") or "") + " " + str(row.get("family_name") or "")
                    ).strip() or str(rid)

            scoring = _game_scoring_context(game, target)
            lineup_minutes, close = _game_minutes_and_closing(game, target)
            official_row = game["player_box"].loc[
                pd.to_numeric(game["player_box"][id_col], errors="coerce").fillna(0).astype("int64") == target["player_id"]
            ].iloc[0]
            total_minutes += _parse_minutes(official_row.get("minutes"))
            total_poss += scoring["possessions"]
            _add_stats(total_stats, scoring["stats"])
            closing_on += close["closing_on"]
            closing_eligible += close["closing_eligible"]
            result["usable_games"] += 1
            result["full_games"] += int(validation["quality"] == "FULL")
            result["fallback_games"] += int(validation["quality"] == "FALLBACK")

            for mate, item in scoring["teammates"].items():
                acc = teammate_acc.setdefault(mate, {
                    "name": player_names.get(mate, str(mate)),
                    "possessions_with": 0,
                    "stats_with": {k: 0.0 for k in total_stats},
                })
                acc["possessions_with"] += item["possessions_with"]
                _add_stats(acc["stats_with"], item["stats_with"])

            for unit, item in scoring["units"].items():
                acc = unit_acc.setdefault(unit, {
                    "minutes": 0.0, "possessions": 0,
                    "stats": {k: 0.0 for k in total_stats},
                    "players": item["players"],
                })
                acc["possessions"] += item["possessions"]
                _add_stats(acc["stats"], item["stats"])
            for unit, minutes in lineup_minutes.items():
                if str(target["player_id"]) in unit.split("_"):
                    acc = unit_acc.setdefault(unit, {
                        "minutes": 0.0, "possessions": 0,
                        "stats": {k: 0.0 for k in total_stats},
                        "players": list(map(int, unit.split("_"))),
                    })
                    acc["minutes"] += minutes
        except Exception as exc:
            result["games"].append({
                "game_id": gid, "season": spec["season"], "quality": "FAILED",
                "reason": f"{type(exc).__name__}:{exc}",
            })

    result["target"] = {
        "minutes": round(total_minutes, 3),
        "possessions": total_poss,
        "stats": total_stats,
        "rates": _rate(total_stats, total_poss),
        "closing_share": closing_on / closing_eligible if closing_eligible else None,
        "closing_minutes_on": round(closing_on, 3),
        "closing_minutes_eligible": round(closing_eligible, 3),
    }

    for mate, acc in teammate_acc.items():
        without_poss = max(0, total_poss - acc["possessions_with"])
        without_stats = {k: total_stats[k] - acc["stats_with"][k] for k in total_stats}
        with_rate = _rate(acc["stats_with"], acc["possessions_with"])
        without_rate = _rate(without_stats, without_poss)
        out = {
            **acc,
            "with_rates": with_rate,
            "without_rates": without_rate,
            "ast_ratio_shrunk": None,
            "reb_ratio_shrunk": None,
        }
        # Only scoring/attempt metrics are supported by this mirror adapter
        # because v3 PBP has no dedicated assisting-player id.
        for stat in ("fga", "pts"):
            a = with_rate and with_rate.get(f"{stat}_per100")
            b = without_rate and without_rate.get(f"{stat}_per100")
            raw = a / b if a is not None and b not in (None, 0) else None
            weight = acc["possessions_with"] / (acc["possessions_with"] + 200.0) if acc["possessions_with"] else 0.0
            out[f"{stat}_ratio_shrunk"] = 1.0 + (raw - 1.0) * weight if raw is not None else None
        result["teammates"][str(mate)] = out

    result["five_man_units"] = {
        key: {
            "minutes": round(value["minutes"], 3),
            "possessions": value["possessions"],
            "players": [player_names.get(pid, str(pid)) for pid in value["players"]],
            "rates": _rate(value["stats"], value["possessions"]),
        }
        for key, value in sorted(unit_acc.items(), key=lambda kv: (kv[1]["possessions"], kv[1]["minutes"]), reverse=True)
    }

    if result["full_games"] >= 8 and total_poss >= 250:
        quality = "FULL"
    elif result["usable_games"] >= 3 and total_poss >= 75:
        quality = "FALLBACK"
    else:
        quality = "LIMITED"
    result["quality"] = quality
    result["stage_receipts"] = {
        "33": {
            "stage": "Teammate WOWY", "execution": "EXECUTED", "quality": quality,
            "source": "SportsDataverse NBA Stats possession mirror",
            "upstream_commit": commit, "games": result["usable_games"],
            "possessions": total_poss, "teammates": len(result["teammates"]),
            "assist_wowy": "LIMITED_NO_ASSISTING_PLAYER_ID_IN_V3_MIRROR",
        },
        "34": {
            "stage": "Five-Man Lineups", "execution": "EXECUTED", "quality": quality,
            "source": "SportsDataverse NBA Stats on-court lineups",
            "upstream_commit": commit, "games": result["usable_games"],
            "five_man_units": len(result["five_man_units"]),
        },
        "35": {
            "stage": "Closing Lineup", "execution": "EXECUTED",
            "quality": quality if closing_eligible else "LIMITED",
            "source": "SportsDataverse NBA Stats PBP + on-court lineups",
            "upstream_commit": commit,
            "competitive_closing_minutes": round(closing_eligible, 3),
            "closing_share": result["target"]["closing_share"],
        },
    }
    return result
