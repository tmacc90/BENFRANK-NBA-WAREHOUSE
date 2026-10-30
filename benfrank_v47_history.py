"""Immutable historical feature store for availability-aware model reconstruction.

New ESPN season rows retain secondary-source assurance. No warehouse rows or
verification receipts are changed or invented. Target-game stats are never features.
"""
import collections
import csv
import datetime as dt
import json
import math
import statistics
from pathlib import Path

from acquire_history import name_key, team_key, normalize_espn, verification_relation
from benfrank_v45_evidence import readonly, archive_minutes, digest
from benfrank_v47_availability import observation, UNKNOWN


class History:
    def __init__(self, warehouse, shots, schedule=None, current_csv=None, crosswalks='identity_crosswalks.json'):
        self.aliases = {}
        self.known_names = {}
        if Path(crosswalks).is_file():
            for e in json.loads(Path(crosswalks).read_text())['entries']:
                self.aliases[name_key(e['archived_nba_name'])] = e['canonical_name']
        self.games, self.shots, self.schedule, self.boxes = [], {}, {}, collections.defaultdict(collections.Counter)
        self.source_hashes = {'warehouse':digest(warehouse),'shooting_database':digest(shots)}
        conn = readonly(warehouse)
        try:
            relation = verification_relation(conn)
            for r in conn.execute('SELECT g.*,v.nba_game_id FROM games g JOIN '+relation+' v USING(player,date,team)'):
                row = dict(r); row['player'] = self.canonical(row['player']); row['source_tier']='SAVED_VERIFIED_NBA_HISTORY'
                self.games.append(row)
                self.known_names[name_key(row['player'])]=row['player']
            for r in conn.execute("SELECT payload_json FROM source_records WHERE file_sha256 IN (SELECT sha256 FROM source_files WHERE name='nba_stats_schedule_master.parquet')"):
                g=json.loads(r[0]);self.schedule[str(g['game_id'])]=g
            for r in conn.execute("SELECT payload_json FROM source_records WHERE file_sha256 IN (SELECT sha256 FROM source_files WHERE name LIKE 'player_boxscores_%.parquet')"):
                raw=json.loads(r[0])
                if not raw.get('minutes'):
                    continue
                minutes=archive_minutes(raw['minutes'])
                if minutes<=0:
                    continue
                box=self.boxes[(str(raw['game_id']),team_key(raw['team_tricode']))]
                box['minutes']+=minutes
                for k,field in (('fgm','field_goals_made'),('fga','field_goals_attempted'),('fta','free_throws_attempted'),
                    ('orb','rebounds_offensive'),('drb','rebounds_defensive'),('tov','turnovers'),('ast','assists'),('blk','blocks')):
                    if raw[field] is None:raise ValueError('MISSING_PRIOR_OFFICIAL_TEAM_STAT')
                    box[k]+=raw[field]
        finally:conn.close()
        conn=readonly(shots)
        try:
            for r in conn.execute('SELECT * FROM verified_shooting'):
                row=dict(r);row['player']=self.canonical(row['player'])
                self.shots[(name_key(row['player']),row['game_date'],row['team'])]=row
        finally:conn.close()
        if schedule:
            import pyarrow.parquet as pq
            self.source_hashes['schedule']=digest(schedule)
            for g in pq.read_table(schedule).to_pylist():self.schedule[str(g['game_id'])]=g
        self.schedule_keys=collections.defaultdict(list)
        for gid,g in self.schedule.items():
            if str(g.get('season_type_id'))=='2':
                self.schedule_keys[(str(g['game_date_est'])[:10],team_key(g['home_team_tricode']),team_key(g['away_team_tricode']))].append(gid)
        self.current_rejections=[]
        if current_csv:
            self.source_hashes['current_espn_csv']=digest(current_csv)
            with Path(current_csv).open() as f:raws=list(csv.DictReader(f))
            current_boxes=collections.defaultdict(collections.Counter)
            for raw in raws:
                try:
                    row,why=normalize_espn(raw,int(raw['season']))
                    if why:continue
                    home,away=(row['team'],row['opponent']) if row['home'] else (row['opponent'],row['team'])
                    gids=self.schedule_keys[(row['date'],home,away)]
                    if len(gids)!=1:raise ValueError('NO_UNIQUE_OFFICIAL_SCHEDULE_IDENTITY')
                    row['nba_game_id']=gids[0];row['player']=self.canonical(row['player'])
                    row['source_tier']='ESPN_SECONDARY_WITH_OFFICIAL_SCHEDULE_IDENTITY'
                    shot={k:int(raw[field]) for k,field in (('fgm','field_goals_made'),('fga','field_goals_attempted'),
                        ('fg3m','three_point_field_goals_made'),('fg3a','three_point_field_goals_attempted'),('ftm','free_throws_made'),('fta','free_throws_attempted'))}
                    shot.update(fg2m=shot['fgm']-shot['fg3m'],fg2a=shot['fga']-shot['fg3a'])
                    if (2*shot['fg2m']+3*shot['fg3m']+shot['ftm']!=row['pts'] or
                            any(shot[m]>shot[a] for m,a in (('fgm','fga'),('fg3m','fg3a'),('ftm','fta'),('fg2m','fg2a')))):
                        raise ValueError('CURRENT_SHOOTING_CONSERVATION_CONFLICT')
                    self.games.append(row)
                    self.known_names[name_key(row['player'])]=row['player']
                    self.shots[(name_key(row['player']),row['date'],row['team'])]=shot
                    box=current_boxes[(gids[0],row['team'])];box['minutes']+=row['minutes']
                    for k,field in (('fgm','field_goals_made'),('fga','field_goals_attempted'),('fta','free_throws_attempted'),
                        ('orb','offensive_rebounds'),('drb','defensive_rebounds'),('tov','turnovers'),('ast','assists'),('blk','blocks')):
                        box[k]+=float(raw[field])
                except (ValueError,KeyError,TypeError) as exc:
                    self.current_rejections.append({'player':raw.get('athlete_display_name'),'date':raw.get('game_date'),'reason':str(exc)})
            self.boxes.update(current_boxes)
        self.games.sort(key=lambda r:(r['date'],r['team'],r['player']))
        self.by_player=collections.defaultdict(list);self.by_team=collections.defaultdict(list);self.actual={}
        for r in self.games:
            self.by_player[name_key(r['player'])].append(r);self.by_team[r['team']].append(r)
            self.actual[(name_key(r['player']),r['date'],r['team'])]=r
        self._league={}

    def canonical(self, name):
        name=self.aliases.get(name_key(name),name.strip())
        return self.known_names.get(name_key(name),name)

    def prior(self,player,through,limit=32):
        return [r for r in reversed(self.by_player[name_key(self.canonical(player))]) if r['date']<=through and r['minutes']>0][:limit]

    def league_prior(self,start_year):
        if start_year in self._league:return self._league[start_year]
        low,high=f'{start_year-1}-07-01',f'{start_year}-07-01'
        paired=[(r,self.shots[(name_key(r['player']),r['date'],r['team'])]) for r in self.games
            if low<=r['date']<high and r['minutes']>0 and (name_key(r['player']),r['date'],r['team']) in self.shots]
        if len(paired)<100:raise ValueError('VERIFIED_PREVIOUS_SEASON_LEAGUE_PRIOR_REQUIRED')
        mins=sum(r['minutes'] for r,_ in paired)
        s={k:sum(shot[k] for _,shot in paired) for k in ('fg2m','fg2a','fg3m','fg3a','ftm','fta')}
        result={k:s[k]*36/mins for k in ('fg2a','fg3a','fta')}
        result.update({k:sum(r[k] for r,_ in paired)*36/mins for k in ('ast','reb','stl','blk','tov')})
        result.update(fg2_pct=s['fg2m']/s['fg2a'],fg3_pct=s['fg3m']/s['fg3a'],ft_pct=s['ftm']/s['fta'])
        self._league[start_year]=result
        return result

    def profile(self,player,through,start_year):
        prior=self.prior(player,through)
        paired=[(r,self.shots[(name_key(r['player']),r['date'],r['team'])]) for r in prior
                if (name_key(r['player']),r['date'],r['team']) in self.shots]
        league=self.league_prior(start_year)
        mins=sum(r['minutes'] for r,_ in paired);exposure=144
        totals={k:sum(s[k] for _,s in paired) for k in ('fg2m','fg2a','fg3m','fg3a','ftm','fta')}
        rates={out:(totals[key]+league[key]*exposure/36)*36/(mins+exposure)
               for out,key in (('fg2a_per36','fg2a'),('fg3a_per36','fg3a'),('fta_per36','fta'))}
        rates.update({out:(sum(r[key] for r,_ in paired)+league[key]*exposure/36)*36/(mins+exposure)
             for out,key in (('ast_per36','ast'),('reb_per36','reb'),('stl_per36','stl'),('blk_per36','blk'),('tov_per36','tov'))})
        beta={}
        for out,made,attempt in (('fg2_pct','fg2m','fg2a'),('fg3_pct','fg3m','fg3a'),('ft_pct','ftm','fta')):
            a=totals[made]+25*league[out];b=totals[attempt]-totals[made]+25*(1-league[out])
            rates[out]=a/(a+b);beta[out]=[a,b]
        history_minutes=[r['minutes'] for r in prior[:12]]
        mean=(.6*statistics.median(history_minutes[:5])+.4*statistics.mean(history_minutes)) if history_minutes else 12.0
        return {**rates,'player':self.canonical(player),'minutes_target':0,'minutes_mean':min(42,max(2,mean)),
                'historical_minutes':history_minutes,'shooting_beta':beta,'observed_profile_games':len(paired),
                'minutes_source':'PRIOR_PLAYED_GAME_MINUTES' if history_minutes else 'UNVALIDATED_ROOKIE_12_MINUTE_MODEL_PRIOR_BLOCKS_FULL',
                'max_feature_game_date':max((r['date'] for r in prior),default=None),
                'source':'PAST_GAME_RATES_SHRUNK_TO_OBSERVED_PREVIOUS_SEASON_LEAGUE_PRIOR',
                'asof':through+'T23:59:59+00:00'}

    def team_rates(self,team,through):
        games={r['nba_game_id']:(r['date'],r['opponent']) for r in self.by_team[team] if r['date']<=through}
        selected=sorted(games,key=lambda gid:games[gid][0],reverse=True)[:5]
        if len(selected)<5:raise ValueError('FIVE_SOURCE_BACKED_PRIOR_TEAM_GAMES_REQUIRED')
        own,other=collections.Counter(),collections.Counter();paces=[]
        for gid in selected:
            a,b=self.boxes[(gid,team)],self.boxes[(gid,games[gid][1])]
            if min(a['minutes'],b['minutes'])<235:raise ValueError('INCOMPLETE_PRIOR_TEAM_MINUTES')
            own.update(a);other.update(b)
            for box in (a,b):paces.append((box['fga']+.44*box['fta']-box['orb']+box['tov'])*240/box['minutes'])
        poss=own['fga']+.44*own['fta']-own['orb']+own['tov']
        rates={'off_reb_probability':own['orb']/(own['orb']+other['drb']),
               'assist_probability':own['ast']/own['fgm'],'block_on_missed_fg_probability':own['blk']/(other['fga']-other['fgm']),
               'shooting_foul_probability':own['fta']/(2*poss),'source':'PRIOR_OBSERVED_TEAM_BOX_COUNTS',
               'asof':through+'T23:59:59+00:00'}
        return rates,statistics.mean(paces),statistics.stdev(paces),[games[g][0] for g in selected]


def offered_roster(document,snapshot,team):
    from zoneinfo import ZoneInfo
    names=set()
    for p in document.get('props',[]):
        try:
            date=dt.datetime.fromisoformat(p['startTimeIso'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
            if p.get('sport')=='NBA' and team_key(p['teamCode'])==team and date==snapshot['game_date'] and team_key(p['opponentCode']) in (snapshot['team'],snapshot['opponent']):
                names.add(p['player'])
        except (KeyError,ValueError,TypeError):continue
    return names
