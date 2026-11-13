"""Contract tests; invented fixture records never count as forward calibration."""
import copy
import datetime as dt
import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benfrank_dna_history import historical_windows, MARKETS
from benfrank_dna_error import assess, load_forward
from benfrank_dna_intake import ocr_screenshots, resolve_batch
from benfrank_auto_history import Store, download
from engine import stat


def records():
    rows=[]
    for season,year,n in [('2026-27',2026,11),('2025-26',2025,20)]:
        for index in range(n):
            rows.append(dict(player='Example Player',date=f'{year}-10-{index+1:02d}',season=season,
                game_id=f'{year}-{index}',team='BOS',opponent='NYK' if index%2==0 else 'MIA',
                home=1,starter=1,minutes=30,pts=20+index%3,reb=6,ast=4,stl=1,blk=1,tov=2,fg3m=2,fga=15))
    return rows


class DnaHistoryTests(unittest.TestCase):
    def test_eleven_current_games_never_backfill_recent_windows(self):
        w=historical_windows(records(),'points',20.5,'2026-11-13','NYK')
        self.assertEqual(w['current_season']['n'],11)
        self.assertEqual(w['L5']['n'],5);self.assertEqual(w['L10']['n'],10)
        self.assertEqual(w['L15']['n'],0);self.assertEqual(w['L15']['availability'],'UNAVAILABLE')
        self.assertNotIn('L52',w)
        self.assertTrue(all(str(g).startswith('2026-') for g in w['L10']['game_ids']))

    def test_previous_h2h_career_and_reliability(self):
        w=historical_windows(records(),'points',21,'2026-11-13','NYK',30)
        self.assertEqual(w['previous_season']['n'],20)
        self.assertEqual(w['current_season_h2h']['n'],6)
        self.assertEqual(w['previous_season_h2h']['n'],10)
        self.assertEqual(w['career_available']['n'],31)
        self.assertFalse(w['career_available']['complete_career_verified'])
        self.assertEqual(w['role_comparable']['n'],31)
        self.assertEqual(w['current_season']['minutes_avg'],30)
        self.assertEqual(w['current_season']['opportunities']['fga']['mean'],15)
        self.assertIsNotNone(w['current_season']['uncertainty']['over_wilson_95'])

    def test_all_eight_categories_same_records_exact_line_and_push(self):
        r=records()[0]
        expected=dict(points=20,rebounds=6,assists=4,pr=26,pa=24,ra=10,pra=30,fantasy_score=37.2)
        self.assertEqual(set(expected),set(MARKETS))
        for market,value in expected.items():
            with self.subTest(market=market):
                self.assertEqual(stat(r,market),value)
                w=historical_windows([r],market,value,'2026-11-13','NYK')['current_season']
                self.assertEqual((w['over_count'],w['under_count'],w['push_count']),(0,0,1))

    def test_future_games_excluded_duplicate_conflicts_rejected(self):
        rows=records();future=dict(rows[0],date='2026-11-13',game_id='target',pts=999)
        self.assertEqual(historical_windows(rows+[future],'points',20.5,'2026-11-13')['current_season']['n'],11)
        self.assertEqual(historical_windows(rows+[rows[0]],'points',20.5,'2026-11-13')['current_season']['n'],11)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_DUPLICATE'):
            historical_windows(rows+[dict(rows[0],pts=30)],'points',20.5,'2026-11-13')

    def test_nonfinite_lines_rejected_missing_stats_not_zero(self):
        with self.assertRaisesRegex(ValueError,'FINITE'):
            historical_windows(records(),'points',float('nan'),'2026-11-13')
        row=dict(records()[0],ast=None)
        w=historical_windows([row],'pra',20.5,'2026-11-13')['current_season']
        self.assertEqual(w['n'],0);self.assertTrue(w['excluded_missing_components'])


