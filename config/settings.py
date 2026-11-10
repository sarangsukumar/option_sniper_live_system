"""
config/settings.py
=============================================================================
Option Sniper Live Production System Configuration
Centralized settings for execution modes, brokers, risk controls, models,
and Telegram alerting.
=============================================================================
"""

import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# EXECUTION MODE & BROKER CONFIGURATION
# -----------------------------------------------------------------------------
# MODE: 'MOCK' (instant local sim), 'PAPER' (real-time paper trading), 'LIVE' (real capital)
EXECUTION_MODE = os.environ.get("OPTION_SNIPER_MODE", "PAPER").upper()

# ORDER TYPE: 'LIMIT' (places limit order at current LTP per MIS standard)
ORDER_TYPE = os.environ.get("OPTION_SNIPER_ORDER_TYPE", "LIMIT").upper()

# BROKER: 'KOTAK' (default live broker for Amrit/Manisha), 'KITE', 'MOCK'
BROKER_TYPE = os.environ.get("OPTION_SNIPER_BROKER", "KOTAK").upper()

# Dry run flag (validates connections and pipelines without sending orders)
DRY_RUN = os.environ.get("OPTION_SNIPER_DRY_RUN", "0") == "1"

# -----------------------------------------------------------------------------
# CAPITAL & SIZING GOVERNANCE
# -----------------------------------------------------------------------------
# Base capital allocated to the pure options strategy
TOTAL_CAPITAL = float(os.environ.get("OPTION_SNIPER_CAPITAL", "100000.0"))  # Default ₹1,00,000

# Lot sizing mode: '1_LOT' (exact 1 lot per trade, conservative live start as per simulation report)
# or '1L_CAPITAL' (sizes lots dynamically based on ₹1.0L capital)
LOT_SIZING_MODE = os.environ.get("OPTION_LOT_SIZING_MODE", "1_LOT").upper()

# Maximum capital committed per single option trade
CAPITAL_PER_TRADE = float(os.environ.get("OPTION_SNIPER_TRADE_CAPITAL", "100000.0"))

# Maximum concurrent option positions open at once
MAX_CONCURRENT_POSITIONS = 2

# Maximum total option trades per calendar day
MAX_DAILY_TRADES = 2

# Circuit breaker: stop trading for the day if N consecutive losses occur
MAX_CONSECUTIVE_LOSSES_HALT = 2

# Hard lot limits (single-stock liquidity preservation)
DEFAULT_MAX_OPTION_LOTS = 5
MIN_OPTION_PREMIUM = 5.00  # Avoid penny options with high bid-ask spread %
MIN_LOT_COST = 8000.0      # Minimum lot premium value

# Expiry Skip Rule from Simulation:
# Put Options within <= 4 calendar days of monthly expiry suffer severe theta decay.
# In the simulation, trades within <= 4 days of expiry are strictly skipped (NOT rolled to next month).
EXPIRY_SKIP_DTE_THRESHOLD = int(os.environ.get("OPTION_EXPIRY_SKIP_DTE", "4"))

# -----------------------------------------------------------------------------
# INTRADAY TRADE MANAGEMENT PARAMETERS (EXACT SIMULATION SPECIFICATION)
# -----------------------------------------------------------------------------
# Simulation strategy: Sync_Hybrid_A_WR85 (+3.5% Arm -> +1.2% Floor Lock + Sync W80)
# Achieved 85.07% ATM Win Rate and 85.92% Conf #1 Win Rate in 2024-2026 Audit Report
STOP_LOSS_PCT = float(os.environ.get("OPTION_STOP_LOSS_PCT", "0.15"))          # Hard cut at -15% option premium drop
FLOOR_LOCK_ARM_PCT = float(os.environ.get("OPTION_FLOOR_LOCK_ARM_PCT", "0.035")) # At +3.5% gain, arm floor lock
FLOOR_LOCK_GAIN_PCT = float(os.environ.get("OPTION_FLOOR_LOCK_GAIN_PCT", "0.012")) # Lock in +1.2% guaranteed floor
TAKE_PROFIT_PCT = float(os.environ.get("OPTION_TAKE_PROFIT_PCT", "0.38"))        # Target profit at +38% gain

