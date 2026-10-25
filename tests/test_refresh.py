import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import refresh_and_audit as refresh


GID = '0022400124'
TARGET = {'nba_game_id': GID, 'nba_player_id': '1642385'}


def response(game_id=GID, status=3, players=None):
    return {'game': {'gameId': game_id, 'gameStatus': status,
                     'homeTeam': {'players': players or []},
                     'awayTeam': {'players': []}}}


class Response(io.BytesIO):
    status = 200


class RefreshTests(unittest.TestCase):
    def opener(self, data):
        return lambda *a, **k: Response(json.dumps(data).encode())

    def test_exact_identity_and_final_required(self):
        for data in (response('0022400999'), response(status=2)):
            receipt, payload, raw = refresh.fetch_game(GID, 1, 1, self.opener(data))
            self.assertIsNone(payload)
            self.assertEqual(receipt['status'], 'UNAVAILABLE')
            self.assertEqual(len(receipt['attempts']), 1)

    def test_http_failure_each_attempt_retained(self):
        def fail(*a, **k):
            raise urllib.error.HTTPError('https://cdn.nba.com', 503, 'Service Unavailable', {}, None)
        receipt, payload, raw = refresh.fetch_game(GID, 1, 2, fail, lambda _: None)
        self.assertEqual([a['http_status'] for a in receipt['attempts']], [503, 503])
        self.assertIsNone(payload)

    def test_forbidden_is_terminal_and_nba_referer_sent(self):
        calls = []
        def fail(request, **kwargs):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {}, None)
        receipt, payload, raw = refresh.fetch_game(GID, 1, 3, fail, lambda _: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get_header('Referer'), 'https://www.nba.com/')

    def test_transient_failure_retained_on_success(self):
        calls = []
        def open_after_retry(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError('test timeout')
            return Response(json.dumps(response()).encode())
        receipt, payload, raw = refresh.fetch_game(GID, 1, 2, open_after_retry, lambda _: None)
        self.assertEqual(receipt['status'], 'FETCHED_FINAL')
        self.assertEqual(receipt['attempts'][0]['error_type'], 'TimeoutError')
        self.assertEqual(len(receipt['attempts']), 2)

    def test_summary_includes_pending_and_ambiguous_records(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            summary = refresh.snapshot(out, [TARGET], {}, {})
            self.assertFalse(summary['capture_complete'])
            self.assertEqual(json.loads((out / 'unresolved.json').read_text())[0]['evidence_status'], 'NOT_ATTEMPTED')
            data = response(players=[{'personId':1642385}, {'personId':1642385}])
            summary = refresh.snapshot(out, [TARGET], {GID:{'status':'FETCHED_FINAL'}}, {GID:data})
            self.assertEqual(summary['still_unresolved'], 1)
            self.assertFalse(summary['capture_complete'])

    def test_capture_never_claims_database_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            data = response(players=[{'personId':1642385, 'played':'0'}])
            summary = refresh.snapshot(Path(directory), [TARGET],
                                       {GID:{'status':'FETCHED_FINAL'}}, {GID:data}, 52906)
            self.assertTrue(summary['capture_complete'])
            self.assertFalse(summary['database_modified'])
            self.assertFalse(summary['full_coverage'])
            self.assertEqual(summary['database_rows_after'], 52906)

    def test_duplicate_and_pathlike_ids_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            for ledger in ([TARGET, TARGET], [dict(TARGET, nba_game_id='../foo')], []):
                path.write_text(json.dumps(ledger))
                with self.assertRaises(ValueError):
                    refresh.read_ledger(path)

    def test_missing_player_fails_capture_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(refresh, 'fetch_game', return_value=(
                {'game_id':GID,'status':'FETCHED_FINAL'}, response(), b'{}')):
                self.assertEqual(refresh.run([TARGET], directory), 2)


if __name__ == '__main__':
    unittest.main()
