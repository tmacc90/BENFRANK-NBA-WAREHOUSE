"""Software fixtures only. Mocked model output is never prediction evidence."""
import datetime as dt
import hashlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from mobile import api
from benfrank_auto_context import parse_projection_capture
from benfrank_auto_runner import run

TOKEN = 'software-test-token-' + 'x' * 40


class MobileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(api, 'ROOT', self.root), patch.object(api, 'JOBS', {}),
            patch.object(api, 'RUN_LOCK', threading.Lock()),
            patch.dict('os.environ', {'BENFRANK_API_TOKEN': TOKEN, 'BENFRANK_REQUIRE_PERSISTENT_STORAGE': 'false'})]
        for p in self.patches:
            p.start()
        self.client = TestClient(api.app, base_url='https://testserver')
        self.headers = {'Authorization': 'Bearer ' + TOKEN}
        self.form = {'player': 'Example Player', 'market': 'points', 'line': '20.5',
                     'pregame_cutoff': '2031-01-02T01:00:00Z'}

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def post(self, **changes):
        return self.client.post('/api/run-framework', headers=self.headers, data=dict(self.form, **changes))

    def queue(self):
        with patch('mobile.api.threading.Thread'):
            r = self.post()
        self.assertEqual(r.status_code, 202, r.text)
        job_id = r.json()['job_id']
        return job_id, json.loads((self.root / job_id / 'request.json').read_text())

    def failed_result(self, **changes):
        return dict(status='INCOMPLETE', props=[], all_requested_props_executed=False,
                    preservation_verified=True, fatal_blocker='TEST_SOURCE_UNAVAILABLE', **changes)

    def write_mock_run(self, result):
        def fake(config, output, state, trials, stress):
            self.assertEqual((trials, stress), (25000, 2000))
            folder = Path(output); folder.mkdir()
            (folder / 'execution_receipt.json').write_text(json.dumps(result))
            return result, 0 if result.get('all_requested_props_executed') else 2
        return fake

    def test_authentication_precedes_form_parsing_and_protects_receipts(self):
        self.assertEqual(self.client.post('/api/run-framework').status_code, 401)
        for path in ('/api/jobs/' + 'a' * 32, '/api/jobs/' + 'a' * 32 + '/receipt', '/openapi.json'):
            self.assertEqual(self.client.get(path).status_code, 401)
        r = self.client.get('/api/jobs/' + 'a' * 32, headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers['www-authenticate'], 'Bearer')

    def test_public_page_assets_and_health(self):
        for path in ('/', '/mobile.js', '/mobile.css'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.headers['cache-control'], 'no-store')
            self.assertIn("connect-src 'self'", r.headers['content-security-policy'])
            self.assertIn('strict-transport-security', r.headers)
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertFalse(self.client.get('/health').json()['execution_verified'])

    def test_missing_short_and_non_ascii_token_fail_closed(self):
        for value in ('', 'short', 'é' * 40):
            with patch.dict('os.environ', {'BENFRANK_API_TOKEN': value}):
                self.assertEqual(self.client.get('/health').status_code, 503)
                self.assertEqual(self.post().status_code, 503)

    def test_unmounted_deployment_storage_blocks_jobs(self):
        with patch.dict('os.environ', {'BENFRANK_REQUIRE_PERSISTENT_STORAGE': 'true'}), patch('os.path.ismount', return_value=False):
            self.assertEqual(self.client.get('/health').status_code, 503)
            self.assertEqual(self.post().status_code, 503)

    def test_request_exact_prop_cutoff_and_eastern_day_are_preserved_without_secret(self):
        job_id, cfg = self.queue()
        self.assertEqual(cfg['requested_prop'], {'player': 'Example Player', 'market': 'points', 'line': 20.5})
        self.assertEqual(cfg['game_date'], '2031-01-01')
        self.assertEqual(cfg['pregame_cutoff_utc'], '2031-01-02T01:00:00+00:00')
        self.assertEqual(cfg['max_props'], 1)
        self.assertNotIn(TOKEN, ''.join(p.read_text() for p in (self.root / job_id).rglob('*.json')))
        self.assertEqual(self.post().status_code, 429)

    def test_invalid_inputs_do_not_start_a_job(self):
        cases = ({'line': 'nan'}, {'line': '-1'}, {'line': 'inf'}, {'market': 'shell'},
                 {'player': ' '}, {'player': 'x' * 121}, {'pregame_cutoff': '2031-01-01T01:00:00'},
                 {'pregame_cutoff': '2001-01-01T00:00:00Z'})
        with patch('mobile.api.threading.Thread') as thread:
            for fields in cases:
                self.assertEqual(self.post(**fields).status_code, 422, fields)
            thread.assert_not_called()

    def test_oversized_body_and_unsupported_upload_are_rejected(self):
        self.assertEqual(self.client.post('/api/run-framework', headers=self.headers, content=b'x' * (api.MAX_BODY + 1)).status_code, 413)
        r = self.client.post('/api/run-framework', headers=self.headers, data=self.form,
                             files={'screenshot': ('image.png', b'fixture', 'image/png')})
        self.assertEqual(r.status_code, 422)

    def test_batch_preserves_all_props_without_native_discovery_dependency(self):
        props=[dict(player='Example Player',market=m,line=10.5) for m in
               ('points','rebounds','assists','pr','pa','ra','pra','fantasy_score')]
        with patch('mobile.api.threading.Thread'):
            response=self.client.post('/api/run-framework-batch',headers=self.headers,
                data=dict(game_date='2031-01-01',props_json=json.dumps(props),pregame_cutoff=self.form['pregame_cutoff']))
        self.assertEqual(response.status_code,202,response.text)
        cfg=json.loads((self.root/response.json()['job_id']/'request.json').read_text())
        self.assertEqual(cfg['props'],props)
        self.assertEqual(cfg['mode'],'uploaded_props')
        self.assertNotIn('max_props',cfg)

    def test_batch_accepts_multiple_valid_screenshots_and_rejects_fake_images(self):
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(20,20),'white').save(image,format='PNG')
        data=dict(game_date='2031-01-01',pregame_cutoff=self.form['pregame_cutoff'])
        with patch('mobile.api.threading.Thread'):
            response=self.client.post('/api/run-framework-batch',headers=self.headers,data=data,
                files=[('screenshots',('one.png',image.getvalue(),'image/png')),
                       ('screenshots',('two.png',image.getvalue(),'image/png'))])
        self.assertEqual(response.status_code,202,response.text)
        cfg=json.loads((self.root/response.json()['job_id']/'request.json').read_text())
        self.assertEqual(len(cfg['screenshots']),2)
        api.RUN_LOCK.release()
        response=self.client.post('/api/run-framework-batch',headers=self.headers,data=data,
            files={'screenshots':('invalid.png',b'not an image','image/png')})
        self.assertEqual(response.status_code,422)
        self.assertFalse(api.RUN_LOCK.locked())

    def test_worker_failure_remains_unverified_and_releases_capacity(self):
        job_id, cfg = self.queue()
        with patch.object(api, 'run', side_effect=RuntimeError('fixture failure')):
            api.worker(job_id, cfg)
        job = api.read_job(job_id)
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(job['execution_receipt']['verified'])
        self.assertIn('request', job)
        self.assertFalse(api.RUN_LOCK.locked())
        self.assertEqual(len(list((self.root / job_id / 'events').glob('*.json'))), 3)

    def test_source_blocker_is_preserved_and_authenticated_artifacts_download(self):
        job_id, cfg = self.queue()
        with patch.object(api, 'run', side_effect=self.write_mock_run(self.failed_result())):
            api.worker(job_id, cfg)
        job = api.read_job(job_id)
        self.assertEqual(job['status'], 'incomplete')
        self.assertEqual(job['reason'], 'TEST_SOURCE_UNAVAILABLE')
        self.assertFalse(job['execution_receipt']['verified'])
        url = '/api/jobs/' + job_id
        receipt = self.client.get(url + '/receipt', headers=self.headers)
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(hashlib.sha256(receipt.content).hexdigest(), job['execution_receipt']['sha256'])
        r = self.client.get(url + '/artifacts', headers=self.headers)
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertIn('request.json', z.namelist())
            self.assertIn('execution/execution_receipt.json', z.namelist())
        api.JOBS.clear()
        self.assertEqual(api.read_job(job_id)['status'], 'incomplete')

    def test_claimed_success_requires_independent_artifact_verification(self):
        job_id, cfg = self.queue()
        p = dict(prop=cfg['requested_prop'], status='FORWARD_TEST_READY_UNCALIBRATED')
        result = dict(status='FORWARD_RESEARCH_EXECUTED', props=[p], all_requested_props_executed=True, preservation_verified=True)
        with patch.object(api, 'run', side_effect=self.write_mock_run(result)), patch.object(api, 'verify', side_effect=ValueError('TRACE_HASH_CONFLICT')):
            api.worker(job_id, cfg)
        job = api.read_job(job_id)
        self.assertEqual(job['status'], 'incomplete')
        self.assertFalse(job['execution_receipt']['verified'])
        self.assertIn('TRACE_HASH_CONFLICT', job['reason'])

    def test_successful_fixture_reports_execution_without_accuracy_certification(self):
        job_id, cfg = self.queue()
        p = dict(prop=dict(cfg['requested_prop'], snapshot_id='test'), status='FORWARD_TEST_READY_UNCALIBRATED')
        result = dict(status='FORWARD_RESEARCH_EXECUTED', props=[p], all_requested_props_executed=True, preservation_verified=True)
        with patch.object(api, 'run', side_effect=self.write_mock_run(result)), patch.object(api, 'verify', return_value={'status': 'SOFTWARE_TEST_FIXTURE'}):
            api.worker(job_id, cfg)
        self.assertEqual(api.read_job(job_id)['status'], 'completed')
        self.assertTrue(api.read_job(job_id)['execution_receipt']['verified'])

    def test_restart_marks_active_job_interrupted_but_keeps_request(self):
        job_id, _ = self.queue()
        api.JOBS.clear()
        api.recover_jobs()
        job = api.read_job(job_id)
        self.assertEqual(job['status'], 'interrupted')
        self.assertEqual(job['error'], 'SERVER_RESTART_INTERRUPTED_JOB')
        self.assertIn('request', job)
        self.assertTrue((self.root / job_id / 'request.json').is_file())

    def test_unknown_jobs_and_running_receipts_have_explicit_status(self):
        self.assertEqual(self.client.get('/api/jobs/..', headers=self.headers).status_code, 404)
        job_id, _ = self.queue()
        self.assertEqual(self.client.get('/api/jobs/' + job_id + '/receipt', headers=self.headers).status_code, 409)


