"""Software contracts only; fixture games never certify prediction accuracy."""
import copy
import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from test_v47_model_repair import context_fixture
from acquire_history import name_key
from engine import connect,FIELDS
from benfrank_v52_sources import parse_depth,parse_projected,secondary_injury_snapshot
from benfrank_v52_early import early_context,check_sources,scenarios,simulate,season_start,resolve_projected_names
from benfrank_v52_blind import payload
from benfrank_v52_ledger import record_prediction,connect as ledger_connect,scorecard

def fixture():
    c=context_fixture();c['max_feature_game_date']='2026-10-28'
    for rs in c['rosters'].values():
        for p in rs:p.update(observed_profile_games=3,minutes_source='SYNTHETIC_SOFTWARE_FIXTURE',roster_source='FIXTURE')
    p={'snapshot_id':'fixture-only','player':'BOS Player 0','market':'points','line':20.5,'team':'BOS','opponent':'NYK',
       'game_date':c['game_date'],'game_id':'fixture-game','tipoff_utc':c['tipoff_utc']}
    s={'game_date':c['game_date'],'depths':{},'projected':{},'projected_source':None}
    for team,rs in c['rosters'].items():
        names=[p['player'] for p in rs]
        s['depths'][team]={'positions':{pos:names[i:]+names[:i] for i,pos in enumerate(('PG','SG','SF','PF','C'))},
            'players':{name_key(n):{'ranks':{'PG':i+1}} for i,n in enumerate(names)},'captured_at':'2026-10-29T13:00:00Z','sha256':'a'*64}
    injury={'teams':{},'printed_at':'2026-10-29T12:00:00Z','retrieved_at':'2026-10-29T13:00:00Z','sha256':'b'*64}
    return p,c,s,injury,'2026-10-29T14:00:00Z'

class EarlyInputTests(unittest.TestCase):
    def test_no_final_starters_field_is_required(self):
        p,c,s,i,cut=fixture();check_sources(p,c,s,cut)
        ctx=early_context(c,p,s,{},i,cut)
        self.assertFalse(ctx['final_starters_required'])
        self.assertEqual(ctx['rosters']['BOS'][0]['availability_status'],'UNKNOWN_NOT_CLEARED')
        self.assertFalse(ctx['official_final_starters_confirmed'])
    def test_future_source_is_rejected(self):
        p,c,s,i,cut=fixture();s['depths']['BOS']['captured_at']='2026-10-29T16:00:00Z'
        with self.assertRaisesRegex(ValueError,'FUTURE_DEPTH'):check_sources(p,c,s,cut)
    def test_target_result_leak_is_rejected(self):
        p,c,s,i,cut=fixture();c['max_feature_game_date']=p['game_date']
        with self.assertRaisesRegex(ValueError,'TARGET_OR_FUTURE'):check_sources(p,c,s,cut)
    def test_wrong_game_or_tipoff_is_rejected(self):
        p,c,s,i,cut=fixture();p['game_id']='other'
        with self.assertRaisesRegex(ValueError,'GAME_ID_CONFLICT'):check_sources(p,c,s,cut)
        p['game_id']='fixture-game';p['tipoff_utc']='2026-10-29T22:00:00Z'
        with self.assertRaisesRegex(ValueError,'TIPOFF_CONFLICT'):check_sources(p,c,s,cut)
    def test_zero_history_prior_is_labeled_without_invented_logs(self):
        p,c,s,i,cut=fixture();reserve=c['rosters']['BOS'][-1]
        reserve.update(observed_profile_games=0,historical_minutes=[])
        ctx=early_context(c,p,s,{},i,cut);r=ctx['rosters']['BOS'][-1]
        self.assertEqual(r['observed_profile_games'],0);self.assertEqual(r['historical_minutes'],[])
        self.assertIn('PEER_PRIOR',r['profile_kind']);self.assertTrue(r['source_peer_players'])
        self.assertEqual(sum(x['minutes_target'] for x in ctx['rosters']['BOS']),240)
    def test_fresh_out_removes_player_from_every_rotation(self):
        p,c,s,i,cut=fixture();name='BOS Player 7'
        i['teams']={'BOS':{name_key(name):{'status':'Out'}}}
        ctx=early_context(c,p,s,{},i,cut)
        for scene,_ in scenarios(ctx,12,count=8):
            self.assertNotIn(name,{x['player'] for x in scene['rosters']['BOS']})
            self.assertEqual(sum(x['minutes_target'] for x in scene['rosters']['BOS']),240)
    def test_new_available_status_is_not_stuck_on_old_out(self):
        p,c,s,i,cut=fixture();c['rosters']['BOS'][7].update(availability_status='Out',probability_played=0)
        i['teams']={'BOS':{name_key('BOS Player 7'):{'status':'Available'}}}
        ctx=early_context(c,p,s,{},i,cut)
        self.assertGreater(ctx['rosters']['BOS'][7]['probability_played'],0)
    def test_complete_game_counts_include_void_separately(self):
        p,c,s,i,cut=fixture();ctx=early_context(c,p,s,{},i,cut)
        ctx['rosters']['BOS'][0].update(availability_status='Out',probability_played=0)
        r=simulate(ctx,p['player'],'points',20.5,1000,21,minimum=1000)
        self.assertEqual(r['void_count'],1000);self.assertEqual(r['under_count'],0)
        self.assertIsNone(r['p_over_raw'])
        self.assertEqual(r['regulation_team_minutes'],{'BOS':240,'NYK':240})
    def test_january_uses_correct_nba_start_year(self):
        self.assertEqual(season_start('2027-01-15'),2026)
        self.assertEqual(season_start('2026-10-31'),2026)

