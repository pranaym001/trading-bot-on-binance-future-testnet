"""
trading_bot.bot
~~~~~~~~~~~~~~~
Core bot package: client, order logic, validation, and logging utilities.
"""

__version__ = "1.0.0"
__author__ = "Trading Bot"

from bot.models import OrderRequest, OrderResponse, TradeHistory
from bot.logging_config import get_logger

__all__ = [
    "OrderRequest",
    "OrderResponse",
    "TradeHistory",
    "get_logger",
]
