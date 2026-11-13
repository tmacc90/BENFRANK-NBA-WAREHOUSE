"""Free supplementary sources, with retained bytes and explicit limitations."""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlencode

from benfrank_auto_history import now, instant
from benfrank_v52_sources import PROJECTED, parse_projected
from benfrank_dna_history import season_for_day, SCORING


def career_baselines(store, board, day):
    """Career totals/appearances provide means, never exact-line hit counts."""
    from benfrank_dna_history import MARKETS
    from engine import stat
    targets={p['espn_player_id']:p['player'] for p in board if p.get('espn_player_id')}
    jobs={pid:('https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/'+pid+'/stats?seasontype=2','ESPN_CAREER_STATS') for pid in targets}
    captures=store.many(jobs,workers=3);results={}
    for pid,name in targets.items():
        url=jobs[pid][0]
        try:
            raw,meta=captures[pid];doc=json.loads(raw)
            categories={c['name']:c for c in doc['categories']}
            for category in categories.values():
                if any(int(r['season']['year'])>int(season_for_day(day)[:4])+1 for r in category['statistics']):
                    raise ValueError('CAREER_AGGREGATE_CONTAINS_FUTURE_SEASON')
            avg=dict(zip(categories['averages']['labels'],categories['averages']['totals']))
            total=dict(zip(categories['totals']['labels'],categories['totals']['totals']))
            n=int(avg['GP'])
            if n<=0:raise ValueError('NO_VERIFIED_CAREER_APPEARANCES')
            components={out:float(total[key]) for out,key in (('pts','PTS'),('reb','REB'),('ast','AST'),('stl','STL'),('blk','BLK'),('tov','TO'))}
            means={m:(sum(components[k]*w for k,w in SCORING.items()) if m=='fantasy_score' else stat(components,m))/n for m in MARKETS}
            results[name]=dict(status='FULL',source=url,timestamp=meta['retrieved_utc'],source_document=meta['id'],
                source_sha256=meta['sha256'],espn_player_id=pid,career_games=n,career_means=means,
                exact_line_coverage_available_from_aggregate=False,
                limitation='Full-career means from regular-season totals; exact-line counts require individual game logs',
                used_in_simulation=False)
        except Exception as error:
            results[name]=dict(status='LIMITED',source=url,timestamp=now(),exact_reason=str(error),
                limitation='Available verified game-log career archive remains usable; no full-career mean invented')
    return results


def official_injury(store, teams, day):
    from benfrank_v46_official_injuries import report_times, report_url
    from benfrank_v47_availability import parse_pdf
    failures = []
    for stamp in report_times(now()):
        url = report_url(stamp.isoformat())
        try:
            raw, meta = store.fetch(url, 'NBA_OFFICIAL_INJURY_PDF')
            if not raw.startswith(b'%PDF-'):
                raise ValueError('ORIGINAL_PDF_REQUIRED')
            parsed = parse_pdf(store.root/meta['file'], stamp.isoformat(), now())
            groups = [g for g in parsed['game_team_reports'].values()
                      if g['game_date'] == day and g['team'] in teams]
            if not groups:
                raise ValueError('TARGET_GAME_DATE_TEAMS_ABSENT_FROM_REPORT')
            return dict(teams={g['team']:g['players'] for g in groups}, printed_at=stamp.isoformat(),
                        retrieved_at=meta['retrieved_utc'], sha256=meta['sha256'], url=url,
                        authority='ORIGINAL_NBA_INJURY_PDF', unlisted_status='UNKNOWN_NOT_CLEARED',
                        source_document=meta['id'], issues=parsed['issues'],
                        team_submission={g['team']:g['submission_status'] for g in groups},
                        status='LIMITED' if parsed['issues'] or len(groups)<len(teams) else 'FULL',
                        failures=failures)
        except Exception as error:
            store.failure(url,error); failures.append(dict(url=url,reason=str(error)))
    raise ValueError('OFFICIAL_INJURY_UNAVAILABLE:'+json.dumps(failures))


