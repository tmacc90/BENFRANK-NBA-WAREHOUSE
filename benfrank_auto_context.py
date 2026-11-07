"""Connect reconciled observations to the existing v4.7/v5.2 profile contract."""
import collections
import datetime as dt
import json
import statistics

from acquire_history import name_key, team_key
from benfrank_auto_history import BASE, PP, ET, now, sha, instant, season_for_date
from benfrank_v47_history import History
from benfrank_v52_sources import parse_depth, secondary_injury_snapshot
from benfrank_v52_early import projected_five, season_start
from benfrank_v46_reconstructed_replay import allocate_minutes
from benfrank_v44_twon import validate
from benfrank_v51_espn_game_details import verify_completed_summary
from espn_live_stage import rows_from_summary

PP_MARKETS = {'Points': 'points', 'Rebounds': 'rebounds', 'Assists': 'assists',
              '3-PT Made': 'threes', 'Pts+Rebs+Asts': 'pra', 'Pts+Rebs': 'pr',
              'Pts+Asts': 'pa', 'Rebs+Asts': 'ra', 'Steals': 'steals',
              'Blocked Shots': 'blocks', 'Turnovers': 'turnovers', 'Fantasy Score': 'fantasy_score'}


def schedule(store, day):
    raw, meta = store.fetch(BASE + 'scoreboard?dates=' + day.replace('-', ''), 'ESPN')
    games = []
    for event in json.loads(raw).get('events', []):
        if str(event.get('season', {}).get('type')) != '2':
            continue
        if instant(event['date']).astimezone(ET).date().isoformat() != day:
            raise ValueError('SCHEDULE_GAME_DATE_CONFLICT')
        comps = event.get('competitions', [])
        if len(comps) != 1:
            continue
        sides = {c['homeAway']: team_key(c['team']['abbreviation']) for c in comps[0]['competitors']}
        games.append(dict(game_id='espn:' + str(event['id']), espn_event_id=str(event['id']),
                          game_date=day, tipoff_utc=event['date'], home=sides['home'], away=sides['away'],
                          source_document=meta, status=event['status']['type']))
    return games


def discover(store, day, max_props=6, max_games=3):
    games = schedule(store, day)
    raw, meta = store.fetch(PP, 'PRIZEPICKS_NATIVE_PUBLIC')
    data = json.loads(raw)
    included = {(x['type'], str(x['id'])): x for x in data.get('included', [])}
    candidates, rejected = [], collections.Counter()
    clock = instant(meta['retrieved_utc'])
    for projection in data.get('data', []):
        try:
            a = projection['attributes']
            if (a.get('odds_type') != 'standard' or a.get('status') != 'pre_game'
                    or a.get('is_live') or a.get('is_promo') or a.get('in_game')):
                continue
            market = PP_MARKETS.get(a['stat_type'])
            if not market:
                continue
            # Over-only demon and under-only promotional offerings are excluded.
            if a.get('allowed_wager_types') in ('over', 'under'):
                continue
            player_ref = projection['relationships']['new_player']['data']
            player = included[(player_ref['type'], str(player_ref['id']))]['attributes']
            if player.get('combo') or player.get('league') != 'NBA':
                continue
            team, opponent = team_key(player['team']), team_key(a['description'])
            matches = [g for g in games if {g['home'], g['away']} == {team, opponent}
                       and abs((instant(g['tipoff_utc']) - instant(a['start_time'])).total_seconds()) <= 60
                       and instant(g['tipoff_utc']) > clock and g['status'].get('state') == 'pre']
            if len(matches) != 1:
                rejected['NO_UNIQUE_FUTURE_SCHEDULE_MATCH'] += 1
                continue
            game = matches[0]
            prop = dict(player=player['name'], market=market, line=a['line_score'], team=team,
                        opponent=opponent, game_date=day, tipoff_utc=game['tipoff_utc'],
                        game_id=game['game_id'], espn_event_id=game['espn_event_id'], platform='PrizePicks',
                        line_capture_utc=meta['retrieved_utc'], native_platform_line_capture_utc=meta['retrieved_utc'],
                        source_url=meta['url'], source_document=meta['id'], source_sha256=meta['sha256'],
                        native_projection_id=projection['id'], source_updated_utc=a.get('updated_at'),
                        line_authority='PUBLIC_NATIVE_PRIZEPICKS_RESPONSE', odds_type=a['odds_type'],
                        snapshot_id='auto_' + sha([projection['id'], a['line_score'], meta['id']])[:24])
            if prop['source_updated_utc'] and instant(prop['source_updated_utc']) > clock:
                raise ValueError('PROP_SOURCE_CLOCK_AFTER_CAPTURE')
            candidates.append(prop)
        except (KeyError, TypeError, ValueError) as error:
            rejected[str(error)] += 1
    # Predeclared research sampling: earliest games, points then other markets,
    # one exact line per player, at most two players in each game. No model ranking.
    preference = ['points', 'rebounds', 'assists', 'threes', 'pra', 'pr', 'pa', 'ra',
                  'steals', 'blocks', 'turnovers', 'fantasy_score']
    candidates.sort(key=lambda p: (instant(p['tipoff_utc']), preference.index(p['market']),
                                   name_key(p['player']), str(p['native_projection_id'])))
    selected, by_game, names = [], collections.Counter(), set()
    for p in candidates:
        if p['game_id'] not in by_game and len(by_game) >= max_games:
            continue
        if by_game[p['game_id']] >= 2 or name_key(p['player']) in names:
            continue
        selected.append(p); names.add(name_key(p['player'])); by_game[p['game_id']] += 1
        if len(selected) >= max_props:
            break
    return selected, dict(source=meta, eligible=len(candidates), selected=len(selected),
                          rejected=dict(rejected), sampling='EARLIEST_GAMES_TWO_DISTINCT_PLAYERS_POINTS_PRIORITY',
                          games=games)


