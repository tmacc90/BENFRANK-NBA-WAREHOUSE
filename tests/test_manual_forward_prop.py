"""Offline unit checks for zero-subscription manual prop resolution."""
import unittest
from unittest.mock import patch

from benfrank_manual_prop import resolve_manual_forward_prop

GAME = {'game_id': 'espn:123', 'espn_event_id': '123',
        'game_date': '2026-11-07', 'tipoff_utc': '2026-11-08T02:00:00+00:00',
        'home': 'DEN', 'away': 'UTA', 'status': {'state': 'pre'},
        'source_document': {'url': 'https://site.api.espn.com/mock'}}
ROLES = ({'game_date': '2026-11-07', 'depths': {
    'DEN': {'players': {'1': {'player': 'Sample Nuggets Player', 'id': '12345'}}},
    'UTA': {'players': {'2': {'player': 'Sample Jazz Player', 'id': '23456'}}}}},
    {'teams': {}, 'retrieved_at': '2026-11-07T20:00:00+00:00'}, {})


class ManualForwardPropTests(unittest.TestCase):
    def configured(self):
        return {'game_date': '2026-11-07',
                'manual_prop': {'player': 'Sample Nuggets Player',
                                'market': 'points', 'line': 15.5}}

    def test_manual_line_resolves_future_espn_identity_without_prizepicks(self):
        with patch('benfrank_manual_prop.schedule', return_value=[GAME]), \
             patch('benfrank_manual_prop.capture_roles', return_value=ROLES) as capture, \
             patch('benfrank_manual_prop.now', return_value='2026-11-07T20:00:00+00:00'):
            board, detail, roles = resolve_manual_forward_prop(None, self.configured())
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0]['team'], 'DEN')
        self.assertEqual(board[0]['opponent'], 'UTA')
        self.assertEqual(board[0]['line'], 15.5)
        self.assertEqual(board[0]['line_authority'], 'USER_ENTERED_NOT_INDEPENDENTLY_PLATFORM_VERIFIED')
        self.assertIsNone(board[0]['native_platform_line_capture_utc'])
        self.assertIn('MANUAL_LINE', detail['source_route'])
        self.assertEqual(roles, ROLES)
        capture.assert_called_once_with(None, ['DEN', 'UTA'], '2026-11-07')

    def test_rejects_started_game(self):
        early = dict(GAME, tipoff_utc='2026-11-07T18:00:00+00:00')
        with patch('benfrank_manual_prop.schedule', return_value=[early]), \
             patch('benfrank_manual_prop.now', return_value='2026-11-07T20:00:00+00:00'):
            with self.assertRaisesRegex(ValueError, 'NO_UNSTARTED_NBA_GAMES'):
                resolve_manual_forward_prop(None, self.configured())

    def test_missing_manual_line_fails_before_http(self):
        with self.assertRaisesRegex(ValueError, 'MANUAL_PROP_REQUIRED'):
            resolve_manual_forward_prop(None, {'game_date': '2026-11-07'})

    def test_rejects_ambiguous_player(self):
        twin_roles = ({'depths': {
            'DEN': {'players': {'1': {'player':'Same Player','id':'111'}}},
            'UTA': {'players': {'2': {'player':'Same Player','id':'222'}}}}}, {}, {})
        cfg = self.configured()
        cfg['manual_prop']['player'] = 'Same Player'
        with patch('benfrank_manual_prop.schedule', return_value=[GAME]), \
             patch('benfrank_manual_prop.capture_roles', return_value=twin_roles), \
             patch('benfrank_manual_prop.now', return_value='2026-11-07T20:00:00+00:00'):
            with self.assertRaisesRegex(ValueError, 'NOT_UNIQUELY_RESOLVED'):
                resolve_manual_forward_prop(None, cfg)

    def test_rejects_bool_line(self):
        cfg = self.configured()
        cfg['manual_prop']['line'] = True
        with self.assertRaisesRegex(ValueError, 'FINITE_LINE_REQUIRED'):
            resolve_manual_forward_prop(None, cfg)


if __name__ == '__main__':
    unittest.main()