# Underlying stock price guardrail
UNDERLYING_SL_PCT = 0.008     # If stock bounces +0.8% above breakdown price, exit option

# Timing Rules (IST)
MARKET_OPEN_TIME = "09:15:00"
SNIPER_0920_TIME = "09:20:00"
SNIPER_0940_TIME = "09:40:00"
CONFIRMATION_DEADLINE = "10:45:00"
MANDATORY_SQUAREOFF_TIME = "15:15:00"
MARKET_CLOSE_TIME = "15:30:00"

# Confirmation Filter
# '1' = Strictly Confirmation #1 Only (Highest win rate: 85.92%)
# '2' = Confirmation #1 and #2
MAX_CONFIRMATION_ORDER = int(os.environ.get("OPTION_SNIPER_MAX_CONF", "1"))

# -----------------------------------------------------------------------------
# TICKER CONVICTION LISTS
# -----------------------------------------------------------------------------
# Tier-1: 100% Backtested Win Rate Club (Priority Allocation)
TIER1_CONVICTION_STOCKS = [
    "GLENMARK", "TECHM", "POLYCAB", "HINDALCO", "COALINDIA", "VOLTAS", "JINDALSTEL"
]

# Tier-2: >85% Win Rate & Liquid F&O Names
TIER2_CORE_STOCKS = [
    "TATACHEM", "TATACONSUM", "AUROPHARMA", "SBIN", "INFY", "ICICIBANK", "TATASTEEL"
]

# -----------------------------------------------------------------------------
# BROKER CREDENTIALS & API KEYS
# -----------------------------------------------------------------------------
# Kotak Neo API
KOTAK_AUTH_CSV = os.environ.get("KOTAK_AUTH_CSV", "/home/ubuntu/KotakCodes1/kotak_auth_userid.csv")
KOTAK_TARGET_USER = os.environ.get("KOTAK_TARGET_USER", "MANISHA")  # Target user AMRIT / MANISHA
KOTAK_USER_ID = os.environ.get("KOTAK_USER_ID", "ZCK30")
KOTAK_CONSUMER_KEY = os.environ.get("KOTAK_CONSUMER_KEY", "")
KOTAK_CONSUMER_SECRET = os.environ.get("KOTAK_CONSUMER_SECRET", "")
KOTAK_MOBILE_NUMBER = os.environ.get("KOTAK_MOBILE_NUMBER", "")
KOTAK_PASSWORD = os.environ.get("KOTAK_PASSWORD", "")
KOTAK_MPIN = os.environ.get("KOTAK_MPIN", "")
KOTAK_TOTP_SECRET = os.environ.get("KOTAK_TOTP_SECRET", "")
KOTAK_ORDER_PRODUCT = os.environ.get("KOTAK_ORDER_PRODUCT", "NRML")

# Zerodha Kite Connect API
KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")

# -----------------------------------------------------------------------------
# TELEGRAM TELEMETRY ENDPOINTS
# -----------------------------------------------------------------------------
TELEGRAM_ENABLED = os.environ.get("OPTION_SNIPER_TELEGRAM", "1") == "1"
TELEGRAM_ENDPOINTS = [
    {
        "name": "Primary Quant Group",
        "token": "7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko",
        "chat_id": "-1002365534285"
    },
    {
        "name": "Production Status & Warning Group",
        "token": "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE",
        "chat_id": "-698073972"
    }
]

# -----------------------------------------------------------------------------
# FILE & STORAGE PATHS
# -----------------------------------------------------------------------------
LOT_SIZE_CSV = CONFIG_DIR / "historical_lotsize_new.csv"
EXPIRY_DATES_CSV = CONFIG_DIR / "master_expiry_dates.csv"
EXPIRY_DATES_TXT = Path(os.environ.get("EXPIRY_DATES_TXT", "/home/ubuntu/KotakCodes1/expiry_dates.txt"))
DATABASE_PATH = DATA_DIR / "option_sniper.db"
DAILY_LEDGER_CSV = DATA_DIR / "daily_trade_ledger.csv"
AUDIT_LOG_FILE = LOGS_DIR / "option_sniper.log"
