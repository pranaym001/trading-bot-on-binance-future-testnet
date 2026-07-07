"""
bot/models.py
~~~~~~~~~~~~~
Data models for the trading bot.

DSA concepts:
  - Dataclasses for structured, type-safe data containers.
  - CircularBuffer: O(1) append / O(n) iteration, fixed-size in-memory
    rolling window for recent trade history — avoids unbounded memory growth.
  - HashMap (dict): O(1) lookup of any past OrderResponse by order_id.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP = "STOP"          # stop-limit on Binance Futures


class TimeInForce(str, Enum):
    GTC = "GTC"   # Good Till Cancel
    IOC = "IOC"   # Immediate Or Cancel
    FOK = "FOK"   # Fill Or Kill
    GTX = "GTX"   # Good Till Crossing (post-only)


# ---------------------------------------------------------------------------
# Core request / response models
# ---------------------------------------------------------------------------

@dataclass
class OrderRequest:
    """Validated, ready-to-send order parameters."""

    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None          # Required for LIMIT / STOP
    stop_price: Optional[float] = None     # Required for STOP (stop-limit)
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_api_params(self) -> Dict[str, str]:
        """Serialize into Binance API query-string parameters."""
        params: Dict[str, str] = {
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.order_type.value,
            "quantity": str(self.quantity),
        }

        if self.order_type in (OrderType.LIMIT, OrderType.STOP):
            params["timeInForce"] = self.time_in_force.value

        if self.price is not None:
            params["price"] = str(self.price)

        if self.stop_price is not None:
            params["stopPrice"] = str(self.stop_price)

        if self.reduce_only:
            params["reduceOnly"] = "true"

        return params

    def summary(self) -> str:
        """Human-readable one-liner for logging / display."""
        parts = [
            f"[{self.order_type.value}]",
            f"{self.side.value}",
            f"{self.quantity} {self.symbol}",
        ]
        if self.price:
            parts.append(f"@ {self.price}")
        if self.stop_price:
            parts.append(f"stop={self.stop_price}")
        return " ".join(parts)


@dataclass
class OrderResponse:
    """Parsed Binance API order response."""

    order_id: int
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    orig_qty: str
    executed_qty: str
    avg_price: str
    status: str
    time_in_force: str
    price: str
    stop_price: Optional[str]
    raw: Dict                              # full raw JSON for auditing

    @classmethod
    def from_api_response(cls, data: Dict) -> "OrderResponse":
        """Factory: build an OrderResponse from the raw Binance JSON dict."""
        return cls(
            order_id=data["orderId"],
            client_order_id=data.get("clientOrderId", ""),
            symbol=data["symbol"],
            side=data["side"],
            order_type=data["type"],
            orig_qty=data.get("origQty", "0"),
            executed_qty=data.get("executedQty", "0"),
            avg_price=data.get("avgPrice", "0"),
            status=data["status"],
            time_in_force=data.get("timeInForce", ""),
            price=data.get("price", "0"),
            stop_price=data.get("stopPrice"),
            raw=data,
        )

    def display_lines(self) -> List[str]:
        """Return formatted lines suitable for CLI output."""
        lines = [
            f"  Order ID       : {self.order_id}",
            f"  Client OID     : {self.client_order_id}",
            f"  Symbol         : {self.symbol}",
            f"  Side           : {self.side}",
            f"  Type           : {self.order_type}",
            f"  Orig Qty       : {self.orig_qty}",
            f"  Executed Qty   : {self.executed_qty}",
            f"  Avg Price      : {self.avg_price}",
            f"  Status         : {self.status}",
        ]
        if self.price and self.price != "0":
            lines.append(f"  Limit Price    : {self.price}")
        if self.stop_price:
            lines.append(f"  Stop Price     : {self.stop_price}")
        return lines


# ---------------------------------------------------------------------------
# DSA: Circular Buffer for fixed-size trade history window
# ---------------------------------------------------------------------------

class CircularBuffer:
    """
    Fixed-capacity circular buffer backed by collections.deque(maxlen=N).

    - append()  : O(1) amortised
    - __iter__  : O(n)  — oldest → newest order

    Keeps only the last *capacity* entries, preventing unbounded growth
    during long-running sessions.
    """

    def __init__(self, capacity: int = 100) -> None:
        if capacity <= 0:
            raise ValueError("CircularBuffer capacity must be > 0")
        self._buf: Deque = deque(maxlen=capacity)
        self.capacity = capacity

    def append(self, item) -> None:
        self._buf.append(item)

    def __iter__(self):
        return iter(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    def to_list(self) -> List:
        return list(self._buf)

    def most_recent(self, n: int = 10) -> List:
        items = list(self._buf)
        return items[-n:] if n < len(items) else items


# ---------------------------------------------------------------------------
# TradeHistory: combines CircularBuffer + HashMap for O(1) lookup
# ---------------------------------------------------------------------------

class TradeHistory:
    """
    Thread-safe in-memory store of completed orders.

    DSA:
      - CircularBuffer   : rolling window (last N orders), O(1) insert
      - HashMap (dict)   : O(1) lookup by order_id
    """

    def __init__(self, capacity: int = 200) -> None:
        self._buffer: CircularBuffer = CircularBuffer(capacity)
        self._index: Dict[int, OrderResponse] = {}   # order_id → OrderResponse

    def add(self, response: OrderResponse) -> None:
        """Record a completed order."""
        self._buffer.append(response)
        self._index[response.order_id] = response

    def get(self, order_id: int) -> Optional[OrderResponse]:
        """O(1) lookup by order ID."""
        return self._index.get(order_id)

    def recent(self, n: int = 10) -> List[OrderResponse]:
        """Return last *n* orders, newest last."""
        return self._buffer.most_recent(n)

    def all(self) -> List[OrderResponse]:
        return self._buffer.to_list()

    def __len__(self) -> int:
        return len(self._buffer)
