"""
engine/risk_controller.py
=============================================================================
Option Sniper Risk Governance & Circuit Breakers Module.
Enforces non-negotiable quantitative capital protection rules:
1. Max 2 Option Trades per Day
2. 2-Loss Daily Halt Circuit Breaker (Ceases all trading after 2 losses)
3. Maximum Concurrent Positions Gate (Max 2 simultaneous open trades)
4. Capital-at-Risk Allocation Constraints
5. Zero Averaging Down Rule
6. Confirmation Order Strict Priority Filter
=============================================================================
"""

from typing import Tuple, List, Dict
from config.settings import (
    TOTAL_CAPITAL,
    CAPITAL_PER_TRADE,
    MAX_CONCURRENT_POSITIONS,
    MAX_DAILY_TRADES,
    MAX_CONSECUTIVE_LOSSES_HALT,
    MAX_CONFIRMATION_ORDER,
    TIER1_CONVICTION_STOCKS
)
from engine.qa_execution_guardrails import calculate_option_lots


class RiskController:
    def __init__(
        self,
        total_capital: float = TOTAL_CAPITAL,
        capital_per_trade: float = CAPITAL_PER_TRADE,
        max_concurrent: int = MAX_CONCURRENT_POSITIONS,
        max_daily_trades: int = MAX_DAILY_TRADES,
        max_consecutive_losses: int = MAX_CONSECUTIVE_LOSSES_HALT,
        max_conf_order: int = MAX_CONFIRMATION_ORDER
    ):
        self.total_capital = total_capital
        self.capital_per_trade = capital_per_trade
        self.max_concurrent = max_concurrent
        self.max_daily_trades = max_daily_trades
        self.max_consecutive_losses = max_consecutive_losses
        self.max_conf_order = max_conf_order

        # Runtime daily state tracking
        self.daily_trades_executed: int = 0
        self.consecutive_losses: int = 0
        self.daily_realized_pnl: float = 0.0
        self.circuit_breaker_tripped: bool = False
        self.circuit_breaker_reason: str = ""
        self.active_positions: Dict[str, dict] = {}

    def can_open_new_trade(self, conf_order: int, stock_symbol: str) -> Tuple[bool, str]:
        """
        Validates whether a new trade can be initiated based on risk gates.

        Returns:
        --------
        (bool, str): (allowed, reason)
        """
        # 1. Circuit Breaker Check
        if self.circuit_breaker_tripped:
            return False, f"CIRCUIT BREAKER ACTIVE: {self.circuit_breaker_reason}"

        # 2. Daily Trade Count Limit
        if self.daily_trades_executed >= self.max_daily_trades:
            return False, f"Daily trade limit reached ({self.daily_trades_executed}/{self.max_daily_trades})"

        # 3. Concurrent Positions Limit
        if len(self.active_positions) >= self.max_concurrent:
            return False, f"Max concurrent positions reached ({len(self.active_positions)}/{self.max_concurrent})"

        # 4. Confirmation Order Filter
        if conf_order > self.max_conf_order:
            return False, f"Confirmation Order #{conf_order} exceeds allowed priority (max #{self.max_conf_order})"

        # 5. Duplicate Stock Filter
        if stock_symbol.upper() in self.active_positions:
            return False, f"Position already active for {stock_symbol.upper()} (Zero Averaging Down rule)"

        return True, "Trade permitted under risk governance"

    def compute_position_size(self, premium: float, lot_size: int, stock_symbol: str) -> int:
        """
        Calculates optimal discrete lot size for the trade.
        Applies Tier-1 conviction bonus if stock is in 100% WR Club.
        """
        stock_clean = stock_symbol.strip().upper()

        # Allocate capital per trade
        alloc = self.capital_per_trade
        # Tier-1 bonus: up to 1.35x capital if available in total account
        if stock_clean in TIER1_CONVICTION_STOCKS:
            alloc = min(self.total_capital * 0.45, alloc * 1.35)

        lots = calculate_option_lots(
            allocated_capital=alloc,
            premium_cmp=premium,
            lot_size=lot_size
        )
        return lots

    def record_trade_entry(self, trade_id: str, trade_info: dict):
        """Registers a newly opened trade in active tracker."""
        self.active_positions[trade_info['stock'].upper()] = trade_info
        self.daily_trades_executed += 1

    def record_trade_exit(self, stock_symbol: str, realized_pnl: float):
        """
        Updates risk metrics on trade exit.
        Triggers circuit breaker if consecutive losses threshold reached.
        """
        stock_clean = stock_symbol.strip().upper()
        if stock_clean in self.active_positions:
            del self.active_positions[stock_clean]

        self.daily_realized_pnl += realized_pnl

        if realized_pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.circuit_breaker_tripped = True
                self.circuit_breaker_reason = (
                    f"2-Loss Daily Halt: {self.consecutive_losses} consecutive losses occurred today. "
                    f"Halting trading to protect capital."
                )
        else:
            self.consecutive_losses = 0

    def reset_daily_state(self):
        """Resets counters for the next trading day."""
        self.daily_trades_executed = 0
        self.consecutive_losses = 0
        self.daily_realized_pnl = 0.0
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = ""
        self.active_positions.clear()

    def get_status_summary(self) -> dict:
        """Returns snapshot of current risk metrics."""
        return {
            "daily_trades_executed": self.daily_trades_executed,
            "max_daily_trades": self.max_daily_trades,
            "active_positions_count": len(self.active_positions),
            "consecutive_losses": self.consecutive_losses,
            "circuit_breaker_tripped": self.circuit_breaker_tripped,
            "circuit_breaker_reason": self.circuit_breaker_reason,
            "daily_realized_pnl": round(self.daily_realized_pnl, 2)
        }
