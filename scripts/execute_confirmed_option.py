#!/usr/bin/env python3
"""
scripts/execute_confirmed_option.py
=============================================================================
Option Sniper - Real-Time Confirmed Signal Execution Daemon.
Triggered immediately when the 09:40 Short-Sell Model confirms downward breakdown.

Strategy Rules Enforced (Per Simulation Report Parity):
1. Confirmation #1 Priority: Only executes for the 1st confirmed candidate of the day.
2. Capital & Sizing: Initial capital ₹1,00,000 | 1-Lot Execution Mode.
3. Expiry Lockout: Strictly skips trading if DTE <= 4 calendar days (No rollover).
4. Exit Rules:
   - +3.5% Arm -> +1.2% Dynamic Floor Lock
   - +38% Take-Profit Target
   - -15% Hard Stop-Loss
   - Underlying model exit synchronization (14:45 PM IST)
   - 15:15 PM IST Mandatory EOD Square-Off
5. Broker: Kotak Neo (User: AMRIT / MANISHA | UCC: ZCK30)
=============================================================================
"""

import os
import sys
import time
import argparse
import pytz
from datetime import datetime, date
import pandas as pd

# Add repo root to path
DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(DIR)
sys.path.insert(0, REPO_ROOT)

from config.settings import (
    TOTAL_CAPITAL,
    LOT_SIZING_MODE,
    MAX_DAILY_TRADES,
    MAX_CONFIRMATION_ORDER,
    EXPIRY_SKIP_DTE_THRESHOLD,
    FLOOR_LOCK_ARM_PCT,
    FLOOR_LOCK_GAIN_PCT,
    TAKE_PROFIT_PCT,
    STOP_LOSS_PCT,
    MANDATORY_SQUAREOFF_TIME,
    BROKER_TYPE,
    DRY_RUN,
    is_option_trading_enabled,
    TRADING_SETTINGS_JSON
)
from engine.strike_selector import StrikeSelector
from engine.qa_execution_guardrails import round_to_nse_tick
from broker.kotak_neo_broker import KotakNeoBroker
from broker.mock_broker import MockBroker
from telemetry.telegram_notifier import TelegramNotifier
from storage.ledger import TradeLedger

IST = pytz.timezone('Asia/Kolkata')
STATE_FILE = os.path.join(REPO_ROOT, 'data', 'active_live_trade.json')
LOG_FILE = os.path.join(REPO_ROOT, 'logs', f'sniper_live_{datetime.now(IST).strftime("%Y%m%d")}.log')
UNDERLYING_MODEL_EXIT_TIME = "14:45:00"