def capture_roles(store, teams, day):
    index_raw, index_meta = store.fetch(BASE + 'teams', 'ESPN')
    from benfrank_v51_rosters import list_teams
    lookup = {team_key(code): pid for pid, code in list_teams(json.loads(index_raw)).items()}
    jobs = {code: (BASE + 'teams/' + lookup[code] + '/depthcharts', 'ESPN') for code in teams}
    depths, identities, failures = {}, {}, []
    for code, (raw, meta) in store.many(jobs).items():
        try:
            depth = parse_depth(json.loads(raw), code, meta['retrieved_utc'])
            depth.update(url=meta['url'], sha256=meta['sha256'], source_document=meta['id'])
            depths[code] = depth
            for p in depth['players'].values():
                if p['id'] in identities and name_key(identities[p['id']]) != name_key(p['player']):
                    raise ValueError('ONE_ESPN_ID_MULTIPLE_NAMES')
                identities[p['id']] = p['player']
        except Exception as error:
            store.failure(meta['url'], error); failures.append(dict(team=code, reason=str(error)))
    raw, meta = store.fetch(BASE + 'injuries', 'ESPN')
    injury = secondary_injury_snapshot(json.loads(raw), json.loads(index_raw), meta['retrieved_utc'], meta['sha256'])
    injury['source_document'] = meta['id']
    sources = dict(version='AUTO_V52_DEPTH_CAPTURE_1', game_date=day, captured_at=now(), depths=depths,
                   projected={}, projected_source=None, failures=failures,
                   final_starters_required_for_early_forecast=False)
    return sources, injury, identities


