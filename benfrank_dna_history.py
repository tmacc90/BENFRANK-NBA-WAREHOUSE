"""Exact-line DNA over season-scoped observations; no L52 dependency.

All rates are descriptive. Career coverage always means the available archive
unless a provider independently certifies a complete career inventory.
"""
import datetime as dt
import itertools
import math
import statistics

from engine import stat

VERSION = 'NBA_DNA_SEASON_HIERARCHY_20261113_1'
MARKETS = ('points', 'rebounds', 'assists', 'pr', 'pa', 'ra', 'pra', 'fantasy_score')
ALIASES = {'points_rebounds': 'pr', 'points_assists': 'pa', 'rebounds_assists': 'ra',
           'pts+rebs': 'pr', 'pts+asts': 'pa', 'rebs+asts': 'ra', 'pts+rebs+asts': 'pra'}
SCORING = dict(pts=1.0, reb=1.2, ast=1.5, stl=3.0, blk=3.0, tov=-1.0)
SCORING_VERSION = 'PRIZEPICKS_NBA_PTS1_REB1.2_AST1.5_STL3_BLK3_TOV-1_VERIFIED_20261113'
SCORING_SOURCE = 'https://www.prizepicks.com/playbook-article/how-to-play-prizepicks-nba-fantasy-scoring-system'


def season_for_day(day):
    day = dt.date.fromisoformat(day)
    year = day.year if day.month >= 7 else day.year - 1
    return f'{year}-{str(year + 1)[-2:]}'


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total))/denominator
    width = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator
    return [max(0, center-width), min(1, center+width)]


def summarize(rows, market, line, requested=None, unavailable=None):
    market = ALIASES.get(market, market)
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise ValueError('FINITE_EXACT_LINE_REQUIRED')
    values, used, missing = [], [], []
    for row in rows:
        try:
            value = stat(row, market)
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError('NONFINITE_STAT')
            values.append(float(value)); used.append(row)
        except (KeyError, TypeError, ValueError):
            missing.append(row.get('game_id', row.get('date')))
    n = len(values)
    over = sum(v > line for v in values)
    under = sum(v < line for v in values)
    outcomes = ['OVER' if v > line else 'UNDER' if v < line else 'PUSH' for v in values]
    recent_side = outcomes[0] if outcomes else None
    recent_streak = len(list(next(itertools.groupby(outcomes))[1])) if outcomes else 0
    minutes = [r['minutes'] for r in used if isinstance(r.get('minutes'), (int, float))]
    opportunities = {}
    for key in ('fga', 'fta', 'fg3a', 'potential_assists', 'rebound_chances', 'touches'):
        measured = [r[key] for r in used if isinstance(r.get(key), (int, float)) and math.isfinite(r[key])]
        opportunities[key] = dict(n=len(measured), mean=statistics.mean(measured) if measured else None,
                                  kind='OBSERVED' if measured else 'UNAVAILABLE')
    return dict(status='LIMITED' if unavailable or not n or missing else 'FULL',
                availability='UNAVAILABLE' if unavailable else 'AVAILABLE' if n else 'NO_OBSERVATIONS',
                exact_reason=unavailable or ('MISSING_MARKET_COMPONENTS' if missing else None),
                requested=requested, n=n, over_count=over, under_count=under, push_count=n-over-under,
                over_rate=over/n if n else None, under_rate=under/n if n else None,
                over_pct=100*over/n if n else None, under_pct=100*under/n if n else None,
                mean=statistics.mean(values) if n else None,
                median=statistics.median(values) if n else None,
                stdev=statistics.stdev(values) if n > 1 else None,
                expected=statistics.mean(values) if n else None,
                historical_mean_minus_line=statistics.mean(values)-line if n else None,
                projection_minus_line=None, projection_kind='MODEL_PROJECTION_ATTACHED_AFTER_SIMULATION',
                streak=dict(side=recent_side, length=recent_streak, order='MOST_RECENT_FIRST'),
                minutes_avg=statistics.mean(minutes) if minutes else None,
                minutes_n=len(minutes), opportunities=opportunities,
                uncertainty=dict(over_wilson_95=wilson(over,n), under_wilson_95=wilson(under,n),
                                 reliability='THIN' if n < 15 else 'MODERATE' if n < 40 else 'LARGER_SAMPLE',
                                 limitation='Descriptive binomial interval; dependence and role changes can widen uncertainty'),
                game_ids=[r.get('game_id', r.get('date')) for r in used],
                excluded_missing_components=missing, historical_rate_is_simulation_probability=False)


def historical_windows(rows, market, line, day, opponent=None, expected_minutes=None, starter=None):
    """Current-season L5/L10/L15 never backfill from a previous season."""
    current = season_for_day(day)
    year = int(current[:4]); previous = f'{year-1}-{str(year)[-2:]}'
    ordered = sorted((dict(r) for r in rows if r['date'] < day),
                     key=lambda r: (r['date'], str(r.get('game_id', ''))), reverse=True)
    # Identical repeats are harmless; disagreeing duplicate identities are not.
    unique = {}
    for row in ordered:
        key = str(row.get('game_id') or (row['date'], row.get('team'), row.get('opponent')))
        if key in unique:
            fields = ('pts','reb','ast','stl','blk','tov','minutes','team','opponent','season')
            if any(unique[key].get(k) != row.get(k) for k in fields):
                raise ValueError('CONFLICTING_DUPLICATE_PLAYER_GAME:' + key)
            continue
        unique[key] = row
    ordered = list(unique.values())
    current_rows = [r for r in ordered if r.get('season') == current]
    previous_rows = [r for r in ordered if r.get('season') == previous]
    windows = {'current_season': summarize(current_rows,market,line)}
    for size in (5,10,15):
        available = len(current_rows) >= size
        windows[f'L{size}'] = summarize(current_rows[:size] if available else [],market,line,size,
            None if available else f'ONLY_{len(current_rows)}_CURRENT_SEASON_GAMES_NEED_{size}')
        windows[f'L{size}']['current_season_games_available'] = len(current_rows)
    windows['current_season_h2h'] = summarize([r for r in current_rows if r.get('opponent') == opponent],market,line,
        unavailable='UPCOMING_OPPONENT_NOT_SUPPLIED' if not opponent else None)
    windows['previous_season'] = summarize(previous_rows,market,line)
    windows['previous_season_h2h'] = summarize([r for r in previous_rows if r.get('opponent') == opponent],market,line,
        unavailable='UPCOMING_OPPONENT_NOT_SUPPLIED' if not opponent else None)
    windows['career_available'] = summarize(ordered,market,line)
    windows['career_available'].update(status='LIMITED', complete_career_verified=False,
        exact_reason='AVAILABLE_ARCHIVE_ONLY_COMPLETE_CAREER_INVENTORY_NOT_VERIFIED')
    comparable = [r for r in ordered if expected_minutes is not None and isinstance(r.get('minutes'),(int,float))
                  and abs(r['minutes'] - expected_minutes) <= max(4, .15*expected_minutes)
                  and (starter is None or r.get('starter') == starter)]
    windows['role_comparable'] = summarize(comparable,market,line,
        unavailable='UPCOMING_ROLE_MINUTES_NOT_SUPPLIED' if expected_minutes is None else None)
    windows['role_comparable']['matching_rule'] = 'Minutes within max(4,15% of projected minutes); starter state when observed'
    for window in windows.values():
        window.update(policy_version=VERSION, current_season=current, previous_season=previous,
                      asof_game_date_exclusive=day)
    return windows
