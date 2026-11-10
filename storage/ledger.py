"""
storage/ledger.py
=============================================================================
Option Sniper Trade Ledger & Historical Database Persistence.
Dual storage backend:
1. SQLite Database: `data/option_sniper.db`
2. Audit CSV Ledger: `data/daily_trade_ledger.csv`
=============================================================================
"""

import sqlite3
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import Dict, Any, List
from config.settings import DATABASE_PATH, DAILY_LEDGER_CSV
from engine.qa_execution_guardrails import calculate_option_taxes


class TradeLedger:
    def __init__(self, db_path: Path = DATABASE_PATH, csv_path: Path = DAILY_LEDGER_CSV):
        self.db_path = Path(db_path)
        self.csv_path = Path(csv_path)
        self._init_sqlite()

    def _init_sqlite(self):
        """Initializes the SQLite schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE,
                    date TEXT,
                    stock TEXT,
                    option_symbol TEXT,
                    strike REAL,
                    opt_type TEXT,
                    expiry TEXT,
                    conf_order INTEGER,
                    entry_time TEXT,
                    entry_price REAL,
                    underlying_entry_price REAL,
                    quantity INTEGER,
                    hard_sl REAL,
                    target_tp REAL,
                    exit_time TEXT,
                    exit_price REAL,
                    exit_reason TEXT,
                    gross_pnl REAL,
                    total_taxes REAL,
                    net_pnl REAL,
                    return_pct REAL,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def record_entry(self, trade_data: dict):
        """Records a new trade entry in DB."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO option_trades (
                    trade_id, date, stock, option_symbol, strike, opt_type,
                    expiry, conf_order, entry_time, entry_price, underlying_entry_price,
                    quantity, hard_sl, target_tp, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data['trade_id'],
                today_str,
                trade_data['stock'],
                trade_data['option_symbol'],
                trade_data['strike'],
                trade_data['opt_type'],
                trade_data['expiry'],
                trade_data['conf_order'],
                trade_data['entry_time'],
                trade_data['entry_price'],
                trade_data.get('underlying_entry_price', 0.0),
                trade_data['quantity'],
                trade_data.get('hard_sl', 0.0),
                trade_data.get('target_tp', 0.0),
                "OPEN"
            ))
            conn.commit()

    def record_exit(self, exit_data: dict):
        """Updates trade with exit metrics, calculates taxes, and appends to CSV."""
        gross_pnl = exit_data['gross_pnl']
        qty = exit_data['quantity']
        entry_px = exit_data['entry_price']
        exit_px = exit_data['exit_price']

        taxes = calculate_option_taxes(qty, entry_px, exit_px)
        tot_taxes = taxes['total_charges']
        net_pnl = round(gross_pnl - tot_taxes, 2)
        ret_pct = round(((exit_px - entry_px) / entry_px) * 100.0, 2) if entry_px > 0 else 0.0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE option_trades SET
                    exit_time = ?,
                    exit_price = ?,
                    exit_reason = ?,
                    gross_pnl = ?,
                    total_taxes = ?,
                    net_pnl = ?,
                    return_pct = ?,
                    status = 'CLOSED'
                WHERE trade_id = ?
            """, (
                exit_data['exit_time'],
                exit_px,
                exit_data['exit_reason'],
                gross_pnl,
                tot_taxes,
                net_pnl,
                ret_pct,
                exit_data['trade_id']
            ))
            conn.commit()

        # Update CSV
        row_dict = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "trade_id": exit_data['trade_id'],
            "stock": exit_data['stock'],
            "option_symbol": exit_data['option_symbol'],
            "strike": exit_data['strike'],
            "conf_order": exit_data['conf_order'],
            "quantity": qty,
            "entry_time": exit_data['entry_time'],
            "entry_price": entry_px,
            "exit_time": exit_data['exit_time'],
            "exit_price": exit_px,
            "exit_reason": exit_data['exit_reason'],
            "gross_pnl": gross_pnl,
            "total_taxes": tot_taxes,
            "net_pnl": net_pnl,
            "return_pct": ret_pct
        }

        df_row = pd.DataFrame([row_dict])
        if not self.csv_path.exists():
            df_row.to_csv(self.csv_path, index=False)
        else:
            df_row.to_csv(self.csv_path, mode='a', header=False, index=False)

    def get_today_summary(self) -> dict:
        """Calculates today's summary statistics from DB."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                "SELECT * FROM option_trades WHERE date = ? AND status = 'CLOSED'",
                conn,
                params=(today_str,)
            )

        if df.empty:
            return {
                "date": today_str,
                "trades_count": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "circuit_breaker": False
            }

        wins = int((df['net_pnl'] > 0).sum())
        losses = int((df['net_pnl'] <= 0).sum())
        wr = (wins / len(df)) * 100.0 if len(df) > 0 else 0.0
        tot_pnl = float(df['net_pnl'].sum())

        return {
            "date": today_str,
            "trades_count": len(df),
            "wins": wins,
            "losses": losses,
            "win_rate": wr,
            "total_pnl": tot_pnl,
            "circuit_breaker": False
        }