def acquire_recent_boxes(store, records, teams, day):
    """Fetch five complete past team boxes for pace/defense and stat crosschecks."""
    events = {}
    for team in teams:
        options = {}
        for row in records:
            ids = row.get('source_game_ids', {}).get('ESPN', [])
            if row['team'] == team and row['date'] < day and len(ids) == 1:
                options[ids[0]] = row
        for eid, row in sorted(options.items(), key=lambda pair: pair[1]['date'], reverse=True)[:5]:
            home, away = (row['team'], row['opponent']) if row['home'] else (row['opponent'], row['team'])
            events[eid] = dict(event_id=eid, date=row['date'], home=home, away=away)
    outputs = {}
    jobs = {eid: (BASE + 'summary?event=' + eid, 'ESPN') for eid in events}
    responses = {eid: cached for eid, (url, _) in jobs.items() if (cached := store.cached(url)) is not None}
    responses.update(store.many({k: v for k, v in jobs.items() if k not in responses}))
    for eid, (raw, meta) in responses.items():
        try:
            doc = json.loads(raw); event = events[eid]
            comp = doc['header']['competitions'][0]
            literal = {c['homeAway']: c['team']['abbreviation'] for c in comp['competitors']}
            if any(team_key(literal[side]) != event[side] for side in ('home', 'away')):
                raise ValueError('CANONICAL_SUMMARY_SCHEDULE_TEAM_CONFLICT')
            # The legacy parser compares ESPN's literal NO/GS/NY abbreviations;
            # canonicalize only after checking and parsing the source document.
            verify_completed_summary(doc, dict(event, **literal))
            if str(doc['header']['season']['type']) != '2':
                raise ValueError('NON_REGULAR_SEASON_SUMMARY')
            rows = rows_from_summary(eid, event['date'], literal['home'], literal['away'], doc)
            stamp = comp['date']
            # Bind every summary athlete ID to its actual row, never by row order.
            players = {}
            for group in doc['boxscore']['players']:
                team = team_key(group['team']['abbreviation'])
                for category in group.get('statistics', []):
                    labels = category.get('labels', [])
                    for a in category.get('athletes', []):
                        athlete = a['athlete']; numbers = a.get('stats', [])
                        players[(team, name_key(athlete['displayName']))] = (athlete['id'], dict(zip(labels, numbers)))
            for r in rows:
                pid, values = players[(team_key(r['team']), name_key(r['player']))]
                r.update(team=team_key(r['team']), opponent=team_key(r['opponent']),
                         source_player_id=str(pid), tipoff_utc=stamp, minutes_precision='rounded_minutes', completed=True)
                if all(k in values for k in ('OREB', 'DREB')):
                    r.update(oreb=int(values['OREB']), dreb=int(values['DREB']))
                store.ingest(r, meta)
            store.db.commit()
            parsed = {}
            period = int(comp['status'].get('period', 4))
            for group in doc['boxscore']['teams']:
                values = {s['name']: s['displayValue'] for s in group['statistics']}
                fgm, fga = map(int, values['fieldGoalsMade-fieldGoalsAttempted'].split('-'))
                ftm, fta = map(int, values['freeThrowsMade-freeThrowsAttempted'].split('-'))
                fg3m, _ = map(int, values['threePointFieldGoalsMade-threePointFieldGoalsAttempted'].split('-'))
                team = team_key(group['team']['abbreviation'])
                score = next(int(c['score']) for c in comp['competitors'] if team_key(c['team']['abbreviation']) == team)
                if 2 * fgm + fg3m + ftm != score:
                    raise ValueError('TEAM_SHOOTING_SCORE_CONFLICT')
                parsed[team] = dict(fgm=fgm, fga=fga, fta=fta,
                                   orb=int(values['offensiveRebounds']), drb=int(values['defensiveRebounds']),
                                   tov=int(values['turnovers']), ast=int(values['assists']), blk=int(values['blocks']),
                                   minutes=240 + 25 * max(0, period - 4))
            outputs[eid] = dict(event=event, boxes=parsed, source_document=meta)
        except Exception as error:
            store.db.rollback(); store.failure(meta['url'], error)
    return outputs


class ProfileHistory(History):
    """Reuse governing profile math over a new reconciled read model."""
    def __init__(self, records, boxes):
        self.aliases, self.known_names, self.shots, self._league = {}, {}, {}, {}
        self.games = sorted(records, key=lambda r: (r['date'], r['team'], r['player']))
        self.by_player, self.by_team = collections.defaultdict(list), collections.defaultdict(list)
        self.boxes = collections.defaultdict(collections.Counter)
        for r in self.games:
            self.known_names[name_key(r['player'])] = r['player']
            self.by_player[name_key(r['player'])].append(r)
            self.by_team[r['team']].append(r)
            if all(r.get(k) is not None for k in ('fg2m', 'fg2a', 'fg3m', 'fg3a', 'ftm', 'fta')):
                self.shots[(name_key(r['player']), r['date'], r['team'])] = r
        for eid, item in boxes.items():
            for team, values in item['boxes'].items():
                self.boxes[(eid, team)] = values

    def rates_from_boxes(self, team, boxes, through):
        selected = sorted((x for x in boxes.values() if team in x['boxes'] and x['event']['date'] <= through),
                          key=lambda x: x['event']['date'], reverse=True)[:5]
        if len(selected) < 5:
            raise ValueError('FIVE_COMPLETE_PRIOR_TEAM_BOXES_REQUIRED:' + team)
        own, other, paces = collections.Counter(), collections.Counter(), []
        for item in selected:
            a = item['boxes'][team]
            b = next(v for key, v in item['boxes'].items() if key != team)
            own.update(a); other.update(b)
            paces.extend((box['fga'] + .44 * box['fta'] - box['orb'] + box['tov']) * 240 / box['minutes']
                         for box in (a, b))
        poss = own['fga'] + .44 * own['fta'] - own['orb'] + own['tov']
        def ratio(a, b):
            if b <= 0 or not 0 <= a / b <= 1:
                raise ValueError('INVALID_OBSERVED_TEAM_RATE:' + team)
            return a / b
        rates = dict(off_reb_probability=ratio(own['orb'], own['orb'] + other['drb']),
                     assist_probability=ratio(own['ast'], own['fgm']),
                     block_on_missed_fg_probability=ratio(own['blk'], other['fga'] - other['fgm']),
                     shooting_foul_probability=ratio(own['fta'], 2 * poss),
                     source='ESPN_COMPLETED_PRIOR_TEAM_BOX_COUNTS', asof=through + 'T23:59:59+00:00',
                     source_documents=[x['source_document']['id'] for x in selected])
        return rates, statistics.mean(paces), max(1, statistics.stdev(paces)), [x['event']['date'] for x in selected]


