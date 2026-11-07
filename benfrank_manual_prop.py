"""No-subscription manual NBA prop route using ESPN's future schedule and depth charts.

The entered line is a tested hypothesis, never represented as a verified
PrizePicks or other sportsbook quote. Data collection is strictly pregame.
"""
import datetime as dt
import math
from acquire_history import name_key
from benfrank_auto_history import now, instant, sha
from benfrank_auto_context import schedule, capture_roles

MARKETS = frozenset(('points', 'rebounds', 'assists', 'threes', 'pra', 'pr',
                     'pa', 'ra', 'steals', 'blocks', 'turnovers', 'fantasy_score'))


def resolve_manual_forward_prop(store, config):
    """Return a one-prop board and verified schedule/identity context.

    Requires player, exact line and market from the user. Resolves the team from
    future ESPN NBA game depth charts, not from an unverified user assertion.
    Does NOT use the blocked PrizePicks discovery endpoint.
    """
    day = config['game_date']
    dt.date.fromisoformat(day)
    supplied = config.get('manual_prop')
    if not isinstance(supplied, dict):
        raise ValueError('MANUAL_PROP_REQUIRED_PLAYER_MARKET_LINE')
    player = supplied.get('player')
    market = supplied.get('market')
    line = supplied.get('line')
    if not isinstance(player, str) or not player.strip() or len(player) > 120:
        raise ValueError('MANUAL_PLAYER_REQUIRED')
    if not isinstance(market, str) or market not in MARKETS:
        raise ValueError('MANUAL_MARKET_UNSUPPORTED')
    if type(line) not in (float, int) or not math.isfinite(line) or not 0 <= line <= 10000:
        raise ValueError('MANUAL_FINITE_LINE_REQUIRED')

    games = schedule(store, day)
    current = instant(now())
    upcoming = [g for g in games if instant(g['tipoff_utc']) > current
                and g['status'].get('state') == 'pre']
    if not upcoming:
        raise ValueError('NO_UNSTARTED_NBA_GAMES_FOR_REQUESTED_SLATE')

    # User-provided team/opponent is a filter, never authoritative over ESPN.
    hinted_team = supplied.get('team')
    hinted_opponent = supplied.get('opponent')
    if hinted_team:
        if not isinstance(hinted_team, str):
            raise ValueError('INVALID_MANUAL_TEAM_FILTER')
        upcoming = [g for g in upcoming if hinted_team in (g['home'], g['away'])]
    if hinted_opponent:
        if not isinstance(hinted_opponent, str):
            raise ValueError('INVALID_MANUAL_OPPONENT_FILTER')
        upcoming = [g for g in upcoming if hinted_opponent in (g['home'], g['away'])]
    if not upcoming:
        raise ValueError('NO_FUTURE_SCHEDULE_MATCH_FOR_TEAM_HINTS')

    lookup_teams = sorted({team for g in upcoming for team in ('home', 'away')
                           for team in (g[team],)})
    sources, injury, identities = capture_roles(store, lookup_teams, day)
    matches = []
    for game in upcoming:
        for team, opponent in ((game['home'], game['away']), (game['away'], game['home'])):
            matching = [p for p in sources['depths'].get(team, {}).get('players', {}).values()
                        if name_key(p['player']) == name_key(player)]
            for observed in matching:
                matches.append((game, team, opponent, observed))
    if len(matches) != 1:
        raise ValueError('MANUAL_PLAYER_NOT_UNIQUELY_RESOLVED_FROM_FUTURE_DEPTH_CHARTS:'
                         + str(len(matches)))
    game, team, opponent, observed = matches[0]
    capture_utc = now()
    raw = {'player': player.strip(), 'market': market, 'line': line,
           'team_hint': hinted_team, 'opponent_hint': hinted_opponent,
           'game_date': day}
    source_hash = sha(raw)
    prop = dict(
        player=observed['player'], market=market, line=line,
        team=team, opponent=opponent, game_date=day,
        tipoff_utc=game['tipoff_utc'], game_id=game['game_id'],
        espn_event_id=game['espn_event_id'],
        espn_player_id=observed['id'], platform='USER_MANUAL',
        source_url='USER_ENTERED_IN_WORKFLOW',
        source_document='MANUAL_INPUT:' + source_hash,
        source_sha256=source_hash,
        line_capture_utc=capture_utc,
        native_platform_line_capture_utc=None,
        line_authority='USER_ENTERED_NOT_INDEPENDENTLY_PLATFORM_VERIFIED',
        snapshot_id='manual_' + sha([source_hash, game['game_id'], capture_utc])[:24])
    discovery = dict(games=games, selected=1, eligible=1,
        source_route='MANUAL_LINE_ESPN_VERIFIED_SCHEDULE_AND_PLAYER',
        line_authority=prop['line_authority'],
        warning='Entered line is not a verified quote from a sportsbook or PrizePicks.',
        schedule_source=game['source_document'])
    return [prop], discovery, (sources, injury, identities)
