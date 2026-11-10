#!/bin/bash
# =============================================================================
# scripts/run_live.sh - Run Option Sniper in Live Production Mode
# =============================================================================
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

export OPTION_SNIPER_MODE="LIVE"
export OPTION_SNIPER_BROKER="${BROKER:-KOTAK}"
export OPTION_SNIPER_CAPITAL="${CAPITAL:-100000.0}"
export OPTION_SNIPER_MAX_CONF="1"

LOG_FILE="$DIR/logs/live_$(date +'%Y%m%d').log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Option Sniper (LIVE Mode - Broker: $OPTION_SNIPER_BROKER)..." | tee -a "$LOG_FILE"
python3 "$DIR/main.py" --mode live --broker "$OPTION_SNIPER_BROKER" >> "$LOG_FILE" 2>&1
