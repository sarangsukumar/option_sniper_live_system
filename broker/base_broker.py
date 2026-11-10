"""
broker/base_broker.py
=============================================================================
Abstract Base Class for Broker Execution Interfaces.
Standardizes order placement, LTP lookup, position tracking, and square-off.
=============================================================================
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List


class BaseBroker(ABC):
    @abstractmethod
    def connect(self) -> bool:
        """Establishes authenticated connection with broker session."""
        pass

    @abstractmethod
    def get_ltp(self, symbol: str) -> float:
        """Fetches latest Last Traded Price (LTP) for symbol."""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str = "BUY",
        order_type: str = "MARKET",
        price: float = 0.0,
        tag: str = "OPTION_SNIPER"
    ) -> Dict[str, Any]:
        """
        Places order with the broker.

        Returns:
        --------
        dict: {'status': 'SUCCESS'|'FAILED', 'order_id': str, 'fill_price': float, 'message': str}
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancels an existing pending order."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Retrieves list of currently open positions."""
        pass

    @abstractmethod
    def square_off_all(self) -> List[Dict[str, Any]]:
        """Emergency or EOD clean liquidation of all open positions."""
        pass