def log(msg: str):
    now_str = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')
    formatted = f"[{now_str}] [OPTION_SNIPER] {msg}"
    print(formatted, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a') as f:
            f.write(formatted + '\n')
    except Exception:
        pass


def is_trade_already_executed_today(stock: str = None) -> bool:
    """Verifies if daily trades limit is reached or duplicate stock trade was already placed today."""
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    ledger = TradeLedger()
    total_trades = ledger.get_today_trades_count()
    if total_trades >= MAX_DAILY_TRADES:
        return True
    if stock and ledger.get_today_trades_count(stock=stock) > 0:
        return True
    open_trades = ledger.get_open_trades()
    if len(open_trades) >= MAX_CONCURRENT_POSITIONS:
        return True
    return False


def save_state(state_dict: dict):
    try:
        import json
        stock = state_dict.get('stock', 'trade')
        stock_state_file = os.path.join(REPO_ROOT, 'data', f'active_live_trade_{stock}.json')
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(stock_state_file, 'w') as f:
            json.dump(state_dict, f, indent=2)
        with open(STATE_FILE, 'w') as f:
            json.dump(state_dict, f, indent=2)
    except Exception as e:
        log(f"⚠️ Failed to save state file: {e}")


def execute_trade(stock: str, rank: int, cmp: float, trigger_type: str, entry_0942: float, dry_run: bool = False):
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    log("=" * 70)
    log(f"🎯 OPTION SNIPER SIGNAL RECEIVED: {stock} (Rank #{rank}) | CMP: ₹{cmp:,.2f} | Trigger: {trigger_type}")
    log("=" * 70)

    # 1. Monday Exclusion Guard
    dow = datetime.now(IST).weekday()
    if dow == 0:  # Monday is 0
        log("ℹ️ Today is Monday. Option Sniper strictly excludes Mondays per verified empirical model. Skipping.")
        return

    # 2. Daily Max Trades Guard (Conf #1 and Conf #2 enabled per Option B)
    if is_trade_already_executed_today(stock):
        log(f"ℹ️ Trade already executed for {stock} or daily limit ({MAX_DAILY_TRADES}) reached for today ({today_str}). Skipping.")
        return

    ledger = TradeLedger()
    conf_order = ledger.get_today_trades_count() + 1
    if conf_order > MAX_CONFIRMATION_ORDER:
        log(f"ℹ️ Confirmation #{conf_order} exceeds MAX_CONFIRMATION_ORDER ({MAX_CONFIRMATION_ORDER}). Skipping.")
        return

    selector = StrikeSelector()
    notifier = TelegramNotifier()
    ledger = TradeLedger()

    # 2.5 Master Kill-Switch Guard (trading_settings.json)
    if not is_option_trading_enabled():
        skip_msg = f"⛔ <b>OPTION SNIPER SKIPPED (KILL-SWITCH ACTIVE)</b>\n" \
                   f"• Stock: <code>{stock}</code> (Rank #{rank})\n" \
                   f"• Reason: <code>place_option_order: false</code> in <code>trading_settings.json</code>\n" \
                   f"• Status: Option trade placement is disabled in system configuration."
        log(f"⛔ Option trading disabled via {TRADING_SETTINGS_JSON} (place_option_order=false). Skipping trade.")
        notifier.send_message(skip_msg)
        return

    # 3. DTE Expiry Lockout Guard (Strict Simulation Rule: DTE <= 4 skipped)
    is_lockout, dte = selector.is_expiry_lockout(today_str)
    expiry_date = selector.get_active_expiry(today_str)

    if is_lockout:
        skip_msg = f"🚫 <b>OPTION SNIPER SKIPPED (EXPIRY LOCKOUT)</b>\n" \
                   f"• Stock: <code>{stock}</code> (Rank #{rank})\n" \
                   f"• Monthly Expiry: <code>{expiry_date}</code>\n" \
                   f"• Days to Expiry (DTE): <b>{dte} days</b> (&le; {EXPIRY_SKIP_DTE_THRESHOLD} threshold)\n" \
                   f"• Rule: Strict Expiry Skip Rule from Simulation Report (No rollover, zero theta trap risk)."
        log(f"🚫 Trade skipped: DTE ({dte}d) <= {EXPIRY_SKIP_DTE_THRESHOLD}d threshold.")
        notifier.send_message(skip_msg)
        return

    # 4. Strike & Contract Resolution
    step = selector.get_step_size(cmp)
    atm_strike = selector.calculate_atm_strike(cmp, step)
    opt_info = selector.build_option_symbol(stock, atm_strike, "PE", expiry_date=expiry_date)
    nse_symbol = opt_info['nse_symbol']
    lot_size = opt_info['lot_size']
    total_qty = 1 * lot_size  # 1-Lot Sizing Mode

    log(f"📋 Contract Details: {nse_symbol} | Strike: ₹{atm_strike:,.1f} PE | Expiry: {expiry_date} (DTE: {dte}d) | Lot Size: {lot_size}")

    # 5. Connect Broker
    if dry_run or DRY_RUN:
        broker = MockBroker()
        log("🧪 Operating in SIMULATED DRY-RUN MODE.")
    else:
        broker = KotakNeoBroker()
        if not broker.connect():
            log("❌ Broker connection failed! Aborting trade.")
            return

    # 6. Fetch Live Option Premium
    opt_ltp = broker.get_ltp(nse_symbol)
    log(f"🔎 Real-time Option Premium LTP for {nse_symbol}: ₹{opt_ltp:.2f}")

    if opt_ltp <= 0.0:
        log(f"⚠️ Live option LTP returned ₹0.0 for {nse_symbol}. Using fallback estimate.")
        opt_ltp = max(5.0, round(cmp * 0.02, 1))

    # 7. Penny Option Sanity Guard
    valid, reason = selector.validate_option_candidate(cmp, opt_ltp, today_str)
    if not valid:
        log(f"🚫 Option candidate validation failed: {reason}")
        return

    # 8. Place LIMIT BUY Order for 1 Lot at Current Price
    limit_entry_px = round_to_nse_tick(opt_ltp, 'nearest')
    log(f"🚀 Placing 1-LOT LIMIT BUY ORDER: {total_qty} units of {nse_symbol} @ ₹{limit_entry_px:.2f} (LTP: ₹{opt_ltp:.2f}, Approx Capital: ₹{limit_entry_px * total_qty:,.2f})...")
    order_res = broker.place_order(
        symbol=nse_symbol,
        quantity=total_qty,
        side="BUY",
        order_type="LIMIT",
        price=limit_entry_px,
        tag="OPTION_SNIPER_CONF1"
    )

    if order_res.get('status') != 'SUCCESS':
        log(f"❌ Order placement failed: {order_res.get('message')}")
        return

    fill_price = float(order_res.get('fill_price', limit_entry_px))
    order_id = order_res.get('order_id', 'LIVE_LIMIT')
    entry_time_str = datetime.now(IST).strftime('%H:%M:%S')

    log(f"✅ LIMIT ORDER PLACED/FILLED: ID={order_id} | {total_qty} units @ ₹{fill_price:.2f} (Limit Price: ₹{limit_entry_px:.2f}) | Execution Time: {entry_time_str} IST")

    # Exit Targets
    hard_sl_price = round(fill_price * (1.0 - STOP_LOSS_PCT), 2)       # -15%
    take_profit_price = round(fill_price * (1.0 + TAKE_PROFIT_PCT), 2) # +38%
    floor_arm_price = round(fill_price * (1.0 + FLOOR_LOCK_ARM_PCT), 2) # +3.5%
    floor_sl_price = round(fill_price * (1.0 + FLOOR_LOCK_GAIN_PCT), 2) # +1.2%

    trade_record = {
        'date': today_str,
        'trade_id': f"OPT_{today_str}_{stock}_CONF{conf_order}",
        'stock': stock,
        'model_rank': rank,
        'trigger_type': trigger_type,
        'option_symbol': nse_symbol,
        'strike': atm_strike,
        'opt_type': 'PE',
        'expiry': expiry_date,
        'dte': dte,
        'conf_order': conf_order,
        'quantity': total_qty,
        'lot_size': lot_size,
        'lots': 1,
        'entry_price': fill_price,
        'underlying_entry_price': entry_0942,
        'entry_time': entry_time_str,
        'hard_sl': hard_sl_price,
        'target_tp': take_profit_price,
        'floor_arm_price': floor_arm_price,
        'floor_sl_price': floor_sl_price,
        'status': 'ACTIVE'
    }

    save_state(trade_record)
    ledger.record_entry(trade_record)

    # Dispatch Entry Alert to Telegram
    entry_alert = (
        f"🎯 <b>OPTION SNIPER LIVE LIMIT ORDER PLACED</b> 🟢\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Stock:</b> <code>{stock}</code> (Rank #{rank} - Conf #{conf_order})\n"
        f"• <b>Contract:</b> <code>{nse_symbol}</code>\n"
        f"• <b>Order Type:</b> <b>LIMIT @ Current Price (₹{limit_entry_px:.2f})</b>\n"
        f"• <b>Strike:</b> ₹{atm_strike:,.1f} PE | <b>Expiry:</b> {expiry_date} (DTE: {dte}d)\n"
        f"• <b>Fill/Limit Premium:</b> ₹{fill_price:.2f}\n"
        f"• <b>Quantity:</b> {total_qty} units (1 Lot)\n"
        f"• <b>Capital Committed:</b> ₹{fill_price * total_qty:,.2f}\n"
        f"• <b>Hard SL (-15%):</b> ₹{hard_sl_price:.2f}\n"
        f"• <b>Floor Arm (+3.5%):</b> ₹{floor_arm_price:.2f} &rarr; Lock SL at ₹{floor_sl_price:.2f} (+1.2%)\n"
        f"• <b>Take-Profit (+38%):</b> ₹{take_profit_price:.2f}\n"
        f"• <b>Underlying 09:42:</b> ₹{entry_0942:,.2f}\n"
        f"• <b>Execution Time:</b> {entry_time_str} IST\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <i>Active Risk Governor: Automatic Floor Lock & Trailing Daemon Armed</i>"
    )
    notifier.send_message(entry_alert)

    # 9. Enter Real-Time Position Management Daemon Loop
    log("🔄 Entering Real-Time Position Monitoring Loop...")
    active_sl = hard_sl_price
    floor_locked = False
    highest_premium = fill_price

    while True:
        time.sleep(5)
        now_ist = datetime.now(IST)
        now_time_str = now_ist.strftime('%H:%M:%S')

        # Check latest option price
        cur_opt_ltp = broker.get_ltp(nse_symbol)
        if cur_opt_ltp <= 0.0:
            continue

        if cur_opt_ltp > highest_premium:
            highest_premium = cur_opt_ltp

        cur_gain_pct = (cur_opt_ltp - fill_price) / fill_price

        # Check 1: Dynamic Floor Lock (+3.5% Arm -> +1.2% Lock)
        if not floor_locked and cur_opt_ltp >= floor_arm_price:
            floor_locked = True
            active_sl = floor_sl_price
            log(f"🔒 FLOOR LOCK TRIGGERED: Option reached ₹{cur_opt_ltp:.2f} (+{cur_gain_pct*100:.1f}% >= +3.5%). SL moved to ₹{active_sl:.2f} (+1.2%).")
            floor_alert = (
                f"🔒 <b>OPTION SNIPER FLOOR LOCKED (+1.2% PROTECTED)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Contract:</b> <code>{nse_symbol}</code>\n"
                f"• <b>Current Premium:</b> ₹{cur_opt_ltp:.2f} ({cur_gain_pct*100:+.2f}%)\n"
                f"• <b>New Stop-Loss:</b> <b>₹{active_sl:.2f} (+1.2% Floor)</b>\n"
                f"• <b>Status:</b> Position is now 100% risk-free green! ✅\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            notifier.send_message(floor_alert)

        # Check 2: Take-Profit Target Hit (+38%)
        if cur_opt_ltp >= take_profit_price:
            exit_reason = "TAKE_PROFIT_+38%"
            log(f"🎉 TAKE-PROFIT HIT: Option reached ₹{cur_opt_ltp:.2f} >= ₹{take_profit_price:.2f} (+{cur_gain_pct*100:.1f}%)")
            _execute_exit(broker, notifier, ledger, trade_record, cur_opt_ltp, exit_reason, now_time_str)
            break

        # Check 3: Stop-Loss Hit (Hard SL or Floor Locked SL)
        if cur_opt_ltp <= active_sl:
            exit_reason = "FLOOR_LOCK_SL_HIT" if floor_locked else "HARD_SL_HIT_-15%"
            log(f"🛑 STOP-LOSS HIT: Option dropped to ₹{cur_opt_ltp:.2f} <= ₹{active_sl:.2f} ({exit_reason})")
            _execute_exit(broker, notifier, ledger, trade_record, cur_opt_ltp, exit_reason, now_time_str)
            break

        # Check 4: Underlying Model Close (14:45 IST)
        if now_time_str >= UNDERLYING_MODEL_EXIT_TIME:
            exit_reason = "UNDERLYING_MODEL_CLOSE_1445"
            log(f"⏰ Underlying model close time reached ({now_time_str} >= {UNDERLYING_MODEL_EXIT_TIME}). Exiting option position.")
            _execute_exit(broker, notifier, ledger, trade_record, cur_opt_ltp, exit_reason, now_time_str)
            break

        # Check 5: Mandatory EOD Square-Off (15:15 IST)
        if now_time_str >= MANDATORY_SQUAREOFF_TIME:
            exit_reason = "MANDATORY_EOD_SQUAREOFF_1515"
            log(f"⏰ Mandatory EOD square-off time reached ({now_time_str} >= {MANDATORY_SQUAREOFF_TIME}). Liquidating option position.")
            _execute_exit(broker, notifier, ledger, trade_record, cur_opt_ltp, exit_reason, now_time_str)
            break


def _execute_exit(broker, notifier, ledger, trade_record: dict, exit_price: float, reason: str, exit_time_str: str):
    symbol = trade_record['option_symbol']
    qty = trade_record['quantity']
    entry_px = trade_record['entry_price']

    limit_exit_px = round_to_nse_tick(exit_price, 'floor')
    log(f"🏁 Liquidating {qty} units of {symbol} via LIMIT SELL @ ₹{limit_exit_px:.2f} (LTP: ₹{exit_price:.2f}) | Reason: {reason}...")
    sell_res = broker.place_order(
        symbol=symbol,
        quantity=qty,
        side="SELL",
        order_type="LIMIT",
        price=limit_exit_px,
        tag=reason[:20]
    )

    realized_px = float(sell_res.get('fill_price', limit_exit_px))
    gross_pnl = (realized_px - entry_px) * qty
    ret_pct = (realized_px - entry_px) / entry_px * 100.0

    trade_record['exit_price'] = realized_px
    trade_record['exit_time'] = exit_time_str
    trade_record['exit_reason'] = reason
    trade_record['realized_pnl'] = gross_pnl
    trade_record['gross_pnl'] = gross_pnl
    trade_record['return_pct'] = ret_pct
    trade_record['status'] = 'COMPLETED'

    save_state(trade_record)
    ledger.record_exit(trade_record)

    log(f"🏁 POSITION CLOSED: PnL: ₹{gross_pnl:+,.2f} ({ret_pct:+.2f}%) | Reason: {reason}")

    # Dispatch Exit Alert to Telegram
    icon = "🎉" if gross_pnl > 0 else "🛑"
    exit_alert = (
        f"{icon} <b>OPTION SNIPER POSITION CLOSED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Contract:</b> <code>{symbol}</code>\n"
        f"• <b>Exit Reason:</b> <b>{reason}</b>\n"
        f"• <b>Entry Premium:</b> ₹{entry_px:.2f}\n"
        f"• <b>Exit Premium:</b> ₹{realized_px:.2f}\n"
        f"• <b>Return:</b> <b>{ret_pct:+.2f}%</b>\n"
        f"• <b>Realized Gross P&amp;L:</b> <b>₹{gross_pnl:+,.2f}</b>\n"
        f"• <b>Exit Time:</b> {exit_time_str} IST\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <i>Option Sniper Production Engine — Automated 09:40 Hybrid</i>"
    )
    notifier.send_message(exit_alert)


def main():
    parser = argparse.ArgumentParser(description="Option Sniper Live Confirmation Execution Daemon")
    parser.add_argument("--stock", required=True, help="Confirmed stock symbol (e.g. TECHM)")
    parser.add_argument("--rank", type=int, default=1, help="09:40 model rank (1-4)")
    parser.add_argument("--cmp", type=float, required=True, help="Underlying CMP at confirmation")
    parser.add_argument("--trigger", default="Direct Downward (cond_a)", help="Confirmation trigger type")
    parser.add_argument("--entry_0942", type=float, default=0.0, help="09:42 benchmark entry price")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without placing broker orders")

    args = parser.parse_args()

    ref_p = args.entry_0942 if args.entry_0942 > 0 else args.cmp
    execute_trade(
        stock=args.stock.strip().upper(),
        rank=args.rank,
        cmp=args.cmp,
        trigger_type=args.trigger,
        entry_0942=ref_p,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
