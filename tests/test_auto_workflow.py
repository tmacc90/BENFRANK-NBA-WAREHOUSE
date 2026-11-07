"""Synthetic software tests; no fixture is a real-world forecast or calibration."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from benfrank_auto_history import Store, parse_gamelog, acquire_logs, write_history
from benfrank_auto_runner import historical_windows, run
from benfrank_auto_evidence import sensitivity, verify_trace, reproduce_trace_samples
from benfrank_v52_blind import run as blind_run
from benfrank_v52_early import simulate, early_context
from benfrank_auto_context import build_context, captured_board
from benfrank_auto_history import PP, sha
from test_v52_early import fixture


def log_document():
    return dict(labels=['MIN','FG','3PT','FT','PTS','REB','AST','STL','BLK','TO'],
        events={'123456789': dict(id='123456789', gameDate='2026-10-28T23:00:00Z', atVs='vs',
            team={'id':'2','abbreviation':'BOS'}, opponent={'id':'3','abbreviation':'NYK'})},
        seasonTypes=[dict(displayName='2026-27 Regular Season', categories=[dict(type='event', events=[
            dict(eventId='123456789', stats=['30','5-10','2-5','3-4','15','7','4','1','1','2'])])])])


def observation(points=15):
    return dict(player='Example Player', source_player_id='12', source_game_id='123456789',
        date='2026-10-28', tipoff_utc='2026-10-28T23:00:00Z', season='2026-27', team='BOS', opponent='NYK',
        home=1, starter=1, minutes=30., pts=points, reb=7, ast=4, stl=1, blk=1, tov=2, fg3m=2)


class AcquisitionTests(unittest.TestCase):
    def test_single_source_failure_keeps_exact_url_and_http_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp)
            def denied(url):raise urllib.error.HTTPError(url,403,'Forbidden',{},None)
            with self.assertRaisesRegex(ValueError,'SOURCE_FETCH_FAILED:.*prizepicks.*403'):
                s.fetch(PP,'PRIZEPICKS_NATIVE_PUBLIC',fetcher=denied)
            self.assertEqual(s.manifest()['failures'][0]['url'],PP);s.db.close()

    def test_supplied_board_retains_capture_clock_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(Path(tmp)/'state')
            doc=dict(data=[dict(id='77',attributes=dict(odds_type='standard',status='pre_game',
                stat_type='Points',description='NYK',start_time='2026-11-01T23:00:00Z',
                updated_at='2026-11-01T10:00:00Z',line_score=20.5),
                relationships={'new_player':{'data':{'type':'new_player','id':'9'}}})],
                included=[dict(type='new_player',id='9',attributes=dict(name='Example Player',team='BOS',league='NBA',combo=False))])
            raw=json.dumps(doc).encode();meta=s.save(PP,raw,'PRIZEPICKS_NATIVE_PUBLIC','2026-11-01T11:00:00Z')
            gz=Path(tmp)/'capture.gz';gz.write_bytes(gzip.compress(raw))
            rp=Path(tmp)/'receipt.json';rp.write_text(json.dumps(meta))
            cfg=dict(game_date='2026-11-01',capture_gzip=str(gz),capture_receipt=str(rp))
            games=[dict(home='BOS',away='NYK',game_id='espn:123456789',espn_event_id='123456789',
                        tipoff_utc='2026-11-01T23:00:00Z',status=dict(state='pre'))]
            with patch('benfrank_auto_context.now',return_value='2026-11-01T12:00:00Z'),patch('benfrank_auto_context.schedule',return_value=games):
                board,audit=captured_board(s,cfg)
                self.assertEqual(board[0]['line_capture_utc'],'2026-11-01T11:00:00Z')
                self.assertEqual(board[0]['source_capture_imported_utc'],'2026-11-01T12:00:00Z')
                self.assertFalse(audit['current_native_line_recheck'])
                gz.write_bytes(gzip.compress(b'{}'))
                with self.assertRaisesRegex(ValueError,'BYTES_HASH_CONFLICT'):captured_board(s,cfg)
            s.db.close()

    def test_ci_fallback_only_accepts_the_exact_native_provider_403(self):
        from scripts.run_auto_ci import execute
        with tempfile.TemporaryDirectory() as tmp:
            live=dict(status='INCOMPLETE',fatal_blocker='ValueError: SOURCE_FETCH_FAILED:'+PP+':HTTPError: HTTP Error 403: Forbidden')
            captured=dict(status='FORWARD_RESEARCH_EXECUTED')
            with patch('scripts.run_auto_ci.run',side_effect=[(live,2),(captured,0)]) as mocked,patch('scripts.run_auto_ci.verify',return_value=dict(predictions=4)):
                self.assertEqual(execute('live.json','capture.json',Path(tmp)/'ok',Path(tmp)/'state'),0)
                self.assertEqual(mocked.call_count,2)
            with patch('scripts.run_auto_ci.run',return_value=(dict(status='INCOMPLETE',fatal_blocker='MODEL_ERROR'),2)) as mocked:
                self.assertEqual(execute('live.json','capture.json',Path(tmp)/'blocked',Path(tmp)/'state'),2)
                self.assertEqual(mocked.call_count,1)

    def test_stale_or_post_tipoff_source_capture_is_not_forward_input(self):
        from benfrank_auto_context import parse_projection_capture
        meta=dict(retrieved_utc='2026-11-01T11:00:00Z')
        with self.assertRaisesRegex(ValueError,'STALE_OR_FUTURE'):
            parse_projection_capture(b'{}',meta,[],observed_at='2026-11-02T12:00:00Z')

    def test_end_year_regular_season_and_shooting_conservation(self):
        rows, rejected = parse_gamelog(log_document(), 'Example Player', '12', 2027)
        self.assertEqual(rejected, []); self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['pts'], 15); self.assertEqual(rows[0]['fg2m'], 3)
        self.assertEqual(parse_gamelog(log_document(), 'Example Player', '12', 2026)[0], [])
        bad = log_document(); bad['seasonTypes'][0]['categories'][0]['events'][0]['stats'][4] = '50'
        self.assertEqual(parse_gamelog(bad, 'Example Player', '12', 2027)[0], [])

    def test_no_all_star_or_duplicate_appearance(self):
        doc = log_document(); doc['events']['123456789']['team']['isAllStar'] = True
        self.assertEqual(parse_gamelog(doc, 'Example Player', '12', 2027)[0], [])
        doc = log_document(); entries = doc['seasonTypes'][0]['categories'][0]['events']; entries += copy.deepcopy(entries)
        rows, rejected = parse_gamelog(doc, 'Example Player', '12', 2027)
        self.assertEqual(len(rows), 1); self.assertIn('DUPLICATE', rejected[0]['reason'])

    def test_l52_reconciliation_uses_independent_upstream_and_quarantines(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(tmp)
            a = s.save('https://site.api.espn.com/a', b'original', 'ESPN', '2026-10-29T12:00:00Z')
            b = s.save('https://cdn.nba.com/a', b'independent', 'NBA_DIRECT', '2026-10-29T12:01:00Z')
            s.ingest(observation(), a); s.ingest(observation(), b); s.db.commit()
            r = s.reconcile('2026-10-30T00:00:00Z', '2026-10-30')
            self.assertTrue(r['records'][0]['independent_sources_agree'])
            c = s.save('https://cdn.nba.com/b', b'correction', 'NBA_DIRECT', '2026-10-29T13:00:00Z')
            s.ingest(observation(16), c); s.db.commit()
            r = s.reconcile('2026-10-30T00:00:00Z', '2026-10-30')
            self.assertEqual(r['records'], []); self.assertIn('pts', r['conflicts'][0]['fields'])
            s.db.close()

    def test_cutoff_filter_precedes_comparison_and_no_retrieval_backdating(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(tmp)
            a = s.save('https://site.api.espn.com/a', b'old', 'ESPN', '2026-10-29T12:00:00Z')
            b = s.save('https://site.api.espn.com/a', b'new', 'ESPN', '2026-10-30T12:00:00Z')
            s.ingest(observation(), a); s.ingest(observation(99), b); s.db.commit()
            r = s.reconcile('2026-10-30T00:00:00Z', '2026-10-30', strict_observed=True)
            self.assertEqual(r['records'][0]['pts'], 15)
            self.assertEqual(r['exclusions']['RETRIEVED_AFTER_ORIGINAL_CUTOFF'], 1)
            self.assertEqual(s.reconcile('2026-10-30T00:00:00Z', '2026-10-28')['records'], [])
            s.db.close()

    def test_source_store_is_append_only_and_raw_receipt_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(tmp); a = s.save('https://site.api.espn.com/a', b'raw', 'ESPN')
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'IMMUTABLE'):
                s.db.execute('DELETE FROM documents')
            fake = dict(a, id='fake')
            with self.assertRaisesRegex(ValueError, 'RECEIPT_MISSING'): s.ingest(observation(), fake)
            with self.assertRaisesRegex(ValueError, 'CONSERVATION'):
                s.ingest(dict(observation(), fgm=4, fga=10, ftm=1), a)
            s.db.close()

    def test_neutral_site_home_disagreement_is_one_quarantined_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp)
            a=s.save('https://site.api.espn.com/a',b'one','ESPN','2026-10-29T12:00:00Z')
            b=s.save('https://cdn.nba.com/a',b'two','NBA_DIRECT','2026-10-29T12:00:00Z')
            s.ingest(observation(),a);s.ingest(dict(observation(),home=0),b);s.db.commit()
            r=s.reconcile('2026-10-30T00:00:00Z','2026-10-30')
            self.assertEqual(r['records'],[]);self.assertEqual(len(r['conflicts']),1)
            self.assertIn('home',r['conflicts'][0]['fields']);s.db.close()

    def test_recent_in_progress_game_log_is_not_a_feature(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(tmp);meta=s.save('https://site.api.espn.com/a',b'live','ESPN','2026-10-29T00:00:00Z')
            s.ingest(observation(),meta);s.db.commit()
            r=s.reconcile('2026-10-29T01:00:00Z','2026-10-29')
            self.assertEqual(r['records'],[])
            self.assertEqual(r['exclusions']['RECENT_GAMELOG_REQUIRES_FINAL_SUMMARY'],1)
            final=s.save('https://site.api.espn.com/b',b'final','ESPN','2026-10-29T00:30:00Z')
            s.ingest(dict(observation(),completed=True),final);s.db.commit()
            self.assertEqual(len(s.reconcile('2026-10-29T01:00:00Z','2026-10-29')['records']),1);s.db.close()

    def test_normalizer_to_reconciler_to_legacy_read_model_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp)/'state')
            audit = acquire_logs(s, {'12':'Example Player'}, '2026-11-01', seasons=1,
                                 fetcher=lambda url: json.dumps(log_document()).encode())
            self.assertEqual(audit[0]['parsed'], 1)
            r = s.reconcile('2026-11-01T00:00:00Z', '2026-11-01')
            dbpath = Path(tmp)/'read.sqlite'; write_history(r['records'], dbpath)
            with sqlite3.connect(dbpath) as conn:
                self.assertEqual(conn.execute('SELECT pts FROM games').fetchone()[0], 15)
            with self.assertRaises(FileExistsError): write_history(r['records'], dbpath)
            windows = historical_windows(r['records'], 'points', 15, '2026-11-01')
            self.assertEqual(windows['L52']['push_count'], 1)
            self.assertEqual(windows['L52']['status'], 'PARTIAL'); s.db.close()


class PhysicalEvidenceTests(unittest.TestCase):
    def test_out_depth_player_without_profile_cannot_be_projected(self):
        from acquire_history import name_key
        p,c,s,i,cut=fixture()
        for team in ('BOS','NYK'):
            s['depths'][team]['positions']['PG'].insert(0,'Inactive Unprofiled '+team)
            i.setdefault('teams',{})[team]={name_key('Inactive Unprofiled '+team):dict(status='Out')}
        context=early_context(c,p,s,{},i,cut)
        for team in ('BOS','NYK'):
            self.assertNotIn('Inactive Unprofiled '+team,context['early_role_evidence'][team]['selected_projected_five'])

    def test_injury_replacement_starter_survives_fifteen_player_trim(self):
        from types import SimpleNamespace
        from acquire_history import name_key
        p,c,s,inj,cut=fixture();templates={}
        for team in ('BOS','NYK'):
            base=copy.deepcopy(c['rosters'][team][0]);names=[team+' Player '+str(n) for n in range(17)]
            for n,name in enumerate(names):
                templates[name]=dict(base,player=name,minutes_mean=30 if n<15 else 2,
                                     max_feature_game_date='2026-10-28')
            s['depths'][team]['players']={name_key(name):dict(player=name,id=str(n)) for n,name in enumerate(names)}
            s['depths'][team].update(url='https://site.api.espn.com/fixture',
                positions={pos:[names[n],names[16],*names] for n,pos in enumerate(('PG','SG','SF','PF','C'))})
            inj.setdefault('teams',{})[team]={name_key(names[0]):dict(status='Out')}
        history=SimpleNamespace(profile=lambda name,*args:copy.deepcopy(templates[name]),
            rates_from_boxes=lambda team,*args:(c['team_rates'][team],100,4,['2026-10-28']))
        game=dict(home='BOS',away='NYK')
        result=build_context(p,game,s,history,{},cut,inj)
        self.assertEqual(len(result['rosters']['BOS']),15)
        self.assertIn('BOS Player 16',{x['player'] for x in result['rosters']['BOS']})

    def test_trace_roundtrip_and_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,c,s,i,cut = fixture(); context = early_context(c,p,s,{},i,cut)
            path = Path(tmp)/'trace.jsonl.gz'
            result = simulate(context,p['player'],'points',20.5,16,21,minimum=1,trace_path=path)
            self.assertTrue(result['trial_evidence']['verified'])
            self.assertEqual(result['trial_evidence']['trials_executed'],16)
            restored=json.loads(json.dumps(context,sort_keys=True))
            proof=reproduce_trace_samples(restored,result,p['player'],'points',path)
            self.assertEqual(proof['complete_games_reexecuted'],5)
            bad = dict(result, trial_chain_sha256='0'*64)
            with self.assertRaisesRegex(ValueError,'HASH_CONFLICT'): verify_trace(path,bad,20.5)
            with self.assertRaises(FileExistsError):
                simulate(context,p['player'],'points',20.5,16,21,minimum=1,trace_path=path)

    def test_ladder_pushes_voids_and_flip_are_separate(self):
        sim = dict(histogram={'9':2,'10':2,'11':6}, void_count=3)
        r = sensitivity(sim,10)
        at = {x['line']:x for x in r['ladder']}
        self.assertEqual(at[10]['push'],2); self.assertEqual(at[10]['void'],3)
        self.assertEqual(at[10.5]['p_over_raw'],.6)
        self.assertEqual(at[11]['side'],'UNDER')
        self.assertFalse(r['calibration_applied'])

    def test_minimum_genuine_trial_request_enforced_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'25000'):
                run('missing.json',Path(tmp)/'out',trials=24999)

    def test_blind_process_proof_requires_real_payload_hash(self):
        from engine import connect, FIELDS
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.sqlite';conn=connect(path)
            for name in ('One','Two'):
                for n in range(65):
                    row=dict(player=name,date=str(dt.date(2025,1,1)+dt.timedelta(days=n)),season='2024-25',
                             team='BOS',opponent='NYK',home=1,starter=1,minutes=30,pts=10+n%8,
                             reb=5,ast=3,stl=1,blk=1,tov=2,fg3m=2)
                    conn.execute('INSERT INTO games VALUES('+','.join('?' for _ in FIELDS)+')',tuple(row[k] for k in FIELDS))
            conn.commit();conn.close()
            r=blind_run(path,'One','points','2026-11-01')
            self.assertTrue(r['independence_evidence']['verified'])
            self.assertFalse(r['independence_evidence']['accuracy_independently_validated'])
            self.assertEqual(r['independence_evidence']['worker_payload_keys'],['candidate','ridge','train'])


if __name__=='__main__': unittest.main()
