"""
engine/strike_selector.py
=============================================================================
Option Strike Selection & Contract Resolver Engine.
Responsibilities:
- Calculates exact exchange step sizes from underlying stock CMP
- Determines At-The-Money (ATM) Put strike price
- Resolves active monthly expiry date from SEBI master calendar
- Applies the Expiry Week Rollover Rule (rolls to Next Month if DTE <= 3 days)
- Maps exchange trading symbols and lot sizes
=============================================================================
"""

import os
import re
from datetime import datetime, date
from pathlib import Path
import pandas as pd
from config.settings import LOT_SIZE_CSV, EXPIRY_DATES_CSV, EXPIRY_DATES_TXT, MIN_OPTION_PREMIUM, EXPIRY_SKIP_DTE_THRESHOLD


class StrikeSelector:
    def __init__(self, lot_size_csv=LOT_SIZE_CSV, expiry_csv=EXPIRY_DATES_CSV, expiry_txt=EXPIRY_DATES_TXT):
        self.lot_size_csv = Path(lot_size_csv)
        self.expiry_csv = Path(expiry_csv)
        self.expiry_txt = Path(expiry_txt) if expiry_txt else None
        self.lot_sizes = {}
        self.expiries = []
        self._load_lot_sizes()
        self._load_expiries()

    def _load_lot_sizes(self):
        """Loads stock contract lot sizes from CSV."""
        if not self.lot_size_csv.exists():
            return

        try:
            df = pd.read_csv(self.lot_size_csv)
            # Find column names
            stock_col = 'stockname' if 'stockname' in df.columns else df.columns[0]
            lot_col = 'lotsize' if 'lotsize' in df.columns else df.columns[2]

            for _, row in df.iterrows():
                symbol = str(row[stock_col]).strip().upper()
                try:
                    lotsize = int(row[lot_col])
                    self.lot_sizes[symbol] = lotsize
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            print(f"⚠️ Warning loading lot sizes: {e}")

    def _load_expiries(self):
        """Loads and sorts master expiry dates dynamically from live expiry_dates.txt and CSV fallback."""
        clean_dates = []

        # 1. Primary Dynamic Source: Live daily-updated expiry_dates.txt
        if self.expiry_txt and self.expiry_txt.exists():
            try:
                with open(self.expiry_txt, 'r') as f:
                    content = f.read()
                if 'expiryDatesList' in content:
                    start = content.find('"') + 1
                    end = content.rfind('"')
                    dates_str = content[start:end]
                else:
                    dates_str = content

                for d in dates_str.split(','):
                    d_clean = d.strip().replace('"', '').replace("'", "").replace(';', '')
                    if d_clean:
                        try:
                            clean_dates.append(pd.to_datetime(d_clean).strftime('%Y-%m-%d'))
                        except Exception:
                            pass
            except Exception as e:
                print(f"⚠️ Warning loading dynamic expiry txt ({self.expiry_txt}): {e}")

        # 2. Historical & Backup Fallback: master_expiry_dates.csv
        if self.expiry_csv and self.expiry_csv.exists():
            try:
                df = pd.read_csv(self.expiry_csv)
                col = 'master_expiry_date' if 'master_expiry_date' in df.columns else df.columns[0]
                raw_dates = df[col].dropna().astype(str).str.strip().tolist()

                for d in raw_dates:
                    try:
                        clean_dates.append(pd.to_datetime(d).strftime('%Y-%m-%d'))
                    except Exception:
                        pass
            except Exception as e:
                print(f"⚠️ Warning loading expiries CSV: {e}")

        self.expiries = sorted(list(set(clean_dates)))

    def get_lot_size(self, symbol: str, default: int = 500) -> int:
        """Returns standard exchange lot size for the stock."""
        clean_sym = symbol.strip().upper()
        return self.lot_sizes.get(clean_sym, default)

    @staticmethod
    def get_step_size(cmp: float) -> float:
        """
        Determines NSE strike step size based on current market price (CMP).
        """
        if cmp > 2500:
            return 50.0
        elif cmp > 1000:
            return 20.0
        elif cmp > 500:
            return 10.0
        elif cmp > 250:
            return 5.0
        elif cmp > 100:
            return 2.5
        else:
            return 1.0

    def calculate_atm_strike(self, cmp: float, step: float = None) -> float:
        """
        Calculates nearest At-The-Money (ATM) strike price.
        """
        if step is None:
            step = self.get_step_size(cmp)
        raw_strike = round(cmp / step) * step
        # If step is integer, return float with no fractional residue
        if step >= 5:
            return float(int(raw_strike))
        return round(raw_strike, 1)

    def calculate_itm_strike(self, cmp: float, steps_in: int = 1) -> float:
        """
        Calculates In-The-Money (ITM) Put strike price (higher strike than ATM).
        For Put: ITM = ATM + (steps_in * step)
        """
        step = self.get_step_size(cmp)
        atm = self.calculate_atm_strike(cmp, step)
        return atm + (steps_in * step)

    def calculate_dte(self, trade_date: str = None, expiry_date: str = None) -> int:
        """
        Calculates calendar Days to Expiry (DTE).
        """
        if trade_date is None:
            trade_dt = date.today()
        else:
            trade_dt = pd.to_datetime(trade_date).date()

        if expiry_date is None:
            expiry_date = self.get_active_expiry(trade_date)

        exp_dt = pd.to_datetime(expiry_date).date()
        return (exp_dt - trade_dt).days

    def is_expiry_lockout(self, trade_date: str = None, expiry_date: str = None) -> tuple:
        """
        Enforces the Last-4-Days Before Monthly Expiry Skip Rule from the Simulation Report:
        - Put Options within <= 4 calendar days of monthly expiry suffer severe theta decay
          and gamma whipsaws.
        - Trades within <= 4 calendar days are strictly skipped (NOT rolled to next month).

        Returns:
        --------
        (is_lockout: bool, dte: int)
        """
        dte = self.calculate_dte(trade_date, expiry_date)
        return (dte <= EXPIRY_SKIP_DTE_THRESHOLD, dte)

    def get_active_expiry(self, trade_date: str = None) -> str:
        """
        Determines current active monthly expiry date.
        Strict Simulation Rule: Uses the current monthly expiry directly.
        (If DTE <= 4 days, trading is strictly skipped by the risk governor,
        never rolled into the next month).
        """
        if trade_date is None:
            trade_dt = date.today()
        else:
            trade_dt = pd.to_datetime(trade_date).date()

        future_expiries = [
            pd.to_datetime(e).date() for e in self.expiries
            if pd.to_datetime(e).date() >= trade_dt
        ]

        if not future_expiries:
            # Fallback to last Thursday of current month
            return (trade_dt.replace(day=28)).strftime('%Y-%m-%d')

        nearest_expiry = future_expiries[0]
        return nearest_expiry.strftime('%Y-%m-%d')

    def build_option_symbol(
        self,
        stock_symbol: str,
        strike: float,
        opt_type: str = "PE",
        expiry_date: str = None,
        trade_date: str = None
    ) -> dict:
        """
        Builds standardized option symbols for NSE and brokers.

        Returns:
        --------
        dict with keys:
          - 'stock': Stock symbol (e.g. 'TECHM')
          - 'strike': Strike price (e.g. 1600.0)
          - 'opt_type': 'PE' or 'CE'
          - 'expiry': YYYY-MM-DD
          - 'nse_symbol': Standard NSE format (e.g. 'TECHM26NOV1600PE')
          - 'display_name': Clean readable representation
        """
        stock_clean = stock_symbol.strip().upper()
        if expiry_date is None:
            expiry_date = self.get_active_expiry(trade_date)

        exp_dt = pd.to_datetime(expiry_date)
        exp_year = exp_dt.strftime('%y')   # '26'
        exp_month = exp_dt.strftime('%b').upper() # 'NOV'

        # Format strike string
        if strike == int(strike):
            strike_str = str(int(strike))
        else:
            strike_str = f"{strike:.1f}"

        nse_symbol = f"{stock_clean}{exp_year}{exp_month}{strike_str}{opt_type}"
        display_name = f"{stock_clean} {strike_str} {opt_type} ({exp_month} {exp_year})"

        return {
            "stock": stock_clean,
            "strike": strike,
            "opt_type": opt_type,
            "expiry": expiry_date,
            "nse_symbol": nse_symbol,
            "display_name": display_name,
            "lot_size": self.get_lot_size(stock_clean)
        }

    def validate_option_candidate(self, cmp: float, premium: float, trade_date: str = None) -> tuple:
        """
        Pre-trade sanity checks:
        - Prevents penny option traps (premium < MIN_OPTION_PREMIUM).
        - Verifies valid positive CMP.
        - Enforces DTE <= 4 days Expiry Skip Rule from Simulation.

        Returns:
        --------
        (bool, str): (is_valid, reason)
        """
        if cmp <= 0:
            return False, f"Invalid underlying CMP: {cmp}"
        if premium is not None and premium < MIN_OPTION_PREMIUM:
            return False, f"Penny option trap: Premium ₹{premium} < ₹{MIN_OPTION_PREMIUM}"

        # Strict Simulation Expiry Skip Rule
        is_lockout, dte = self.is_expiry_lockout(trade_date)
        if is_lockout:
            return False, f"EXPIRY_LOCKOUT: DTE ({dte}d) <= {EXPIRY_SKIP_DTE_THRESHOLD}d. Strict Expiry Skip Rule from Simulation (no trading within 4 days of expiry)."

        return True, "Valid candidate"
