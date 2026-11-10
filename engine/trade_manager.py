"""
engine/trade_manager.py
=============================================================================
Option Position Lifecycle & Dynamic Exit Manager.
Responsibilities:
- Tracks live position state (entry price, quantity, current PnL)
- Dynamic Floor Lock: Automatically locks Stop-Loss to Break-Even at +18% gain
- Take-Profit Target (+38% gain)
- Hard Stop-Loss (-15% option premium drop)
- Underlying Stock Price Reversal Guardrail (+0.8% stock bounce)
- Mandatory 15:15 IST Square-Off Execution
=============================================================================
"""

from typing import Tuple, Optional
from datetime import datetime
from config.settings import (
    STOP_LOSS_PCT,
    FLOOR_LOCK_GAIN_PCT,
    TAKE_PROFIT_PCT,
    UNDERLYING_SL_PCT,
    MANDATORY_SQUAREOFF_TIME
)
from engine.qa_execution_guardrails import round_to_nse_tick


class ManagedOptionPosition:
    def __init__(
        self,
        trade_id: str,
        stock: str,
        option_symbol: str,
        strike: float,
        opt_type: str,
        expiry: str,
        entry_price: float,
        underlying_entry_price: float,
        quantity: int,
        entry_time: str,
        conf_order: int
    ):
        self.trade_id = trade_id
        self.stock = stock.upper()
        self.option_symbol = option_symbol
        self.strike = strike
        self.opt_type = opt_type
        self.expiry = expiry
        self.entry_price = round_to_nse_tick(entry_price, 'ceil')
        self.underlying_entry_price = underlying_entry_price
        self.quantity = quantity
        self.entry_time = entry_time
        self.conf_order = conf_order

        # Dynamic exit levels
        self.hard_sl = round_to_nse_tick(self.entry_price * (1.0 - STOP_LOSS_PCT), 'floor')
        self.target_tp = round_to_nse_tick(self.entry_price * (1.0 + TAKE_PROFIT_PCT), 'floor')
        self.current_sl = self.hard_sl
        self.floor_locked = False

        # Status tracking
        self.highest_ltp = self.entry_price
        self.exit_price: Optional[float] = None
        self.exit_time: Optional[str] = None
        self.exit_reason: Optional[str] = None
        self.is_closed = False

    def update_price(
        self,
        current_option_ltp: float,
        current_underlying_ltp: float,
        current_time_str: str = None
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Evaluates active position against dynamic exit triggers.

        Returns:
        --------
        (should_exit, exit_reason, exit_price)
        """
        if self.is_closed:
            return False, None, None

        if current_time_str is None:
            current_time_str = datetime.now().strftime("%H:%M:%S")

        # Track high watermark
        if current_option_ltp > self.highest_ltp:
            self.highest_ltp = current_option_ltp

        # 1. Floor Lock Trigger: At +18% gain, advance SL to Break-Even (+0.5%)
        if not self.floor_locked:
            gain_pct = (current_option_ltp - self.entry_price) / self.entry_price
            if gain_pct >= FLOOR_LOCK_GAIN_PCT:
                self.floor_locked = True
                be_sl = round_to_nse_tick(self.entry_price * 1.005, 'floor')
                self.current_sl = max(self.current_sl, be_sl)

        # 2. Check Take-Profit Target Hit
        if current_option_ltp >= self.target_tp:
            exit_px = round_to_nse_tick(current_option_ltp, 'floor')
            self._close_position(exit_px, current_time_str, "TAKE_PROFIT")
            return True, "TAKE_PROFIT", exit_px

        # 3. Check Current Stop-Loss Hit (Hard SL or Floor-Locked BE)
        if current_option_ltp <= self.current_sl:
            exit_px = round_to_nse_tick(current_option_ltp, 'floor')
            reason = "FLOOR_LOCK_SL" if self.floor_locked else "HARD_STOP_LOSS"
            self._close_position(exit_px, current_time_str, reason)
            return True, reason, exit_px

        # 4. Underlying Stock Reversal SL (+0.8% rise above entry price)
        if self.underlying_entry_price > 0:
            stock_reversal_pct = (current_underlying_ltp - self.underlying_entry_price) / self.underlying_entry_price
            if stock_reversal_pct >= UNDERLYING_SL_PCT:
                exit_px = round_to_nse_tick(current_option_ltp, 'floor')
                self._close_position(exit_px, current_time_str, "UNDERLYING_SL_REVERSAL")
                return True, "UNDERLYING_SL_REVERSAL", exit_px

        # 5. Mandatory 15:15 IST Time Stop
        if current_time_str >= MANDATORY_SQUAREOFF_TIME:
            exit_px = round_to_nse_tick(current_option_ltp, 'floor')
            self._close_position(exit_px, current_time_str, "TIME_SQUAREOFF_1515")
            return True, "TIME_SQUAREOFF_1515", exit_px

        return False, None, None

    def _close_position(self, exit_price: float, exit_time: str, reason: str):
        self.is_closed = True
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason

    def get_realized_pnl(self) -> float:
        """Computes gross realized PnL."""
        if not self.is_closed or self.exit_price is None:
            return 0.0
        return round((self.exit_price - self.entry_price) * self.quantity, 2)

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "stock": self.stock,
            "option_symbol": self.option_symbol,
            "strike": self.strike,
            "opt_type": self.opt_type,
            "expiry": self.expiry,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "underlying_entry_price": self.underlying_entry_price,
            "entry_time": self.entry_time,
            "conf_order": self.conf_order,
            "hard_sl": self.hard_sl,
            "current_sl": self.current_sl,
            "target_tp": self.target_tp,
            "floor_locked": self.floor_locked,
            "highest_ltp": self.highest_ltp,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time,
            "exit_reason": self.exit_reason,
            "is_closed": self.is_closed,
            "gross_pnl": self.get_realized_pnl()
        }
