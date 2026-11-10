"""
broker/kotak_neo_broker.py
=============================================================================
Kotak Neo API Live Production Broker Adapter.
Connects to Kotak Neo trade API to place, track, and square off F&O Put options.
Supports auto-loading credentials from kotak_auth_userid.csv for Amrit / Manisha
with TOTP 2FA + MPIN session initialization.
=============================================================================
"""

import sys
import os
from typing import Dict, Any, List, Optional
import pandas as pd
import pyotp

from broker.base_broker import BaseBroker
from config.settings import (
    KOTAK_AUTH_CSV,
    KOTAK_TARGET_USER,
    KOTAK_USER_ID,
    KOTAK_CONSUMER_KEY,
    KOTAK_CONSUMER_SECRET,
    KOTAK_MOBILE_NUMBER,
    KOTAK_PASSWORD,
    KOTAK_MPIN,
    KOTAK_TOTP_SECRET,
    KOTAK_ORDER_PRODUCT
)
from engine.qa_execution_guardrails import round_to_nse_tick


class KotakNeoBroker(BaseBroker):
    def __init__(self):
        self.client = None
        self.is_connected = False
        self.ucc = KOTAK_USER_ID
        self.user_name = KOTAK_TARGET_USER
        self.available_margin = 0.0

    def _load_auth_credentials(self) -> Dict[str, str]:
        """
        Loads Kotak Neo credentials from CSV file or environment variables.
        Priority:
        1. kotak_auth_userid.csv matching user/UCC (Amrit/Manisha / ZCK30)
        2. Environment variables
        """
        creds = {
            "consumer_key": KOTAK_CONSUMER_KEY,
            "consumer_secret": KOTAK_CONSUMER_SECRET,
            "mobile_number": KOTAK_MOBILE_NUMBER,
            "password": KOTAK_PASSWORD,
            "mpin": KOTAK_MPIN,
            "totp_secret": KOTAK_TOTP_SECRET,
            "userid": self.ucc,
            "user_name": self.user_name
        }

        # Check if auth CSV exists
        if os.path.exists(KOTAK_AUTH_CSV):
            try:
                df = pd.read_csv(KOTAK_AUTH_CSV)
                df.columns = df.columns.str.strip()

                target_row = None
                # Match by userid or username
                for _, r in df.iterrows():
                    u_id = str(r.get("userid", "")).strip()
                    k_user = str(r.get("Kotak_user", "")).strip().upper()
                    api_user = str(r.get("user_from_API", "")).strip().upper()

                    if (self.ucc and u_id.upper() == self.ucc.upper()) or \
                       (self.user_name and (self.user_name.upper() in [k_user, api_user])):
                        target_row = r
                        break

                if target_row is None and len(df) > 0:
                    target_row = df.iloc[0]

                if target_row is not None:
                    creds["consumer_key"] = str(target_row.get("consumer_key", creds["consumer_key"])).strip()
                    creds["consumer_secret"] = str(target_row.get("consumer_secret", creds["consumer_secret"])).strip()
                    creds["mobile_number"] = str(target_row.get("mobile_number", creds["mobile_number"])).strip()
                    creds["password"] = str(target_row.get("password", creds["password"])).strip()
                    creds["mpin"] = str(int(target_row.get("MPIN", creds["mpin"]))).strip() if pd.notna(target_row.get("MPIN")) else creds["mpin"]
                    creds["totp_secret"] = str(target_row.get("totp_secret", creds["totp_secret"])).strip()
                    creds["userid"] = str(target_row.get("userid", creds["userid"])).strip()
                    creds["user_name"] = str(target_row.get("user_from_API", target_row.get("Kotak_user", creds["user_name"]))).strip()
            except Exception as e:
                print(f"⚠️ Error reading Kotak auth CSV ({KOTAK_AUTH_CSV}): {e}")

        return creds

    def connect(self) -> bool:
        """Initializes Kotak Neo client session with TOTP 2FA validation."""
        try:
            from neo_api_client import NeoAPI

            creds = self._load_auth_credentials()
            consumer_key = creds["consumer_key"]
            mobile_number = creds["mobile_number"]
            mpin = creds["mpin"]
            totp_secret = creds["totp_secret"]
            userid = creds["userid"]
            self.ucc = userid
            self.user_name = creds["user_name"]

            if not consumer_key or not mobile_number or not mpin or not totp_secret:
                print(f"⚠️ Incomplete Kotak Neo credentials for {self.user_name} ({userid}).")
                return False

            # Initialize NeoAPI client
            self.client = NeoAPI(
                consumer_key=consumer_key,
                environment='prod',
                neo_fin_key='neotradeapi'
            )

            # Generate TOTP code
            totp_code = pyotp.TOTP(totp_secret).now()
            formatted_mobile = mobile_number if mobile_number.startswith('+') else f'+91{mobile_number}'

            # Step 1: TOTP Login
            lr = self.client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
            if lr and 'error' in lr:
                print(f"❌ Kotak Neo TOTP login error: {lr.get('error')}")
                return False

            # Step 2: MPIN Validation
            vr = self.client.totp_validate(mpin=mpin)
            if vr and 'error' in vr:
                print(f"❌ Kotak Neo MPIN validation error: {vr.get('error')}")
                return False

            # Step 3: Verify Margin & Limits
            try:
                limits = self.client.limits()
                if isinstance(limits, dict) and limits.get("stat") == "Ok":
                    self.available_margin = float(limits.get("Net", 0.0))
            except Exception:
                self.available_margin = 0.0

            self.is_connected = True
            print(f"✅ Kotak Neo connected successfully for User: {self.user_name} (UCC: {self.ucc}) | Net Margin: ₹{self.available_margin:,.2f}")
            return True

        except ImportError:
            print("⚠️ neo_api_client package not found. KotakNeoBroker will operate in fallback mode.")
            return False
        except Exception as e:
            print(f"⚠️ Kotak Neo connection error for {self.user_name}: {e}")
            return False

    def get_ltp(self, symbol: str) -> float:
        """Fetches live quotes from Kotak Neo."""
        if not self.is_connected or not self.client:
            return 0.0
        try:
            quote = self.client.quotes(instrument_tokens=[{"instrument_token": symbol, "exchange_segment": "nse_fo"}])
            if quote and 'message' in quote and len(quote['message']) > 0:
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
            pr = str(round_to_nse_tick(price, "floor")) if ot == "L" else "0"

            res = self.client.place_order(
                exchange_segment="nse_fo",
                product=KOTAK_ORDER_PRODUCT,
                price=pr,
                order_type=ot,
                quantity=str(quantity),
                validity="DAY",
                trading_symbol=symbol,
                transaction_type=tt,
                amo="NO",
                disclosed_quantity="0",
                trigger_price="0",
                tag=tag
            )

            order_id = ""
            if isinstance(res, dict):
                order_id = res.get("nOrdNo", res.get("order_id", ""))
                is_ok = res.get("stat") == "Ok" or res.get("stCode") == 200 or bool(order_id)
            else:
                is_ok = False

            return {
                "status": "SUCCESS" if (is_ok or order_id) else "FAILED",
                "order_id": order_id,
                "fill_price": price,
                "message": str(res)
            }
        except Exception as e:
            return {"status": "FAILED", "order_id": "", "fill_price": 0.0, "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """Cancels open order."""
        if not self.is_connected or not self.client:
            return False
        try:
            self.client.cancel_order(order_id=order_id)
            return True
        except Exception:
            return False

    def get_positions(self) -> List[Dict[str, Any]]:
        """Retrieves active positions from Kotak Neo."""
        if not self.is_connected or not self.client:
            return []
        try:
            pos_resp = self.client.positions()
            if isinstance(pos_resp, dict) and isinstance(pos_resp.get("data"), list):
                return pos_resp.get("data", [])
            return []
        except Exception:
            return []

    def square_off_all(self) -> List[Dict[str, Any]]:
        """Squares off all open positions."""
        positions = self.get_positions()
        results = []
        for p in positions:
            net_qty = int(p.get("netQty", 0))
            sym = p.get("tradingSymbol", "")
            if net_qty > 0:
                res = self.place_order(sym, net_qty, side="SELL", order_type="MARKET", tag="EOD_SQUAREOFF")
                results.append(res)
        return results
