"""Synthetic software contracts. No fixture trial is historical NBA evidence."""
import copy
import datetime as dt
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_v44_twon import fixture
from benfrank_v44_twon import prepare_game,simulate_game
from benfrank_v47_availability import parse_pdf,observation,UNKNOWN
from benfrank_v47_model import availability_probability,rotation_scenarios,trial_run
from benfrank_v47_uncertainty import fit,apply,finite_quantile,wilson
from benfrank_v47_board import cohort
from benfrank_v47_run import run


def context_fixture():
    c=fixture();c.update(game_id='fixture-game',pace_sd=3,input_mode='EXPLICIT_SYNTHETIC_TEST')
    for roster in c['rosters'].values():
        for p in roster:
            p.update(minutes_mean=p['minutes_target'],historical_minutes=[max(1,p['minutes_target']-3),p['minutes_target'],p['minutes_target']+3],
                     probability_played=1,availability_status=UNKNOWN,
                     shooting_beta={k:[p[k]*100,(1-p[k])*100] for k in ('fg2_pct','fg3_pct','ft_pct')})
    return c


def development_rows(n=50):
    return [{'game_id':'fixture-'+str(i),'partition':'DEVELOPMENT','platform':'PrizePicks','market':'points','line':26.5,
             'tipoff_utc':(dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(days=i)).isoformat(),
             'mean':26.0,'q05':20.,'q95':32.,'actual':27. if i%2 else 25.,'p_over_raw':.3 if i%2 else .7,
             'over_result':i%2} for i in range(n)]


class RotationRepairTests(unittest.TestCase):
    def test_out_players_never_enter_scenario_or_substitution_rosters(self):
        c=context_fixture();out=c['rosters'][c['home']][0]['player']
        c['rosters'][c['home']][0].update(availability_status='Out',probability_played=1)
        scenarios,_=rotation_scenarios(c,16,42)
        for scenario,prepared in scenarios:
            self.assertNotIn(out,{p['player'] for p in scenario['rosters'][c['home']]})
            game=simulate_game(scenario,42,prepared=prepared,max_overtimes=12,max_shooting_sequences=32)
            self.assertNotIn(out,game['stats'])
            self.assertEqual(game['regulation_team_minutes'],{c['home']:240,c['away']:240})

    def test_scenarios_vary_minutes_and_conserve_each_team(self):
        scenarios,_=rotation_scenarios(context_fixture(),24,87)
        allocations=set()
        for scenario,_ in scenarios:
            for roster in scenario['rosters'].values():
                self.assertEqual(sum(p['minutes_target'] for p in roster),240)
                self.assertTrue(all(0<=p['minutes_target']<=48 for p in roster))
                allocations.add(tuple(p['minutes_target'] for p in roster))
        self.assertGreater(len(allocations),1)

    def test_unlisted_is_unknown_even_with_high_learned_play_probability(self):
        model={'counts':{UNKNOWN+'|CORE':[98,100]}}
        self.assertLess(availability_probability(model,UNKNOWN,'CORE'),1)
        self.assertEqual(availability_probability(model,'Out','CORE'),0)

    def test_missing_probability_prior_is_explicitly_blocked(self):
        with self.assertRaisesRegex(ValueError,'DEVELOPMENT_AVAILABILITY_PRIOR'):
            availability_probability({'counts':{}},UNKNOWN,'CORE')

    def test_voids_are_never_under_wins_and_counts_sum_to_trials(self):
        c=context_fixture();player=c['rosters'][c['home']][0]['player']
        fake={'score_tied_after_overtime_limit':False,'shot_sequence_ceiling_hit':False,
              'regulation_team_minutes':{c['home']:240,c['away']:240},'stats':{},'overtime_periods':0}
        with patch('benfrank_v47_model.rotation_scenarios',return_value=([(c,{})],0)),patch('benfrank_v47_model.simulate_game',return_value=fake):
            r=trial_run(c,player,'points',26.5,25000)
        self.assertEqual(r['void_count'],25000)
        self.assertEqual(r['under_count'],0)
        self.assertIsNone(r['p_over_raw'])
        self.assertIsNone(r['mean'])
        self.assertEqual(sum(r[k] for k in ('over_count','under_count','push_count','void_count')),25000)
        self.assertEqual(r['ticket_authority'],'NO_TICKET')

    def test_incomplete_overtime_cannot_claim_completed_trials(self):
        c=context_fixture();player=c['rosters'][c['home']][0]['player']
        with patch('benfrank_v47_model.rotation_scenarios',return_value=([(c,{})],0)),patch('benfrank_v47_model.simulate_game',return_value={'score_tied_after_overtime_limit':True}):
            with self.assertRaisesRegex(ValueError,'TAIL_GUARD'):
                trial_run(c,player,'points',26.5,25000)

    def test_cache_for_different_context_is_rejected(self):
        c=fixture();prepared=prepare_game(c)
        with self.assertRaisesRegex(ValueError,'different context'):
            simulate_game(copy.deepcopy(c),42,prepared=prepared)