class SourceTests(unittest.TestCase):
    def test_secondary_fallback_never_claims_official_or_unlisted_healthy(self):
        teams=[{'team':{'id':str(i),'abbreviation':'T'+str(i)}} for i in range(25)]
        teams[0]={'team':{'id':'0','abbreviation':'POR'}}
        index={'sports':[{'leagues':[{'teams':teams}]}]}
        # Canonical ESPN team-index validation requires alphabetic abbreviations.
        for i,t in enumerate(teams[1:],1):t['team']['abbreviation']='A'+chr(65+i)
        payload={'injuries':[{'id':'0','injuries':[{'athlete':{'displayName':'Injured Player'},'status':'Day-To-Day','date':'2026-10-30T12:00Z'}]}]}
        r=secondary_injury_snapshot(payload,index,'2026-10-31T14:00:00Z','a'*64)
        self.assertEqual(r['authority'],'ESPN_SECONDARY_NOT_OFFICIAL');self.assertIsNone(r['printed_at'])
        self.assertEqual(r['teams']['POR'][name_key('Injured Player')]['status'],'UNKNOWN_NOT_CLEARED')
        self.assertNotIn(name_key('Unlisted Player'),r['teams']['POR'])
    def test_unique_suffix_match_is_audited_and_ambiguous_match_rejected(self):
        depth={'players':{name_key('Darius Acuff Jr.'):{'player':'Darius Acuff Jr.','id':'123'}}}
        names,checks=resolve_projected_names(['Darius Acuff'],depth)
        self.assertEqual(names,['Darius Acuff Jr.']);self.assertEqual(checks[0]['espn_player_id'],'123')
        depth['players'][name_key('Darius Acuff III')]={'player':'Darius Acuff III','id':'456'}
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS'):resolve_projected_names(['Darius Acuff'],depth)
    def test_projected_date_and_full_names(self):
        text='<main data-gamedate="2026-10-31"><ul class="lineup__list is-visit"><li class="lineup__status is-expected">Expected</li>'
        text+=''.join('<li class="lineup__player"><a title="Player '+str(i)+'" href="/basketball/player/p">P</a></li>' for i in range(5))
        text+='<li><button data-team="POR"></button></li></ul>'
        self.assertEqual(len(parse_projected(text,'2026-10-31')['POR']['players']),5)
        with self.assertRaisesRegex(ValueError,'DATE_CONFLICT'):parse_projected(text,'2026-11-01')
    def test_depth_team_and_future_clock(self):
        athletes=[{'displayName':'Player '+str(i),'id':str(i+1)} for i in range(7)]
        d={'team':{'abbreviation':'POR'},'depthchart':[{'positions':{p:{'athletes':athletes} for p in ('pg','sg','sf','pf','c')}}]}
        self.assertEqual(len(parse_depth(d,'POR','2026-10-31T14:00:00Z')['players']),7)
        with self.assertRaisesRegex(ValueError,'TEAM_CONFLICT'):parse_depth(d,'UTA','2026-10-31T14:00:00Z')
        d['timestamp']='2026-10-31T15:00:00Z'
        with self.assertRaisesRegex(ValueError,'CLOCK_AFTER'):parse_depth(d,'POR','2026-10-31T14:00:00Z')

