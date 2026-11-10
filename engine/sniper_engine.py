"""
engine/sniper_engine.py
=============================================================================
Option Sniper Master Production Engine.
The primary runtime orchestrator coordinating:
- Morning ML scoring & watchlist generation (09:20 / 09:40)
- Candle low breakdown confirmation detection (09:42 - 10:45)
- Confirmation #1 Priority filtering
- Automatic ATM Put strike selection
- Broker order routing & fill verification
- Real-time dynamic position tracking & floor lock
- EOD square-off & ledger persistence
=============================================================================
"""

import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from config.settings import (
    TOTAL_CAPITAL,
    CAPITAL_PER_TRADE,
    MAX_CONCURRENT_POSITIONS,
    MAX_DAILY_TRADES,
    MAX_CONFIRMATION_ORDER,
    MANDATORY_SQUAREOFF_TIME,
    DRY_RUN
)
from engine.strike_selector import StrikeSelector
from engine.risk_controller import RiskController
from engine.trade_manager import ManagedOptionPosition
from models.model_loader import ModelLoader
from broker.base_broker import BaseBroker
from telemetry.telegram_notifier import TelegramNotifier
from storage.ledger import TradeLedger


class OptionSniperEngine:
    def __init__(
        self,
        broker: BaseBroker,
        dry_run: bool = DRY_RUN
    ):
        self.broker = broker
        self.dry_run = dry_run

        self.strike_selector = StrikeSelector()
        self.risk_controller = RiskController()
        self.model_loader = ModelLoader()
        self.notifier = TelegramNotifier()
        self.ledger = TradeLedger()

        self.watchlist: List[dict] = []
        self.active_positions: Dict[str, ManagedOptionPosition] = {}
        self.confirmation_counter: int = 0
        self.is_running: bool = False

    def initialize(self) -> bool:
        """Connects to broker and verifies environment."""
        print("🔧 Initializing Option Sniper Engine...")
        if not self.broker.connect():
            print("⚠️ Broker connection returned False.")
            return False

        print("✅ Broker connected successfully.")
        print(f"📊 Loaded {len(self.strike_selector.lot_sizes)} F&O lot sizes.")
        print(f"📅 Loaded {len(self.strike_selector.expiries)} master expiry dates.")
        print(f"🤖 Models ready: 09:40 ({self.model_loader.model_0940 is not None}), "
              f"09:20 ({self.model_loader.model_0920 is not None})")
        return True

    def generate_morning_watchlist(self, df_candidates: pd.DataFrame, source: str = "0940") -> List[dict]:
        """
        Scores candidate stocks, ranks by short conviction, and builds option targets.
        """
        print(f"🔍 Generating {source} morning watchlist from {len(df_candidates)} candidates...")
        if source == "0940":
            df_ranked = self.model_loader.score_candidates_0940(df_candidates)
        else:
            df_ranked = self.model_loader.score_candidates_0920(df_candidates)

        # Take Top 4 candidates
        top_candidates = df_ranked.head(4)
        self.watchlist.clear()

        for idx, row in top_candidates.iterrows():
            stock = str(row['stock']).strip().upper()
            cmp = float(row.get('cmp', 1000.0))
            low_0942 = float(row.get('low_0942', cmp * 0.998))

            step = self.strike_selector.get_step_size(cmp)
            atm_strike = self.strike_selector.calculate_atm_strike(cmp, step)
            opt_info = self.strike_selector.build_option_symbol(stock, atm_strike, "PE")

            entry = {
                "rank": idx + 1,
                "stock": stock,
                "cmp": cmp,
                "trigger_price": low_0942,
                "strike": atm_strike,
                "option_symbol": opt_info['nse_symbol'],
                "lot_size": opt_info['lot_size'],
                "confirmed": False
            }
            self.watchlist.append(entry)

        # Alert watchlist via Telegram
        self.notifier.notify_morning_watchlist(self.watchlist)
        return self.watchlist

    def check_candle_breakdowns(self, current_ticks: Dict[str, float]) -> List[dict]:
        """
        Checks if any watchlist candidates have breached below their trigger price.
        Assigns sequential confirmation numbers (Conf #1, Conf #2).
        """
        confirmed_candidates = []
        for item in self.watchlist:
            if item['confirmed']:
                continue

            stock = item['stock']
            cur_price = current_ticks.get(stock)
            if cur_price is None:
                continue

            # Breakdown condition: stock crosses below 09:42 candle low
            if cur_price < item['trigger_price']:
                item['confirmed'] = True
                self.confirmation_counter += 1
                item['conf_order'] = self.confirmation_counter
                item['breakdown_price'] = cur_price
                confirmed_candidates.append(item)
                print(f"🚨 CONFIRMATION #{item['conf_order']}: {stock} broke below ₹{item['trigger_price']:.2f} at ₹{cur_price:.2f}")

        return confirmed_candidates

    def execute_option_entry(self, candidate: dict, option_premium_cmp: float) -> Optional[ManagedOptionPosition]:
        """
        Executes Put Option buy order following risk controls.
        """
        stock = candidate['stock']
        conf_order = candidate['conf_order']

        # 1. Risk Controller Gate
        allowed, reason = self.risk_controller.can_open_new_trade(conf_order, stock)
        if not allowed:
            print(f"🚫 Trade rejected for {stock} (Conf #{conf_order}): {reason}")
            return None

        # 2. Strike Sanity & Penny Option Filter
        valid, val_reason = self.strike_selector.validate_option_candidate(candidate['cmp'], option_premium_cmp)
        if not valid:
            print(f"🚫 Strike invalid for {stock}: {val_reason}")
            return None

        # 3. Position Sizing
        lot_size = candidate['lot_size']
        lots = self.risk_controller.compute_position_size(option_premium_cmp, lot_size, stock)
        total_quantity = lots * lot_size

        if lots < 1 or total_quantity <= 0:
            print(f"🚫 Insufficient capital or zero lots calculated for {stock}")
            return None

        # 4. Place Order via Broker
        option_sym = candidate['option_symbol']
        print(f"🚀 Placing BUY order: {total_quantity} qty of {option_sym} @ ₹{option_premium_cmp:.2f}...")

        if self.dry_run:
            fill_price = option_premium_cmp
            order_id = f"DRY_{uuid.uuid4().hex[:6]}"
            print(f"🧪 [DRY RUN] Order simulated filled: {order_id} @ ₹{fill_price:.2f}")
        else:
            order_res = self.broker.place_order(
                symbol=option_sym,
                quantity=total_quantity,
                side="BUY",
                order_type="MARKET",
                price=option_premium_cmp
            )
            if order_res.get('status') != 'SUCCESS':
                print(f"❌ Order failed: {order_res.get('message')}")
                return None
            fill_price = order_res.get('fill_price', option_premium_cmp)
            order_id = order_res.get('order_id', str(uuid.uuid4()))

        trade_id = f"TRD_{datetime.now().strftime('%Y%m%d')}_{stock}_{conf_order}"
        now_time = datetime.now().strftime("%H:%M:%S")

        # 5. Create Active Position
        position = ManagedOptionPosition(
            trade_id=trade_id,
            stock=stock,
            option_symbol=option_sym,
            strike=candidate['strike'],
            opt_type="PE",
            expiry=self.strike_selector.get_active_expiry(),
            entry_price=fill_price,
            underlying_entry_price=candidate['breakdown_price'],
            quantity=total_quantity,
            entry_time=now_time,
            conf_order=conf_order
        )

        self.active_positions[stock] = position
        self.risk_controller.record_trade_entry(trade_id, position.to_dict())
        self.ledger.record_entry(position.to_dict())

        # Notify via Telegram
        self.notifier.notify_order_filled(position.to_dict())
        return position

    def monitor_and_manage_positions(
        self,
        option_ticks: Dict[str, float],
        underlying_ticks: Dict[str, float],
        current_time_str: str = None
    ):
        """
        Evaluates active positions for exit triggers (TP, SL, Floor Lock, Time Stop).
        """
        if current_time_str is None:
            current_time_str = datetime.now().strftime("%H:%M:%S")

        for stock, pos in list(self.active_positions.items()):
            opt_ltp = option_ticks.get(pos.option_symbol, pos.entry_price)
            stock_ltp = underlying_ticks.get(stock, pos.underlying_entry_price)

            prev_floor_locked = pos.floor_locked
            should_exit, exit_reason, exit_px = pos.update_price(opt_ltp, stock_ltp, current_time_str)

            # Check if floor lock was newly triggered
            if pos.floor_locked and not prev_floor_locked:
                self.notifier.notify_floor_locked(pos.stock, pos.option_symbol, opt_ltp, pos.current_sl)

            if should_exit:
                self._execute_position_exit(pos, exit_px, exit_reason, current_time_str)

    def _execute_position_exit(
        self,
        position: ManagedOptionPosition,
        exit_price: float,
        reason: str,
        current_time_str: str
    ):
        """Liquidates option position and persists results."""
        stock = position.stock
        print(f"🏁 Exiting {stock} ({position.option_symbol}) | Reason: {reason} @ ₹{exit_price:.2f}")

        if not self.dry_run:
            self.broker.place_order(
                symbol=position.option_symbol,
                quantity=position.quantity,
                side="SELL",
                order_type="MARKET",
                price=exit_price,
                tag=reason[:20]
            )

        realized_gross_pnl = position.get_realized_pnl()

        # Update risk controller and ledger
        self.risk_controller.record_trade_exit(stock, realized_gross_pnl)
        self.ledger.record_exit(position.to_dict())

        # Notify via Telegram
        self.notifier.notify_trade_exit(position.to_dict())

        # Remove from active tracker
        if stock in self.active_positions:
            del self.active_positions[stock]

    def square_off_all_eod(self):
        """End-of-day mandatory liquidation at 15:15 IST."""
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"⏰ Initiating 15:15 Mandatory EOD Square-Off...")
        for stock, pos in list(self.active_positions.items()):
            ltp = self.broker.get_ltp(pos.option_symbol)
            pos.update_price(ltp, 0.0, current_time_str=now_str)
            self._execute_position_exit(pos, ltp, "MANDATORY_EOD_SQUAREOFF", now_str)

        # Send daily summary
        summary = self.ledger.get_today_summary()
        summary["circuit_breaker"] = self.risk_controller.circuit_breaker_tripped
        self.notifier.notify_daily_summary(summary)