def build_context(prop, game, sources, history, boxes, cutoff, injury=None):
    through = (dt.date.fromisoformat(prop['game_date']) - dt.timedelta(days=1)).isoformat()
    derived_asof = min(instant(through + 'T23:59:59+00:00'), instant(cutoff)).isoformat()
    rosters, team_rates, paces, sds, feature_dates = {}, {}, [], [], []
    for team in (game['home'], game['away']):
        depth = sources['depths'][team]
        profiles = []
        for item in depth['players'].values():
            p = history.profile(item['player'], through, season_start(prop['game_date']))
            p['asof'] = derived_asof
            p.update(espn_player_id=item['id'], roster_source=depth['url'],
                     roster_source_sha256=depth['sha256'], probability_played=.8,
                     availability_status='UNKNOWN_NOT_CLEARED')
            profiles.append(p)
        out = {key for key, obs in (injury or {}).get('teams', {}).get(team, {}).items()
               if obs.get('status') == 'Out'}
        required = set(map(name_key, projected_five(depth, out)))
        required.update(map(name_key, projected_five(depth, set())))
        if team == prop['team']:
            required.add(name_key(prop['player']))
        profiles.sort(key=lambda p: (name_key(p['player']) in required, p['minutes_mean'], p['player']), reverse=True)
        profiles = profiles[:15]
        if not required.issubset({name_key(p['player']) for p in profiles}):
            raise ValueError('PROJECTED_TARGET_OR_STARTER_MISSING_FROM_PROFILE')
        targets = allocate_minutes({p['player']: p['minutes_mean'] for p in profiles})
        for p in profiles:
            p['minutes_target'] = targets[p['player']]
            feature_dates.extend([p['max_feature_game_date']] if p['max_feature_game_date'] else [])
        rosters[team] = profiles
        rates, pace, sd, dates = history.rates_from_boxes(team, boxes, through)
        rates['asof'] = derived_asof
        team_rates[team] = rates; paces.append(pace); sds.append(sd); feature_dates.extend(dates)
    if not feature_dates:
        raise ValueError('NO_OBSERVED_PROFILE_DATES')
    context = dict(game_id=prop['game_id'], game_date=prop['game_date'], tipoff_utc=prop['tipoff_utc'],
                   home=game['home'], away=game['away'], rosters=rosters, team_rates=team_rates,
                   pace_per_team=max(75, min(125, statistics.mean(paces))), pace_sd=statistics.mean(sds),
                   pace_source='OBSERVED_PAST_TEAM_BOX_POSSESSION_ESTIMATOR', pace_asof=derived_asof,
                   max_feature_game_date=max(feature_dates), constructed_at=now(), analysis_cutoff_utc=cutoff,
                   scoring_contract='PTS1_REB1.2_AST1.5_STL3_BLK3_TOV-1',
                   profile_builder='EXISTING_V47_HISTORY_PROFILE_MATH_FEEDING_V52_EARLY_CONTEXT',
                   source_correction_vintage_verified=False)
    validate(context)
    return context
