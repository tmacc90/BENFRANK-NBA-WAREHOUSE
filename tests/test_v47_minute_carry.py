"""Rollover evidence from the original source rather than fabricated game minutes."""
import unittest
from acquire_history import minutes

class OfficialClockRolloverTests(unittest.TestCase):
    def test_archive_rounded_clock_seconds_carry(self):
        # Raw archived NBA mirror values causing 127 historical failures.
        self.assertEqual(minutes("13:60"),14.0)
        self.assertEqual(minutes("30:60"),31.0)
        self.assertEqual(minutes("0:60"),1.0)
        self.assertEqual(minutes("13:60.0"),14.0)
    def test_normal_clock_unchanged(self):
        self.assertAlmostEqual(minutes("32:30"),32.5)
        self.assertEqual(minutes("25:00"),25.0)
        self.assertEqual(minutes("28.5"),28.5)
    def test_noncarry_invalid_clocks_not_imputed(self):
        for value in ("10:61","10:60.01","10:-1","10:nan","10:inf","10:xxx"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    minutes(value)
    def test_above_max_game_minutes_rejected(self):
        with self.assertRaises(ValueError):
            minutes("70:60")

if __name__=="__main__":
    unittest.main()
