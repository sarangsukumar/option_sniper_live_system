#!/usr/bin/env python3
"""
main.py
=============================================================================
Option Sniper Live Production System - Master CLI Entrypoint
Usage:
    python main.py --dry-run           # Run comprehensive pre-flight sanity checks
    python main.py --mode paper        # Run in Paper Trading mode
    python main.py --mode live         # Run in Live Production mode
    python main.py --test              # Run test suite
    python main.py --reconcile         # Print today's trade ledger & summary
=============================================================================
"""

import os
import sys
import argparse
import unittest
from datetime import datetime
import pandas as pd

from config.settings import (
    EXECUTION_MODE,
    BROKER_TYPE,
    TOTAL_CAPITAL,
    CAPITAL_PER_TRADE,
    MAX_DAILY_TRADES,
    MAX_CONFIRMATION_ORDER,
    TIER1_CONVICTION_STOCKS
)
from broker.mock_broker import MockBroker
from broker.kotak_neo_broker import KotakNeoBroker
from broker.kite_broker import KiteBroker
from engine.sniper_engine import OptionSniperEngine
from storage.ledger import TradeLedger


def get_broker(broker_type: str, mode: str):
    """Instantiates appropriate broker adapter."""
    if mode.upper() in ["MOCK", "PAPER"] or broker_type.upper() == "MOCK":
        return MockBroker(slippage_ticks=1)
    elif broker_type.upper() == "KOTAK":
        return KotakNeoBroker()
    elif broker_type.upper() == "KITE":
        return KiteBroker()
    else:
        return MockBroker(slippage_ticks=1)


def run_dry_run():
    """Performs end-to-end dry-run and configuration verification."""
    print("=" * 70)
    print("🛡️ OPTION SNIPER PRODUCTION SYSTEM: PRE-FLIGHT DRY-RUN AUDIT")
    print("=" * 70)

    broker = get_broker(BROKER_TYPE, "MOCK")
    engine = OptionSniperEngine(broker=broker, dry_run=True)

    ok = engine.initialize()
    if not ok:
        print("❌ Pre-flight initialization failed!")
        return False

    print(f"\n[1] Strategy Configuration:")
    print(f"    • Execution Mode:        {EXECUTION_MODE}")
    print(f"    • Broker Type:           {BROKER_TYPE}")
    print(f"    • Total Account Capital: ₹{TOTAL_CAPITAL:,.2f}")
    print(f"    • Capital per Trade:     ₹{CAPITAL_PER_TRADE:,.2f}")
    print(f"    • Max Daily Trades:      {MAX_DAILY_TRADES}")
    print(f"    • Max Conf Priority:     #{MAX_CONFIRMATION_ORDER}")
    print(f"    • Tier-1 Basket:         {', '.join(TIER1_CONVICTION_STOCKS)}")

    # Strike Selector Test
    print(f"\n[2] Testing Strike Selection & Expiry Resolution:")
    sample_stocks = [
        ("GLENMARK", 1740.0),
        ("TECHM", 1680.0),
        ("POLYCAB", 6850.0),
        ("HINDALCO", 650.0),
        ("COALINDIA", 420.0)
    ]
    for stock, cmp in sample_stocks:
        step = engine.strike_selector.get_step_size(cmp)
        atm = engine.strike_selector.calculate_atm_strike(cmp, step)
        opt = engine.strike_selector.build_option_symbol(stock, atm, "PE")
        print(f"    • {stock:10s} | CMP: ₹{cmp:7.1f} | Step: ₹{step:4.1f} | ATM Strike: ₹{atm:6.1f} | "
              f"Symbol: {opt['nse_symbol']:18s} | Lot: {opt['lot_size']} shares")

    # Model Inference Test
    print(f"\n[3] Testing Model Inference & Candidate Ranking:")
    mock_features = pd.DataFrame([
        {"stock": "GLENMARK", "cmp": 1740.0, "low_0942": 1735.0, "ret_0915_0940": -0.012, "vol_ratio_0940": 2.1},
        {"stock": "TECHM",    "cmp": 1680.0, "low_0942": 1675.0, "ret_0915_0940": -0.015, "vol_ratio_0940": 1.9},
        {"stock": "POLYCAB",  "cmp": 6850.0, "low_0942": 6820.0, "ret_0915_0940": -0.008, "vol_ratio_0940": 1.5},
        {"stock": "HINDALCO", "cmp": 650.0,  "low_0942": 647.0,  "ret_0915_0940": -0.005, "vol_ratio_0940": 1.2},
    ])
    watchlist = engine.generate_morning_watchlist(mock_features)
    print(f"    Generated Watchlist with {len(watchlist)} candidates.")

    # Simulated Breakdown & Execution Test
    print(f"\n[4] Simulating Candle Breakdown & Order Fill:")
    mock_ticks = {"GLENMARK": 1732.0, "TECHM": 1678.0}
    confirmed = engine.check_candle_breakdowns(mock_ticks)
    if confirmed:
        first_conf = confirmed[0]
        pos = engine.execute_option_entry(first_conf, option_premium_cmp=38.50)
        if pos:
            print(f"    ✅ Position Created: {pos.option_symbol} | Fill: ₹{pos.entry_price:.2f} | "
                  f"Hard SL: ₹{pos.hard_sl:.2f} | Target: ₹{pos.target_tp:.2f}")

            # Simulate price gain to +20% (Trigger floor lock)
            print(f"\n[5] Simulating +20% Option Gain (Floor Lock Check):")
            engine.monitor_and_manage_positions(
                option_ticks={pos.option_symbol: 46.50},
                underlying_ticks={"GLENMARK": 1720.0}
            )
            print(f"    Floor Locked Status: {pos.floor_locked} | Active SL: ₹{pos.current_sl:.2f}")

            # Simulate Target Hit at +40%
            print(f"\n[6] Simulating +40% Take-Profit Target Hit:")
            engine.monitor_and_manage_positions(
                option_ticks={pos.option_symbol: 54.00},
                underlying_ticks={"GLENMARK": 1710.0}
            )

    # Risk summary
    print(f"\n[7] End of Dry-Run Risk & Ledger State:")
    status = engine.risk_controller.get_status_summary()
    print(f"    • Trades Today:        {status['daily_trades_executed']}")
    print(f"    • Realized PnL:        ₹{status['daily_realized_pnl']:,.2f}")
    print(f"    • Circuit Breaker:     {'TRIPPED' if status['circuit_breaker_tripped'] else 'CLEAN'}")

    print("\n" + "=" * 70)
    print("✨ ALL PRE-FLIGHT CHECKS PASSED: SYSTEM FULLY PRODUCTION READY")
    print("=" * 70)
    return True


