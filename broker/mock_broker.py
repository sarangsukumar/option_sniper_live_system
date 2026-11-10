"""
broker/mock_broker.py
=============================================================================
High-Fidelity Mock & Paper Trading Broker Adapter.
Features:
- Realistic 2-Tick Bid-Ask Friction Simulation:
    Buy orders fill at ceil(LTP + 1 tick)
    Sell orders fill at floor(LTP - 1 tick)
- Full local order lifecycle tracking & fill execution
- Position state and PnL management
=============================================================================
"""

import uuid
from typing import Dict, Any, List, Optional
from broker.base_broker import BaseBroker
from engine.qa_execution_guardrails import round_to_nse_tick, NSE_TICK_SIZE


class MockBroker(BaseBroker):
    def __init__(self, slippage_ticks: int = 1):
        self.slippage_ticks = slippage_ticks
        self.is_connected = False
        self.ltp_table: Dict[str, float] = {}
        self.orders: Dict[str, dict] = {}
        self.positions: Dict[str, dict] = {}

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def set_ltp(self, symbol: str, price: float):
        """Updates simulated market price for a symbol."""
        self.ltp_table[symbol.strip().upper()] = round_to_nse_tick(price, 'nearest')

    def get_ltp(self, symbol: str) -> float:
        sym = symbol.strip().upper()
        return self.ltp_table.get(sym, 100.0)

    def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        price: float = 0.0,
        tag: str = "OPTION_SNIPER"
    ) -> Dict[str, Any]:
        sym = symbol.strip().upper()
        current_ltp = self.get_ltp(sym)
        order_id = f"MOCK_{uuid.uuid4().hex[:8].upper()}"

        # Apply realistic 1 to 2 tick friction
        friction = self.slippage_ticks * NSE_TICK_SIZE
        if side.upper() == "BUY":
            fill_price = round_to_nse_tick(current_ltp + friction, 'ceil')
        else:
            fill_price = round_to_nse_tick(current_ltp - friction, 'floor')

        order_record = {
            "order_id": order_id,
            "symbol": sym,
            "side": side.upper(),
            "quantity": quantity,
            "order_type": order_type.upper(),
            "limit_price": price,
            "fill_price": fill_price,
            "status": "FILLED",
            "tag": tag
        }
        self.orders[order_id] = order_record

        # Update position tracker
        pos = self.positions.get(sym, {
            "symbol": sym,
            "net_quantity": 0,
            "avg_price": 0.0,
            "realized_pnl": 0.0
        })

        if side.upper() == "BUY":
            new_qty = pos["net_quantity"] + quantity
            if new_qty > 0:
                total_cost = (pos["net_quantity"] * pos["avg_price"]) + (quantity * fill_price)
                pos["avg_price"] = round_to_nse_tick(total_cost / new_qty, 'nearest')
            pos["net_quantity"] = new_qty
        elif side.upper() == "SELL":
            closed_qty = min(quantity, pos["net_quantity"])
            pnl = (fill_price - pos["avg_price"]) * closed_qty
            pos["realized_pnl"] += pnl
            pos["net_quantity"] -= quantity

        self.positions[sym] = pos

        return {
            "status": "SUCCESS",
            "order_id": order_id,
            "fill_price": fill_price,
            "message": f"Simulated fill at ₹{fill_price:.2f} (slippage: {self.slippage_ticks} ticks)"
        }

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id]["status"] = "CANCELLED"
            return True
        return False

    def get_positions(self) -> List[Dict[str, Any]]:
        return [p for p in self.positions.values() if p["net_quantity"] != 0]

    def square_off_all(self) -> List[Dict[str, Any]]:
        results = []
        for sym, pos in list(self.positions.items()):
            if pos["net_quantity"] > 0:
                res = self.place_order(sym, pos["net_quantity"], side="SELL", order_type="MARKET", tag="EOD_SQUAREOFF")
                results.append(res)
        return results
