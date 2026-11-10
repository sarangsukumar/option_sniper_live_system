#!/bin/bash
# =============================================================================
# scripts/run_paper.sh - Run Option Sniper in Paper Trading Mode
# =============================================================================
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

export OPTION_SNIPER_MODE="PAPER"
export OPTION_SNIPER_BROKER="MOCK"
export OPTION_SNIPER_CAPITAL="100000.0"
export OPTION_SNIPER_MAX_CONF="1"

LOG_FILE="$DIR/logs/paper_$(date +'%Y%m%d').log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Option Sniper (Paper Mode)..." | tee -a "$LOG_FILE"
python3 "$DIR/main.py" --mode paper >> "$LOG_FILE" 2>&1