class NumericalTests(unittest.TestCase):
    def test_25000_actual_trials_and_all_stress_shapes(self):
        from test_v52_early import fixture
        from benfrank_v52_early import early_context,simulate,stress
        from benfrank_auto_evidence import sensitivity, verify_trace
        p,c,s,i,cut=fixture();ctx=early_context(c,p,s,{},i,cut)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'main.jsonl.gz'
            result=simulate(ctx,p['player'],'points',20.5,25000,44,trace_path=path)
            self.assertEqual(result['trials_executed'],25000)
            self.assertEqual(sum(result[k] for k in ('over_count','under_count','push_count','void_count')),25000)
            self.assertTrue(verify_trace(path,result,20.5)['verified'])
            self.assertEqual(len(list(gzip.open(path,'rt'))),25000)
            with self.assertRaises(FileExistsError):simulate(ctx,p['player'],'points',20.5,25000,44,trace_path=path)
            ladder=sensitivity(result,20.5)['ladder']
            self.assertTrue({19.5,20,20.5,21,21.5}.issubset({x['line'] for x in ladder}))
        for kind in ('FOUL_TROUBLE','BLOWOUT_MINUTES','INJURY_LIMITED_OPPORTUNITY'):
            modified=stress(ctx,p['player'],'OVER',kind)
            before=next(x for rs in ctx['rosters'].values() for x in rs if x['player']==p['player'])
            after=next(x for rs in modified['rosters'].values() for x in rs if x['player']==p['player'])
            self.assertLess(after['minutes_mean'],before['minutes_mean'])

    def test_missing_error_cohort_is_uncalibrated_no_complement(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=assess(Path(tmp)/'absent.sqlite',dict(analysis_cutoff_utc='2026-11-13T20:00Z'))
            self.assertEqual(r['calibration_status'],'UNCALIBRATED')
            self.assertIsNone(r['estimated_error_probability'])
            self.assertEqual(r['eligible_frozen_settled_n'],0)

    def test_missing_injury_and_lineup_keep_unknown(self):
        from test_v52_early import fixture
        from benfrank_v52_early import early_context
        p,c,s,i,cut=fixture();i.update(teams={},sha256=None,authority='UNAVAILABLE')
        ctx=early_context(c,p,s,{},i,cut)
        self.assertEqual(ctx['rosters']['BOS'][0]['availability_status'],'UNKNOWN_NOT_CLEARED')
        self.assertFalse(ctx['official_final_starters_confirmed'])


class IntakeTests(unittest.TestCase):
    def test_two_screenshots_all_eight_categories_one_extraction(self):
        from PIL import Image,ImageDraw,ImageFont
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',28)
        labels=['Points','Rebounds','Assists','Pts+Rebs','Pts+Asts','Rebs+Asts','PRA','Fantasy Score']
        paths=[];names=[]
        with tempfile.TemporaryDirectory() as tmp:
            for page in range(2):
                im=Image.new('RGB',(1000,850),'white');draw=ImageDraw.Draw(im)
                for j in range(4):
                    name=['Example Alpha','Example Bravo','Example Charlie','Example Delta','Example Echo','Example Foxtrot','Example Golf','Example Hotel'][page*4+j]
                    names.append(name);x=30+(j%2)*500;y=30+(j//2)*400
                    draw.text((x,y),name,fill='black',font=font)
                    draw.text((x,y+50),'BOS vs NYK',fill='black',font=font)
                    draw.text((x,y+110),f'{j+1}.5 '+labels[page*4+j],fill='black',font=font)
                file=Path(tmp)/f'fixture_{page}.png';im.save(file);paths.append(str(file))
            r=ocr_screenshots(paths,names)
            self.assertEqual(len(r['props']),8,r)
            self.assertEqual({p['market'] for p in r['props']},set(MARKETS))
            self.assertEqual(len(r['screenshots']),2)

    def test_unreadable_screenshot_is_not_fabricated(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'empty.png';Image.new('RGB',(300,300),'white').save(path)
            r=ocr_screenshots([path],['Example Player'])
            self.assertFalse(r['props']);self.assertTrue(r['rejected'])


class ResilienceTests(unittest.TestCase):
    def test_outage_retains_append_only_checkpoint_and_final_failure_receipt(self):
        from benfrank_auto_runner import run
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);config=tmp/'request.json'
            config.write_text(json.dumps(dict(mode='future_discovery',game_date='2031-01-01')))
            with patch('benfrank_auto_runner.discover',side_effect=ValueError('TEST_PROVIDER_OUTAGE')):
                result,code=run(config,tmp/'run',tmp/'state')
            self.assertEqual(code,2)
            snapshots=list((tmp/'run'/'checkpoints').glob('*.json'))
            self.assertEqual(len(snapshots),1)
            checkpoint=json.loads(snapshots[0].read_text())
            self.assertEqual(checkpoint['stages'][0]['status'],'BLOCKED')
            self.assertTrue((tmp/'run'/'execution_receipt.json').is_file())
            self.assertIn('TEST_PROVIDER_OUTAGE',result['fatal_blocker'])

    def test_new_config_does_not_invalidate_preservation_of_originals(self):
        from benfrank_auto_runner import preservation_check
        self.assertTrue(preservation_check({'original':'abc'},{'original':'abc','new_config':'def'})['verified'])
        self.assertFalse(preservation_check({'original':'abc'},{'original':'CHANGED'})['verified'])

    def test_negative_sensitivity_offsets_are_retained_as_theoretical(self):
        from benfrank_auto_evidence import sensitivity
        result=sensitivity(dict(histogram={'0':1,'1':3},void_count=0),.5)
        at={r['line']:r for r in result['ladder']}
        self.assertIn(-.5,at);self.assertTrue(at[-.5]['theoretical_negative_threshold'])

    def test_career_aggregate_has_means_but_no_invented_hit_rates(self):
        from benfrank_dna_sources import career_baselines
        labels=['GP','PTS','REB','AST','STL','BLK','TO']
        doc=dict(categories=[dict(name='averages',labels=labels,totals=['100','20','6','4','1','1','2'],statistics=[]),
                             dict(name='totals',labels=labels[1:],totals=['2000','600','400','100','100','200'],statistics=[])])
        class FakeStore:
            def many(self,jobs,workers):return {'1':(json.dumps(doc).encode(),dict(retrieved_utc='2026-11-13T20:00Z',id='doc',sha256='a'*64))}
        result=career_baselines(FakeStore(),[dict(player='Example Player',espn_player_id='1')],'2026-11-13')['Example Player']
        self.assertEqual(result['career_games'],100)
        self.assertEqual(result['career_means']['pra'],30)
        self.assertEqual(result['career_means']['fantasy_score'],37.2)
        self.assertFalse(result['exact_line_coverage_available_from_aggregate'])

    def test_zero_minute_bench_row_does_not_discard_verified_team_totals(self):
        from benfrank_auto_context import acquire_recent_boxes
        comp=dict(date='2026-11-12T00:00:00Z',status={'period':4},competitors=[
            dict(homeAway='home',team={'abbreviation':'BOS'},score='10'),
            dict(homeAway='away',team={'abbreviation':'NYK'},score='10')])
        values={'fieldGoalsMade-fieldGoalsAttempted':'5-10','freeThrowsMade-freeThrowsAttempted':'0-0',
                'threePointFieldGoalsMade-threePointFieldGoalsAttempted':'0-0','offensiveRebounds':'2',
                'defensiveRebounds':'4','turnovers':'2','assists':'3','blocks':'1'}
        doc=dict(header=dict(competitions=[comp],season={'type':2}),boxscore=dict(
            teams=[dict(team={'abbreviation':t},statistics=[dict(name=k,displayValue=v) for k,v in values.items()]) for t in ('BOS','NYK')],
            players=[dict(team={'abbreviation':'BOS'},statistics=[dict(labels=['MIN'],athletes=[
                dict(athlete={'id':'1','displayName':'Zero Reserve'},stats=['0'])])])]))
        meta=dict(id='fixture',url='https://site.api.espn.com/fixture')
        class FakeStore:
            db=type('DB',(),{'commit':lambda s:None,'rollback':lambda s:None})()
            def cached(self,url):return json.dumps(doc).encode(),meta
            def many(self,jobs):return {}
            def ingest(self,r,m):
                if r['minutes']<=0:raise ValueError('INVALID_PLAYED_MINUTES')
            def failure(self,*args):raise AssertionError(args)
        row=dict(player='Zero Reserve',team='BOS',opponent='NYK',home=1,date='2026-11-11',minutes=0,
                 pts=0,reb=0,ast=0,stl=0,blk=0,tov=0,source_game_ids={'ESPN':['123']})
        with patch('benfrank_auto_context.verify_completed_summary'),patch('benfrank_auto_context.rows_from_summary',return_value=[row]):
            result=acquire_recent_boxes(FakeStore(),[row],['BOS'],'2026-11-13')
        self.assertEqual(set(result['123']['boxes']),{'BOS','NYK'})

    def test_missing_injury_feed_preserves_depth_and_unknown_status(self):
        from benfrank_auto_context import capture_roles
        class FakeStore:
            def fetch(self,url,family):
                if url.endswith('injuries'):raise ValueError('INJURY_OUTAGE')
                return b'{}',dict(retrieved_utc='2026-11-13T20:00:00Z',sha256='a'*64,id='doc',url=url)
            def many(self,jobs):return {}
        with patch('benfrank_v51_rosters.list_teams',return_value={'1':'BOS'}):
            sources,injury,ids=capture_roles(FakeStore(),['BOS'],'2026-11-13')
        self.assertEqual(injury['authority'],'UNAVAILABLE')
        self.assertEqual(injury['unlisted_status'],'UNKNOWN_NOT_CLEARED')

    def test_current_source_denial_is_not_retried_or_bypassed(self):
        import urllib.error
        from email.message import Message
        error=urllib.error.HTTPError('https://www.basketball-reference.com',403,'Forbidden',Message(),None)
        with patch('urllib.request.urlopen',side_effect=error) as call:
            with self.assertRaises(urllib.error.HTTPError):download('https://www.basketball-reference.com')
        self.assertEqual(call.call_count,1)

    def test_transient_source_outage_retries_then_succeeds(self):
        class Response:
            status=200
            def geturl(self):return 'https://site.api.espn.com/retry-test'
            def read(self,n):return b'{}'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('urllib.request.urlopen',side_effect=[TimeoutError('outage'),Response()]) as call,patch('time.sleep'):
            self.assertEqual(download('https://site.api.espn.com/retry-test'),b'{}')
            self.assertEqual(call.call_count,2)

    def test_qualification_does_not_invent_a_primary(self):
        from benfrank_dna_qualification import rank
        self.assertIsNone(rank([{'ticket_qualification':{'qualified':False}}])['primary'])
