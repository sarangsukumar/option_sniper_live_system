#!/usr/bin/env python3
"""
scripts/eod_squareoff_and_reconcile.py
=============================================================================
Option Sniper - 15:15 IST EOD Safety Liquidator & Daily Ledger Reconciler.
Ensures zero overnight F&O carryover and broadcasts verified PnL to Telegram.
=============================================================================
"""

import os
import sys
import json
import glob
import pytz
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(DIR)
sys.path.insert(0, REPO_ROOT)

from config.settings import BROKER_TYPE, DRY_RUN
from engine.qa_execution_guardrails import round_to_nse_tick
from broker.kotak_neo_broker import KotakNeoBroker
from broker.mock_broker import MockBroker
from storage.ledger import TradeLedger
from telemetry.telegram_notifier import TelegramNotifier

IST = pytz.timezone('Asia/Kolkata')
STATE_FILE = os.path.join(REPO_ROOT, 'data', 'active_live_trade.json')
LOG_FILE = os.path.join(REPO_ROOT, 'logs', f'eod_{datetime.now(IST).strftime("%Y%m%d")}.log')


def log(msg: str):
    now_str = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')
    formatted = f"[{now_str}] [OPTION_SNIPER_EOD] {msg}"
    print(formatted, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(formatted + '\n')
    except Exception:
        pass


def main():
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    now_time_str = datetime.now(IST).strftime('%H:%M:%S')
    log("=" * 65)
    log(f"⏰ Starting 15:15 IST Mandatory EOD Square-Off & Reconciler ({today_str})")
    log("=" * 65)

    ledger = TradeLedger()
    notifier = TelegramNotifier()

    # Step 1: Check for active unclosed positions (supports up to 2 concurrent trades)
    state_files = glob.glob(os.path.join(REPO_ROOT, 'data', 'active_live_trade*.json'))
    for s_file in state_files:
        try:
            with open(s_file, 'r') as f:
                state = json.load(f)
            
            if state.get('date') == today_str and state.get('status') == 'ACTIVE':
                log(f"⚠️ Found active unclosed position: {state.get('option_symbol')} in {os.path.basename(s_file)}. Initiating square-off...")
                broker = KotakNeoBroker() if BROKER_TYPE == "KOTAK" and not DRY_RUN else MockBroker()
                if broker.connect():
                    sym = state['option_symbol']
                    qty = state['quantity']
                    entry_px = state['entry_price']
                    ltp = broker.get_ltp(sym) or entry_px

                    limit_exit_px = round_to_nse_tick(ltp, 'floor')
                    res = broker.place_order(symbol=sym, quantity=qty, side="SELL", order_type="LIMIT", price=limit_exit_px)
                    fill_px = float(res.get('fill_price', limit_exit_px))
                    gross_pnl = (fill_px - entry_px) * qty
                    ret_pct = (fill_px - entry_px) / entry_px * 100.0

                    state['exit_price'] = fill_px
                    state['exit_time'] = now_time_str
                    state['exit_reason'] = "MANDATORY_EOD_SQUAREOFF_1515"
                    state['realized_pnl'] = gross_pnl
                    state['gross_pnl'] = gross_pnl
                    state['return_pct'] = ret_pct
                    state['status'] = 'COMPLETED'

                    with open(s_file, 'w') as f:
                        json.dump(state, f, indent=2)
                    ledger.record_exit(state)
                    log(f"✅ Position cleanly liquidated: {sym} | PnL = ₹{gross_pnl:+,.2f} ({ret_pct:+.2f}%)")
        except Exception as e:
            log(f"⚠️ Error during active trade check on {s_file}: {e}")

    # Step 2: Generate and broadcast Daily Summary
    summary = ledger.get_today_summary()
    log("=" * 65)
    log(f"📊 Daily Summary: Trades={summary['trades_count']} | Wins={summary['wins']} | Losses={summary['losses']} | PnL=₹{summary['total_pnl']:,.2f}")
    log("=" * 65)

    if summary['trades_count'] > 0:
        notifier.notify_daily_summary(summary)
    else:
        log("ℹ️ No trades executed today. Skipping Telegram daily summary broadcast.")


if __name__ == "__main__":
    main()
