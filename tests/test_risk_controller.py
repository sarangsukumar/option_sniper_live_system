"""
tests/test_risk_controller.py
Unit tests for risk governance, circuit breakers, and position constraints.
"""

import unittest
from engine.risk_controller import RiskController


class TestRiskController(unittest.TestCase):
    def setUp(self):
        self.risk = RiskController(
            total_capital=100000.0,
            capital_per_trade=35000.0,
            max_concurrent=2,
            max_daily_trades=2,
            max_consecutive_losses=2,
            max_conf_order=1
        )

    def test_conf_order_filter(self):
        # Conf #1 allowed
        ok, _ = self.risk.can_open_new_trade(conf_order=1, stock_symbol="TECHM")
        self.assertTrue(ok)
        # Conf #2 rejected when max_conf_order == 1
        ok, reason = self.risk.can_open_new_trade(conf_order=2, stock_symbol="GLENMARK")
        self.assertFalse(ok)
        self.assertIn("exceeds allowed priority", reason)

    def test_daily_trades_limit(self):
        self.risk.record_trade_entry("T1", {"stock": "TECHM"})
        self.risk.record_trade_entry("T2", {"stock": "GLENMARK"})
        ok, reason = self.risk.can_open_new_trade(conf_order=1, stock_symbol="POLYCAB")
        self.assertFalse(ok)
        self.assertIn("Daily trade limit reached", reason)

    def test_circuit_breaker_2_losses(self):
        self.risk.record_trade_entry("T1", {"stock": "TECHM"})
        self.risk.record_trade_exit("TECHM", realized_pnl=-3500.0)
        self.assertFalse(self.risk.circuit_breaker_tripped)

        self.risk.record_trade_entry("T2", {"stock": "GLENMARK"})
        self.risk.record_trade_exit("GLENMARK", realized_pnl=-2800.0)
        self.assertTrue(self.risk.circuit_breaker_tripped)
        self.assertIn("2-Loss Daily Halt", self.risk.circuit_breaker_reason)


    def test_position_sizing_1lot_and_capital(self):
        # 1-Lot mode (default)
        lots_1lot = self.risk.compute_position_size(premium=35.0, lot_size=600, stock_symbol="TECHM")
        self.assertEqual(lots_1lot, 1)

        # 1L Capital dynamic mode
        risk_cap = RiskController(
            total_capital=100000.0,
            capital_per_trade=100000.0,
            lot_sizing_mode="1L_CAPITAL"
        )
        # Neutral stock (INFY): premium 35.0, lot 600 -> contract cost 21,000 -> 100k / 21k = 4.76 -> 4 lots
        lots_cap = risk_cap.compute_position_size(premium=35.0, lot_size=600, stock_symbol="INFY")
        self.assertGreaterEqual(lots_cap, 4)

        # Tier-1 stock (TECHM): capital capped at 45% of total account (45,000) -> 45k / 21k = 2 lots
        lots_tier1 = risk_cap.compute_position_size(premium=35.0, lot_size=600, stock_symbol="TECHM")
        self.assertEqual(lots_tier1, 2)


if __name__ == '__main__':
    unittest.main()