def supplement_roles(store, sources, secondary, teams, day):
    """Official availability has priority; disagreement is retained, never merged silently."""
    try:
        official = official_injury(store, teams, day)
        official['secondary_source'] = secondary
        disagreements = []
        for team, entries in official['teams'].items():
            for key, row in entries.items():
                other = secondary.get('teams',{}).get(team,{}).get(key)
                if other and row['status'] != other['status']:
                    disagreements.append(dict(team=team,player=row['player'],official=row['status'],
                                              secondary=other['status'],resolution='OFFICIAL_PRIORITY_WITH_DISAGREEMENT'))
        official['source_disagreements'] = disagreements
        injury = official
    except Exception as error:
        injury = dict(secondary, status='FALLBACK' if secondary.get('sha256') else 'LIMITED',
                      official_blocker=str(error))
    try:
        raw,meta=store.fetch(PROJECTED,'ROTOWIRE_PUBLIC_PROJECTED')
        projected=parse_projected(raw.decode('utf8'),day)
        sources['projected']={k:v for k,v in projected.items() if k in teams}
        sources['projected_source']=dict(url=PROJECTED,captured_at=meta['retrieved_utc'],
            sha256=meta['sha256'],source_document=meta['id'],authority='PUBLIC_EXPECTED_FIVE_NOT_CONFIRMED')
        sources['projected_status']='FULL' if all(t in sources['projected'] for t in teams) else 'LIMITED'
    except Exception as error:
        store.failure(PROJECTED,error)
        sources['projected_status']='FALLBACK' if sources.get('depths') else 'BLOCKED'
        sources.setdefault('failures',[]).append(dict(source=PROJECTED,reason=str(error),
            alternative='ESPN published depth order; projected roles, not confirmed starters'))
    return sources,injury


def supplementary(store, day, target_names):
    """Capture measured opportunities when obtainable. No guessed tracking fields."""
    season=season_for_day(day)
    end=(dt.date.fromisoformat(day)-dt.timedelta(days=1)).strftime('%m/%d/%Y')
    query=dict(LeagueID='00',Season=season,SeasonType='Regular Season',PerMode='PerGame',
               DateFrom='',DateTo=end,LastNGames='0',Month='0',OpponentTeamID='0',TeamID='0')
    jobs={kind:('https://stats.nba.com/stats/leaguedashptstats?'+urlencode(dict(query,PtMeasureType=kind)),
                'NBA_TRACKING_DIRECT') for kind in ('Possessions','Passing','Rebounding')}
    jobs['pbp_players']=('https://api.pbpstats.com/get-totals/nba?'+urlencode(dict(
        Season=season,SeasonType='Regular Season',Type='Player',ToDate=day)), 'PBP_STATS')
    # Small parallel batch; each failed optional source is independent.
    results=store.many(jobs,workers=4)
    output={}
    for name,(url,family) in jobs.items():
        if name not in results:
            output[name]=dict(status='BLOCKED',source=url,timestamp=now(),
                exact_reason='SOURCE_FETCH_FAILED_SEE_APPEND_ONLY_FAILURE_MANIFEST',
                limitation='No measured tracking inserted into model')
            continue
        raw,meta=results[name]
        try:
            doc=json.loads(raw)
            if name=='pbp_players':
                rows=doc['multi_row_table_data']
                # Aggregate endpoint date filters are not independently documented here.
                # Capture as context; never join unverified as-of aggregate fields to a forecast.
                selected=[r for r in rows if r.get('Name') in target_names]
                output[name]=dict(status='LIMITED',source=url,timestamp=meta['retrieved_utc'],
                    source_document=meta['id'],rows=selected,raw_rows=len(rows),used_in_model=False,
                    limitation='Season aggregate captured; ToDate semantics and possession-level WOWY/closing lineups not verified')
            else:
                sets=doc.get('resultSets',[])
                if not sets:raise ValueError('NBA_TRACKING_SCHEMA_EMPTY')
                rows=[dict(zip(rs['headers'],r)) for rs in sets for r in rs['rowSet']]
                selected=[r for r in rows if r.get('PLAYER_NAME') in target_names]
                output[name]=dict(status='LIMITED',source=url,timestamp=meta['retrieved_utc'],
                    source_document=meta['id'],rows=selected,raw_rows=len(rows),used_in_model=False,
                    limitation='Captured contextual tracking; player-ID/as-of game granularity must be verified before model use')
        except Exception as error:
            store.failure(url,error)
            output[name]=dict(status='BLOCKED',source=url,timestamp=now(),exact_reason=str(error),
                              limitation='Optional source failed; observed boxes remain available')
    return output