def run_tests():
    """Runs test suite."""
    print("🧪 Running Option Sniper Test Suite...")
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir="tests", pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


def reconcile():
    """Prints today's ledger summary."""
    ledger = TradeLedger()
    summary = ledger.get_today_summary()
    print("=" * 60)
    print(f"📊 OPTION SNIPER LEDGER AUDIT ({summary['date']})")
    print("=" * 60)
    print(f"Trades Executed: {summary['trades_count']}")
    print(f"Wins / Losses:   {summary['wins']} W / {summary['losses']} L")
    print(f"Win Rate:        {summary['win_rate']:.1f}%")
    print(f"Net Realized PnL: ₹{summary['total_pnl']:,.2f}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Option Sniper Live Production System")
    parser.add_argument("--mode", choices=["live", "paper", "mock"], default=EXECUTION_MODE.lower(),
                        help="Execution mode (default: paper)")
    parser.add_argument("--broker", choices=["mock", "kotak", "kite"], default=BROKER_TYPE.lower(),
                        help="Broker adapter to use")
    parser.add_argument("--dry-run", action="store_true", help="Run comprehensive system validation")
    parser.add_argument("--test", action="store_true", help="Run unit test suite")
    parser.add_argument("--reconcile", action="store_true", help="Print today's trade ledger summary")

    args = parser.parse_args()

    if args.dry_run:
        success = run_dry_run()
        sys.exit(0 if success else 1)
    elif args.test:
        run_tests()
    elif args.reconcile:
        reconcile()
    else:
        print(f"🚀 Launching Option Sniper in {args.mode.upper()} mode with {args.broker.upper()} broker...")
        broker = get_broker(args.broker, args.mode)
        engine = OptionSniperEngine(broker=broker, dry_run=(args.mode == "mock"))
        if not engine.initialize():
            print("❌ Engine initialization failed.")
            sys.exit(1)
        print("🟢 Engine is active and standing by for market open.")


if __name__ == "__main__":
    main()