class BlindAndLedgerTests(unittest.TestCase):
    def test_five_real_target_games_can_use_pooled_training_without_future_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=connect(str(Path(tmp)/'fixture.sqlite'));start=dt.date(2025,1,1)
            for name,n in [('Peer A',65),('Peer B',65),('Rookie',5)]:
                for i in range(n):
                    row={'player':name,'date':str(start+dt.timedelta(days=i)),'season':'2024-25','team':'BOS','opponent':'NYK',
                         'home':1,'starter':1,'minutes':25.,'pts':10.+i%7,'reb':5.,'ast':3.,'stl':1.,'blk':0.,'tov':2.,'fg3m':2.}
                    c.execute('INSERT INTO games VALUES('+','.join('?' for _ in FIELDS)+')',tuple(row[k] for k in FIELDS))
            c.commit();a,n=payload(c,'Rookie','points','2026-10-31');self.assertEqual(n,5)
            self.assertEqual(set(a),{'train','candidate','ridge'});self.assertNotIn('line',a)
            row['date']='2026-10-31';row['pts']=999
            c.execute('INSERT INTO games VALUES('+','.join('?' for _ in FIELDS)+')',tuple(row[k] for k in FIELDS))
            b,nn=payload(c,'Rookie','points','2026-10-31');self.assertEqual(nn,5)
            self.assertEqual(a,b);self.assertGreaterEqual(len(a['train']),100);c.close()
    def test_prediction_is_immutable_and_insert_cannot_be_backdated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'ledger.sqlite';n=dt.datetime.now(dt.timezone.utc)
            r={'status':'FORWARD_TEST_READY','prop':{'snapshot_id':'fixture','tipoff_utc':(n+dt.timedelta(hours=1)).isoformat()},
               'analysis_cutoff_utc':(n-dt.timedelta(minutes=2)).isoformat(),'forecast_completed_at_utc':(n-dt.timedelta(minutes=1)).isoformat(),
               'main_simulation':{'trials_executed':25000,'complete_sequential_games':True,'over_count':12000,'under_count':12000,'void_count':1000,'push_count':0}}
            r['receipt_sha256']=hashlib.sha256(json.dumps(r,sort_keys=True,allow_nan=False).encode()).hexdigest()
            record_prediction(db,r);c=ledger_connect(db)
            with self.assertRaisesRegex(sqlite3.IntegrityError,'IMMUTABLE'):c.execute('DELETE FROM early_predictions')
            c.close();self.assertEqual(scorecard(db)['predictions_frozen_before_tipoff'],1)
            r['prop']['tipoff_utc']=(n-dt.timedelta(hours=1)).isoformat()
            with self.assertRaisesRegex(ValueError,'PRECEDE_TIPOFF'):record_prediction(db,r)

if __name__=='__main__':unittest.main()
