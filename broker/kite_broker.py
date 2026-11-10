"""
broker/kite_broker.py
=============================================================================
Zerodha Kite Connect Live Broker Adapter.
Connects to Kite Connect API for live F&O option order placement.
=============================================================================
"""

from typing import Dict, Any, List
from broker.base_broker import BaseBroker
from config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN
from engine.qa_execution_guardrails import round_to_nse_tick


class KiteBroker(BaseBroker):
    def __init__(self):
        self.kite = None
        self.is_connected = False

    def connect(self) -> bool:
        try:
            from kiteconnect import KiteConnect
            if KITE_API_KEY and KITE_ACCESS_TOKEN:
                self.kite = KiteConnect(api_key=KITE_API_KEY)
                self.kite.set_access_token(KITE_ACCESS_TOKEN)
                self.is_connected = True
                return True
            else:
                print("⚠️ Kite API credentials missing in environment.")
                return False
        except ImportError:
            print("⚠️ kiteconnect package not installed.")
            return False
        except Exception as e:
            print(f"⚠️ Kite connection error: {e}")
            return False

    def get_ltp(self, symbol: str) -> float:
        if not self.is_connected or not self.kite:
            return 0.0
        try:
            instrument = f"NFO:{symbol}"
            quote = self.kite.ltp(instrument)
            return float(quote.get(instrument, {}).get("last_price", 0.0))
        except Exception:
            return 0.0

    def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        price: float = 0.0,
        tag: str = "OPTION_SNIPER"
    ) -> Dict[str, Any]:
        if not self.is_connected or not self.kite:
            return {"status": "FAILED", "order_id": "", "fill_price": 0.0, "message": "Kite not connected"}

        try:
            transaction_type = self.kite.TRANSACTION_TYPE_BUY if side.upper() == "BUY" else self.kite.TRANSACTION_TYPE_SELL
            order_type_kite = self.kite.ORDER_TYPE_MARKET if order_type.upper() == "MARKET" else self.kite.ORDER_TYPE_LIMIT

            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange=self.kite.EXCHANGE_NFO,
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=self.kite.PRODUCT_MIS,
                order_type=order_type_kite,
                price=price if order_type_kite == self.kite.ORDER_TYPE_LIMIT else None,
                tag=tag[:20]
            )
            return {
                "status": "SUCCESS",
                "order_id": str(order_id),
                "fill_price": price,
                "message": f"Kite order placed successfully: {order_id}"
            }
        except Exception as e:
            return {"status": "FAILED", "order_id": "", "fill_price": 0.0, "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        if not self.is_connected or not self.kite:
            return False
        try:
            self.kite.cancel_order(variety=self.kite.VARIETY_REGULAR, order_id=order_id)
            return True
        except Exception:
            return False

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self.is_connected or not self.kite:
            return []
        try:
            res = self.kite.positions()
            return res.get("net", [])
        except Exception:
            return []

    def square_off_all(self) -> List[Dict[str, Any]]:
        positions = self.get_positions()
        results = []
        for p in positions:
            net_qty = int(p.get("quantity", 0))
            sym = p.get("tradingsymbol", "")
            if net_qty > 0:
                res = self.place_order(sym, net_qty, side="SELL", order_type="MARKET", tag="EOD_SQUAREOFF")
                results.append(res)
        return results
