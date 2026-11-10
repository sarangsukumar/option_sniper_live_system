#!/bin/bash
# =============================================================================
# scripts/run_eod_reconcile.sh - End of Day Ledger Audit & Reconcile
# =============================================================================
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Reconciling Option Sniper Daily Ledger..."
python3 "$DIR/main.py" --reconcile
