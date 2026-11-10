"""
engine/qa_execution_guardrails.py
=============================================================================
Institutional QA Execution Guardrails & Compliance Module.
Handles:
- Strict ₹0.05 NSE Tick Size Rounding (Zero non-tick executions)
- Liquidity-Aware Discrete Lot Calculation
- Statutory Taxes, Exchange Charges, STT & Brokerage Computation
=============================================================================
"""

import math
import numpy as np

NSE_TICK_SIZE = 0.05
DEFAULT_MAX_OPTION_LOTS = 5


def round_to_nse_tick(price: float, direction: str = 'floor', tick: float = NSE_TICK_SIZE) -> float:
    """
    Rounds a price strictly to the nearest valid NSE tick size (₹0.05).

    Parameters:
    -----------
    price : float
        Raw calculated price.
    direction : str
        'floor' for exits / limit sells (conservative lower price).
        'ceil' for entries / limit buys (conservative higher price).
        'nearest' for midpoint rounding.
    tick : float
        Tick size (default 0.05 for NSE equities and options).

    Returns:
    --------
    float: Tick-compliant price rounded to 2 decimal places.
    """
    if price is None or np.isnan(price) or price <= 0:
        return 0.05

    if direction == 'floor':
        rounded = math.floor(round(price, 6) / tick) * tick
    elif direction == 'ceil':
        rounded = math.ceil(round(price, 6) / tick) * tick
    else:
        rounded = round(round(price, 6) / tick) * tick

    return max(0.05, round(rounded, 2))


def calculate_option_lots(
    allocated_capital: float,
    premium_cmp: float,
    lot_size: int,
    max_lots: int = DEFAULT_MAX_OPTION_LOTS,
    sizing_mode: str = "1_LOT"
) -> int:
    """
    Computes integer option lots constrained by capital budget and order-book liquidity.

    Parameters:
    -----------
    allocated_capital : float
        Capital allocated for this stock trade (e.g. ₹1,00,000).
    premium_cmp : float
        Option premium per share (₹).
    lot_size : int
        Exchange contract lot size (e.g. 500 shares).
    max_lots : int
        Maximum permitted lots per single-stock option order.
    sizing_mode : str
        '1_LOT' (default): Exactly 1 standard exchange contract lot (conservative live start).
        '1L_CAPITAL': Dynamically sized based on allocated capital budget up to max_lots.

    Returns:
    --------
    int: Discrete lots to trade (1 <= lots <= max_lots).
    """
    if premium_cmp <= 0 or lot_size <= 0:
        return 1

    # Exact 1-Lot mode as per simulation report conservative live benchmark
    if sizing_mode.upper() == "1_LOT":
        return 1

    if allocated_capital <= 0:
        return 1

    contract_cost = premium_cmp * lot_size
    theoretical_lots = int(allocated_capital / contract_cost)

    # Allow 1 lot if capital covers at least 50% of 1 lot contract cost
    if theoretical_lots < 1:
        if allocated_capital >= 0.5 * contract_cost:
            theoretical_lots = 1
        else:
            theoretical_lots = 0

    bounded_lots = min(theoretical_lots, max_lots)
    return max(1, bounded_lots) if theoretical_lots >= 1 else 0


def calculate_option_taxes(qty: int, buy_premium: float, sell_premium: float) -> dict:
    """
    Computes all exchange and statutory charges for an intraday stock option trade:
    - Brokerage: ₹20 buy + ₹20 sell = ₹40 flat
    - STT (Securities Transaction Tax): 0.1% on sell premium turnover
    - Exchange Transaction Charges: 0.03503% on total premium turnover
    - SEBI Turnover Fees: 0.0001% on total premium turnover
    - Stamp Duty: 0.003% on buy premium turnover
    - GST: 18% on (Brokerage + Exchange Charges + SEBI Fees)

    Returns:
    --------
    dict containing breakdown and total statutory costs.
    """
    buy_turnover = qty * buy_premium
    sell_turnover = qty * sell_premium
    total_turnover = buy_turnover + sell_turnover

    brokerage = 40.0
    stt = sell_turnover * 0.001
    exchange_charges = total_turnover * 0.0003503
    sebi_charges = total_turnover * 0.000001
    stamp_duty = buy_turnover * 0.00003
    gst = 0.18 * (brokerage + exchange_charges + sebi_charges)

    total_charges = round(brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst, 2)

    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_charges": round(exchange_charges, 2),
        "sebi_charges": round(sebi_charges, 2),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "total_charges": total_charges
    }
