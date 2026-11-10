"""
tests/test_strike_selector.py
Unit tests for strike calculation, step sizing, and rollover rules.
"""

import unittest
from engine.strike_selector import StrikeSelector


class TestStrikeSelector(unittest.TestCase):
    def setUp(self):
        self.selector = StrikeSelector()

    def test_step_sizes(self):
        self.assertEqual(self.selector.get_step_size(3000.0), 50.0)
        self.assertEqual(self.selector.get_step_size(1500.0), 20.0)
        self.assertEqual(self.selector.get_step_size(600.0), 10.0)
        self.assertEqual(self.selector.get_step_size(300.0), 5.0)
        self.assertEqual(self.selector.get_step_size(150.0), 2.5)

    def test_atm_strike_calculation(self):
        # TECHM @ 1684 -> step 20 -> 1680
        self.assertEqual(self.selector.calculate_atm_strike(1684.0), 1680.0)
        # GLENMARK @ 1742 -> step 20 -> 1740
        self.assertEqual(self.selector.calculate_atm_strike(1742.0), 1740.0)
        # COALINDIA @ 423 -> step 5 -> 425
        self.assertEqual(self.selector.calculate_atm_strike(423.0), 425.0)

    def test_symbol_generation(self):
        info = self.selector.build_option_symbol("TECHM", 1680.0, "PE")
        self.assertEqual(info['stock'], "TECHM")
        self.assertEqual(info['strike'], 1680.0)
        self.assertEqual(info['opt_type'], "PE")
        self.assertIn("TECHM", info['nse_symbol'])
        self.assertIn("1680PE", info['nse_symbol'])

    def test_candidate_validation(self):
        # Valid
        ok, _ = self.selector.validate_option_candidate(1000.0, 25.0)
        self.assertTrue(ok)
        # Penny trap
        ok, reason = self.selector.validate_option_candidate(1000.0, 2.5)
        self.assertFalse(ok)
        self.assertIn("Penny option trap", reason)


if __name__ == '__main__':
    unittest.main()
