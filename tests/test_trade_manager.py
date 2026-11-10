"""
tests/test_trade_manager.py
Unit tests for position management, trailing floor lock, and SL/TP exits.
"""

import unittest
from engine.trade_manager import ManagedOptionPosition


class TestTradeManager(unittest.TestCase):
    def setUp(self):
        self.pos = ManagedOptionPosition(
            trade_id="TEST_01",
            stock="TECHM",
            option_symbol="TECHM26NOV1680PE",
            strike=1680.0,
            opt_type="PE",
            expiry="2026-11-26",
            entry_price=40.0,
            underlying_entry_price=1680.0,
            quantity=500,
            entry_time="09:42:00",
            conf_order=1
        )

    def test_initial_sl_tp(self):
        # Entry 40.0 -> SL at -15% = 34.0, TP at +38% = 55.20
        self.assertEqual(self.pos.entry_price, 40.0)
        self.assertEqual(self.pos.hard_sl, 34.0)
        self.assertEqual(self.pos.target_tp, 55.20)
        self.assertFalse(self.pos.floor_locked)

    def test_floor_lock_activation(self):
        # Premium rises to 48.0 (+20% gain > +18% threshold)
        should_exit, reason, _ = self.pos.update_price(48.0, 1665.0, "10:00:00")
        self.assertFalse(should_exit)
        self.assertTrue(self.pos.floor_locked)
        # SL should now be advanced to Break-Even (at least 40.20)
        self.assertGreaterEqual(self.pos.current_sl, 40.20)

    def test_take_profit_exit(self):
        # Premium reaches 56.0 (>= 55.20 TP)
        should_exit, reason, exit_px = self.pos.update_price(56.0, 1650.0, "10:15:00")
        self.assertTrue(should_exit)
        self.assertEqual(reason, "TAKE_PROFIT")
        self.assertGreater(self.pos.get_realized_pnl(), 0)

    def test_hard_sl_exit(self):
        # Premium crashes to 33.0 (<= 34.0 Hard SL)
        should_exit, reason, exit_px = self.pos.update_price(33.0, 1690.0, "09:50:00")
        self.assertTrue(should_exit)
        self.assertEqual(reason, "HARD_STOP_LOSS")
        self.assertLess(self.pos.get_realized_pnl(), 0)


if __name__ == '__main__':
    unittest.main()
