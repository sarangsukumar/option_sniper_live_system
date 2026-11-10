"""
broker/kotak_neo_broker.py
=============================================================================
Kotak Neo API Live Production Broker Adapter.
Connects to Kotak Neo trade API to place, track, and square off F&O Put options.
=============================================================================
"""

import sys
import os
from typing import Dict, Any, List
from broker.base_broker import BaseBroker
from config.settings import (
    KOTAK_CONSUMER_KEY,
    KOTAK_CONSUMER_SECRET,
    KOTAK_MOBILE_NUMBER,
    KOTAK_PASSWORD,
    KOTAK_MPIN
)
from engine.qa_execution_guardrails import round_to_nse_tick


class KotakNeoBroker(BaseBroker):
    def __init__(self):
        self.client = None
        self.is_connected = False

    def connect(self) -> bool:
        """Initializes Kotak Neo client session."""
        try:
            # Check if neo_api is installed
            from neo_api_client import NeoAPI
            self.client = NeoAPI(
                consumer_key=KOTAK_CONSUMER_KEY,
                consumer_secret=KOTAK_CONSUMER_SECRET,
                environment='prod'
            )
            # Authenticate session
            if KOTAK_MOBILE_NUMBER and KOTAK_PASSWORD:
                self.client.login(mobilenumber=KOTAK_MOBILE_NUMBER, password=KOTAK_PASSWORD)
                if KOTAK_MPIN:
                    self.client.session_2fa(OTP=KOTAK_MPIN)
                self.is_connected = True
                return True
            else:
                print("⚠️ Kotak Neo credentials missing in environment.")
                return False
        except ImportError:
            print("⚠️ neo_api_client package not found. KotakNeoBroker will operate in fallback mode.")
            return False
        except Exception as e:
            print(f"⚠️ Kotak Neo connection error: {e}")
            return False

    def get_ltp(self, symbol: str) -> float:
        """Fetches live quotes from Kotak Neo."""
        if not self.is_connected or not self.client:
            return 0.0
        try:
            # Example API call structure for Kotak Neo
            quote = self.client.quotes(instrument_tokens=[{"instrument_token": symbol, "exchange_segment": "nse_fo"}])
            if quote and 'message' in quote:
                return float(quote['message'][0].get('last_price', 0.0))
            return 0.0
        except Exception as e:
            print(f"⚠️ Error fetching Kotak LTP for {symbol}: {e}")
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
        """Places live order on Kotak Neo."""
        if not self.is_connected or not self.client:
            return {"status": "FAILED", "order_id": "", "fill_price": 0.0, "message": "Broker not connected"}

        try:
            tt = "B" if side.upper() == "BUY" else "S"
            ot = "MKT" if order_type.upper() == "MARKET" else "L"
            pr = str(price) if ot == "L" else "0"

            res = self.client.place_order(
                exchange_segment="nse_fo",
                product="MIS",
                price=pr,
                order_type=ot,
                quantity=str(quantity),
                validity="DAY",
                trading_symbol=symbol,
                transaction_type=tt,
                tag=tag
            )
            order_id = res.get("nOrdNo", "")
            return {
                "status": "SUCCESS" if order_id else "FAILED",
                "order_id": order_id,
                "fill_price": price,
                "message": str(res)
            }
        except Exception as e:
            return {"status": "FAILED", "order_id": "", "fill_price": 0.0, "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        if not self.is_connected or not self.client:
            return False
        try:
            self.client.cancel_order(order_id=order_id)
            return True
        except Exception:
            return False

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self.is_connected or not self.client:
            return []
        try:
            pos_resp = self.client.positions()
            return pos_resp.get("data", [])
        except Exception:
            return []

    def square_off_all(self) -> List[Dict[str, Any]]:
        positions = self.get_positions()
        results = []
        for p in positions:
            net_qty = int(p.get("netQty", 0))
            sym = p.get("tradingSymbol", "")
            if net_qty > 0:
                res = self.place_order(sym, net_qty, side="SELL", order_type="MARKET", tag="EOD_SQUAREOFF")
                results.append(res)
        return results