class ExactSelectionTests(unittest.TestCase):
    def test_prediction_ledger_rejects_issuance_after_requested_deadline(self):
        from benfrank_v52_ledger import record_prediction
        receipt = {'status': 'FORWARD_TEST_READY', 'prop': {'tipoff_utc': '2031-01-01T23:00:00Z'},
            'analysis_cutoff_utc': '2031-01-01T10:00:00Z',
            'forecast_completed_at_utc': '2031-01-01T10:01:00Z',
            'requested_pregame_cutoff_utc': '2031-01-01T10:02:00Z',
            'main_simulation': {'trials_executed': 25000, 'complete_sequential_games': True,
                                'over_count': 12500, 'under_count': 12500}}
        with tempfile.TemporaryDirectory() as tmp, patch('benfrank_v52_ledger.now', return_value='2031-01-01T10:03:00Z'):
            path = Path(tmp) / 'ledger.sqlite'
            with self.assertRaisesRegex(ValueError, 'ACTUAL_PREDICTION_INSERT_MUST_PRECEDE_REQUESTED_CUTOFF'):
                record_prediction(path, receipt)
            self.assertFalse(path.exists())

    def test_requested_prop_is_selected_before_two_player_sampling_limit(self):
        players = ['Alice Player', 'Bob Player', 'Charlie Player']
        raw = {'data': [], 'included': []}
        for n, name in enumerate(players):
            raw['data'].append(dict(id=str(n), attributes=dict(odds_type='standard', status='pre_game', stat_type='Points',
                description='NYK', start_time='2031-01-01T23:00:00Z', line_score=20.5),
                relationships={'new_player': {'data': {'type': 'new_player', 'id': str(n)}}}))
            raw['included'].append(dict(type='new_player', id=str(n), attributes=dict(name=name, team='BOS', league='NBA')))
        games = [dict(game_id='espn:1', espn_event_id='1', home='BOS', away='NYK', tipoff_utc='2031-01-01T23:00:00Z', status={'state': 'pre'})]
        meta = dict(retrieved_utc='2031-01-01T12:00:00Z', url='fixture', id='fixture', sha256='fixture')
        wanted = dict(player='Charlie Player', market='points', line=20.5)
        board, _ = parse_projection_capture(json.dumps(raw).encode(), meta, games, observed_at='2031-01-01T12:00:01Z', requested_prop=wanted)
        self.assertEqual([p['player'] for p in board], ['Charlie Player'])
        with self.assertRaisesRegex(ValueError, 'REQUESTED_EXACT_PROP_NOT_ON_CURRENT_NATIVE_BOARD'):
            parse_projection_capture(json.dumps(raw).encode(), meta, games, observed_at='2031-01-01T12:00:01Z', requested_prop=dict(wanted, line=21.5))

    def test_expired_cutoff_blocks_before_any_live_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp); cfg = path / 'input.json'
            cfg.write_text(json.dumps(dict(game_date='2001-01-01', pregame_cutoff_utc='2001-01-01T12:00:00Z')))
            with patch('benfrank_auto_runner.discover') as network:
                result, code = run(cfg, path / 'run', path / 'state')
            network.assert_not_called()
            self.assertEqual(code, 2)
            self.assertIn('REQUESTED_PREGAME_CUTOFF_ALREADY_PASSED', result['fatal_blocker'])
            self.assertTrue(result['preservation_verified'])