class UncertaintyRepairTests(unittest.TestCase):
    def test_finite_sample_quantile_uses_conservative_order_statistic(self):
        self.assertEqual(finite_quantile(list(range(10))),9)
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_FINITE_SAMPLE'):
            finite_quantile(list(range(8)))

    def test_parameter_fit_and_conformal_calibration_games_are_disjoint(self):
        model=fit(development_rows())
        self.assertEqual(len(model['parameter_fit_games']),30)
        self.assertEqual(model['conformal_calibration_n'],20)
        self.assertFalse(set(model['parameter_fit_games'])&set(model['conformal_calibration_games']))

    def test_conformal_labels_cannot_reestimate_probability_or_bias_parameters(self):
        rows=development_rows();before=fit(rows)
        for row in rows[30:]:row['actual']+=100;row['over_result']=1
        after=fit(rows)
        for key in ('bias_points','isotonic_bins','probability_prior','probability_shrink_weight'):
            self.assertEqual(before[key],after[key])
        self.assertGreater(after['conformal_radius'],before['conformal_radius'])

    def test_new_test_outcomes_cannot_fit_any_calibration(self):
        rows=development_rows();rows[-1]['partition']='NEW_TEST'
        with self.assertRaisesRegex(ValueError,'NEW_TEST_OUTCOMES'):
            fit(rows)

    def test_market_and_line_bands_cannot_be_pooled(self):
        for key,value in (('market','assists'),('platform','OtherPlatform'),('line',31.5)):
            rows=development_rows();rows[-1][key]=value
            with self.assertRaisesRegex(ValueError,'ONE_PLATFORM_MARKET'):
                fit(rows)

    def test_scoped_monotone_probability_calibration(self):
        model=fit(development_rows())
        row={**development_rows(1)[0],'game_id':'new-fixture','tipoff_utc':'2026-10-20T23:00:00+00:00'}
        probabilities=[apply({**row,'p_over_raw':i/100},model)['p_over_calibrated'] for i in range(101)]
        self.assertEqual(probabilities,sorted(probabilities))
        self.assertTrue(all(0<p<1 for p in probabilities))
        with self.assertRaisesRegex(ValueError,'SCOPE_MISMATCH'):
            apply({**row,'market':'rebounds'},model)

    def test_reusing_development_or_earlier_game_is_rejected(self):
        rows=development_rows();model=fit(rows)
        with self.assertRaisesRegex(ValueError,'NOT_A_NEW_TEST'):
            apply(rows[0],model)
        with self.assertRaisesRegex(ValueError,'MUST_PRECEDE'):
            apply({**rows[0],'game_id':'new-fixture'},model)

    def test_binomial_coverage_reports_uncertainty(self):
        low,high=wilson(9,10)
        self.assertLess(low,.9);self.assertGreater(high,.9)


class OfficialPdfTableTests(unittest.TestCase):
    def test_second_page_uses_physical_columns_and_retains_game_context(self):
        columns={'GameDate':23,'GameTime':119,'Matchup':199,'Team':264,'PlayerName':424,'CurrentStatus':585,'Reason':666}
        def word(text,x,top):return {'text':text,'x0':x,'top':top}
        class Page:
            width=842;height=595
            def __init__(self,n,words):self.page_number=n;self.words=words
            def extract_words(self,**kwargs):return self.words
        heading=[word(k,x,107) for k,x in columns.items()]
        first=heading+[word('02/01/2026',24,130),word('NYK@BOS',200,130),word('BostonCeltics',265,130),
                       word('First,Fixture',425,130),word('Out',586,130),word('Injury',667,130),word('Page1of2',400,565)]
        second=[word('Second,Fixture',425,82),word('Questionable',586,82),word('Illness',667,82),word('Page2of2',400,565)]
        class Document:
            pages=[Page(1,first),Page(2,second)]
            def __enter__(self):return self
            def __exit__(self,*args):return False
        with patch('pdfplumber.open',return_value=Document()),patch('subprocess.run') as proc:
            proc.return_value.stdout='Injury Report: 02/01/26 06:00 AM'
            result=parse_pdf('synthetic-fixture.pdf','2026-02-01T11:00:00Z','2026-02-01T12:00:00Z')
        self.assertEqual(result['issues'],[])
        self.assertEqual(observation(result,'2026-02-01','BOS','NYK','BOS','Fixture Second')['status'],'Questionable')
        self.assertEqual(observation(result,'2026-02-01','BOS','NYK','BOS','Unlisted Fixture')['status'],UNKNOWN)
        self.assertEqual(observation(result,'2026-02-02','BOS','NYK','BOS','Fixture Second')['status'],UNKNOWN)


class CohortAndEntryPointTests(unittest.TestCase):
    def test_cohort_does_not_inspect_outcomes_and_selects_one_per_game(self):
        base={'game_id':'fixture','game_date':'2026-10-20','tipoff_utc':'2026-10-20T23:00:00Z','market':'points','line':26.5,'captured_at':'2026-10-20T12:00:00Z'}
        rows=[{**base,'snapshot_id':'b','player':'Zed Fixture','actual':999},
              {**base,'snapshot_id':'a','player':'Adam Fixture','actual':0}]
        self.assertEqual(cohort(rows,'2026-10-20','2026-10-28')[0]['player'],'Adam Fixture')
        for r in rows:r['actual']=100-r['actual']
        self.assertEqual(cohort(rows,'2026-10-20','2026-10-28')[0]['player'],'Adam Fixture')

    def test_entrypoint_retains_no_ticket_for_void_distribution(self):
        with patch('benfrank_v47_run.trial_run',return_value={'p_over_raw':None}):
            r=run({'game_id':'fixture'},'Fixture Player','points',26.5,'PrizePicks')
        self.assertEqual(r['status'],'BLOCKED_NO_CONDITIONAL_PLAYED_DISTRIBUTION')
        self.assertEqual(r['ticket_authority'],'NO_TICKET')


if __name__=='__main__':unittest.main()
