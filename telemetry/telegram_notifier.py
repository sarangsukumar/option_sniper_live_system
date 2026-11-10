"""
telemetry/telegram_notifier.py
=============================================================================
Real-Time Telegram Telemetry & Alert Dispatcher.
Broadcasts institutional notifications across designated Telegram channels:
- Morning Watchlist & Strike Selection (09:40)
- Confirmation & Order Fills
- Dynamic Floor Lock & Trailing SL Advancements
- Trade Exits (Target, SL, Time Square-off)
- End-of-Day PnL Summary Ledger
=============================================================================
"""

import requests
from typing import List, Dict, Optional
from config.settings import TELEGRAM_ENABLED, TELEGRAM_ENDPOINTS


class TelegramNotifier:
    def __init__(self, endpoints: List[Dict[str, str]] = TELEGRAM_ENDPOINTS, enabled: bool = TELEGRAM_ENABLED):
        self.endpoints = endpoints
        self.enabled = enabled

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Broadcasts text message to all registered Telegram endpoints."""
        if not self.enabled:
            return True

        success = True
        for ep in self.endpoints:
            url = f"https://api.telegram.org/bot{ep['token']}/sendMessage"
            payload = {
                "chat_id": ep["chat_id"],
                "text": text,
                "parse_mode": parse_mode
            }
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code != 200:
                    success = False
            except Exception as e:
                print(f"⚠️ Telegram alert failure to {ep['name']}: {e}")
                success = False

        return success

    def notify_morning_watchlist(self, watchlist: List[dict]):
        """Alerts top 4 candidate stocks and target strikes."""
        lines = [
            "🎯 <b>OPTION SNIPER: MORNING WATCHLIST GENERATED</b>",
            f"<b>Total Candidates:</b> {len(watchlist)}",
            "------------------------------------------------"
        ]
        for idx, item in enumerate(watchlist, 1):
            lines.append(
                f"<b>#{idx} {item['stock']}</b> | CMP: ₹{item['cmp']:.2f}<br/>"
                f"• Target Option: <b>{item['option_symbol']}</b> (ATM Strike: ₹{item['strike']})<br/>"
                f"• Breakdown Trigger: Below ₹{item['trigger_price']:.2f}"
            )
        lines.append("------------------------------------------------")
        lines.append("⏳ <i>Awaiting candle confirmation breakdown. Priority on Conf #1.</i>")
        self.send_message("\n".join(lines))

    def notify_order_filled(self, trade_info: dict):
        """Alerts when a Put option order is filled."""
        msg = f"""🟢 <b>OPTION SNIPER: ORDER FILLED (CONF #{trade_info['conf_order']})</b>
------------------------------------------------
<b>Stock:</b> #{trade_info['stock']}
<b>Contract:</b> <code>{trade_info['option_symbol']}</code>
<b>Lot Size:</b> {trade_info['quantity']} shares
<b>Fill Premium:</b> ₹{trade_info['entry_price']:.2f}
<b>Underlying Entry:</b> ₹{trade_info['underlying_entry_price']:.2f}
------------------------------------------------
🎯 <b>Target (+38%):</b> ₹{trade_info['target_tp']:.2f}
🛡️ <b>Hard SL (-15%):</b> ₹{trade_info['hard_sl']:.2f}
🔒 <b>Floor Lock:</b> Moves SL to +1.2% profit at +3.5% gain
⏰ <b>Time:</b> {trade_info['entry_time']}"""
        self.send_message(msg)

    def notify_floor_locked(self, stock: str, option_symbol: str, current_price: float, floor_sl: float):
        """Alerts when profit reaches +3.5% and SL is ratcheted to +1.2% guaranteed floor."""
        msg = f"""🔒 <b>OPTION SNIPER: FLOOR LOCKED (PROFIT LOCKED)</b>
------------------------------------------------
<b>Stock:</b> #{stock}
<b>Contract:</b> <code>{option_symbol}</code>
<b>Current Premium:</b> ₹{current_price:.2f} (+3.5% Gain Arm Reached)
🛡️ <b>Trailing Stop Loss:</b> Advanced to <b>₹{floor_sl:.2f}</b> (+1.2% Floor Lock)
✨ <i>Trade is now 100% risk-free with guaranteed profit locked.</i>"""
        self.send_message(msg)

    def notify_trade_exit(self, exit_info: dict):
        """Alerts when a position is closed."""
        pnl = exit_info['gross_pnl']
        pnl_symbol = "🟢 +" if pnl >= 0 else "🔴 "
        msg = f"""🏁 <b>OPTION SNIPER: POSITION CLOSED</b>
------------------------------------------------
<b>Stock:</b> #{exit_info['stock']}
<b>Contract:</b> <code>{exit_info['option_symbol']}</code>
<b>Exit Reason:</b> <b>{exit_info['exit_reason']}</b>
<b>Entry Premium:</b> ₹{exit_info['entry_price']:.2f}
<b>Exit Premium:</b> ₹{exit_info['exit_price']:.2f}
<b>Net Realized PnL:</b> <b>{pnl_symbol}₹{pnl:,.2f}</b>
⏰ <b>Exit Time:</b> {exit_info['exit_time']}"""
        self.send_message(msg)

    def notify_daily_summary(self, summary: dict):
        """Alerts end-of-day trading recap."""
        pnl = summary['total_pnl']
        pnl_str = f"🟢 +₹{pnl:,.2f}" if pnl >= 0 else f"🔴 -₹{abs(pnl):,.2f}"
        msg = f"""📊 <b>OPTION SNIPER: DAILY OPERATIONS RECAP</b>
------------------------------------------------
<b>Date:</b> {summary['date']}
<b>Trades Executed:</b> {summary['trades_count']}
<b>Wins / Losses:</b> {summary['wins']} W / {summary['losses']} L
<b>Win Rate:</b> {summary['win_rate']:.1f}%
<b>Total Realized PnL:</b> <b>{pnl_str}</b>
<b>Circuit Breaker:</b> {"⚠️ TRIPPED" if summary['circuit_breaker'] else "✅ Normal"}
------------------------------------------------
<i>All positions squared off flat. System ready for tomorrow.</i>"""
        self.send_message(msg)
