"""
bot/orders.py
~~~~~~~~~~~~~
High-level order placement logic.

DSA concepts:
  - Min-Heap (heapq): pending orders sorted by price — useful for TWAP/Grid
    style strategies; also demonstrates priority queue usage.
  - Hash Map (dict): O(1) lookup of any placed order by order_id.
  - TradeHistory (CircularBuffer + HashMap): bounded rolling history window.
"""

from __future__ import annotations

import heapq
import time
from typing import Dict, List, Optional, Tuple

from bot.client import BinanceClient, BinanceAPIError, NetworkError
from bot.logging_config import get_logger
from bot.models import (
    CircularBuffer,
    OrderRequest,
    OrderResponse,
    OrderSide,
    OrderType,
    TimeInForce,
    TradeHistory,
)
from bot.validators import validate_order_request, ValidationError
from config import settings

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Min-Heap Order Queue  (DSA: priority queue)
# ---------------------------------------------------------------------------

class OrderQueue:
    """
    Priority queue of pending OrderRequests, ordered by price (ascending).

    Used internally to buffer and dispatch orders in price-priority order —
    the foundation for any TWAP or Grid strategy.

    DSA: min-heap via heapq — push O(log n), pop O(log n).
    Tie-breaking on timestamp ensures FIFO within the same price level.
    """

    def __init__(self) -> None:
        self._heap: List[Tuple[float, float, OrderRequest]] = []
        # (price, timestamp, request)  — price=0 for MARKET orders

    def push(self, request: OrderRequest) -> None:
        priority = request.price if request.price else 0.0
        heapq.heappush(self._heap, (priority, request.timestamp, request))

    def pop(self) -> OrderRequest:
        _, _, req = heapq.heappop(self._heap)
        return req

    def peek(self) -> Optional[OrderRequest]:
        if self._heap:
            return self._heap[0][2]
        return None

    def __len__(self) -> int:
        return len(self._heap)

    def is_empty(self) -> bool:
        return len(self._heap) == 0


# ---------------------------------------------------------------------------
# OrderManager
# ---------------------------------------------------------------------------

class OrderManager:
    """
    Orchestrates order placement, tracking, and history management.

    Attributes
    ----------
    history   : TradeHistory  — rolling circular buffer + hashmap of placed orders
    pending   : OrderQueue    — min-heap of queued (not yet sent) orders
    _index    : Dict[int, OrderResponse] — fast O(1) id→response lookup
    """

    def __init__(self, client: Optional[BinanceClient] = None) -> None:
        self._client  = client or BinanceClient()
        self.history  = TradeHistory(capacity=settings.history_capacity)
        self.pending  = OrderQueue()
        self._index: Dict[int, OrderResponse] = {}

    # ── Internal helper ──────────────────────────────────────────────────

    def _submit(self, request: OrderRequest) -> OrderResponse:
        """
        Send a validated OrderRequest to Binance and record the response.
        Raises BinanceAPIError or NetworkError on failure.
        """
        params = request.to_api_params()
        raw    = self._client.place_order(params)

        response = OrderResponse.from_api_response(raw)
        self.history.add(response)
        self._index[response.order_id] = response

        log.info(
            "Order recorded — id=%s symbol=%s status=%s execQty=%s avgPrice=%s",
            response.order_id,
            response.symbol,
            response.status,
            response.executed_qty,
            response.avg_price,
            extra={
                "event": "order.recorded",
                "order_id": response.order_id,
                "symbol": response.symbol,
                "side": response.side,
                "type": response.order_type,
                "status": response.status,
                "orig_qty": response.orig_qty,
                "executed_qty": response.executed_qty,
                "avg_price": response.avg_price,
                "price": response.price,
            },
        )
        return response

    # ── Public order placement methods ───────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float | str,
        strict_symbol: bool = True,
    ) -> OrderResponse:
        """
        Place a MARKET order immediately.

        Parameters
        ----------
        symbol        : trading pair, e.g. 'BTCUSDT'
        side          : 'BUY' or 'SELL'
        quantity      : order size in base asset
        strict_symbol : validate symbol against known Trie
        """
        log.info("→ MARKET %s %s qty=%s", side.upper(), symbol.upper(), quantity)

        fields = validate_order_request(
            symbol=symbol,
            side=side,
            order_type="MARKET",
            quantity=quantity,
            strict_symbol=strict_symbol,
        )
        request = OrderRequest(**fields)
        return self._submit(request)

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float | str,
        price: float | str,
        time_in_force: str = "GTC",
        strict_symbol: bool = True,
    ) -> OrderResponse:
        """
        Place a LIMIT order at a specified price.

        Parameters
        ----------
        symbol        : trading pair
        side          : 'BUY' or 'SELL'
        quantity      : order size
        price         : limit price
        time_in_force : GTC / IOC / FOK / GTX  (default GTC)
        strict_symbol : validate symbol
        """
        log.info(
            "→ LIMIT %s %s qty=%s price=%s tif=%s",
            side.upper(), symbol.upper(), quantity, price, time_in_force,
        )

        fields = validate_order_request(
            symbol=symbol,
            side=side,
            order_type="LIMIT",
            quantity=quantity,
            price=price,
            time_in_force=time_in_force,
            strict_symbol=strict_symbol,
        )
        request = OrderRequest(**fields)
        # Enqueue in priority queue (will be dispatched immediately below)
        self.pending.push(request)
        dispatched = self.pending.pop()
        return self._submit(dispatched)

    def place_stop_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float | str,
        price: float | str,
        stop_price: float | str,
        time_in_force: str = "GTC",
        strict_symbol: bool = True,
    ) -> OrderResponse:
        """
        Place a STOP (stop-limit) order.

        Parameters
        ----------
        symbol     : trading pair
        side       : 'BUY' or 'SELL'
        quantity   : order size
        price      : limit price (execution price when stop triggers)
        stop_price : price that triggers the order
        """
        log.info(
            "→ STOP_LIMIT %s %s qty=%s price=%s stopPrice=%s",
            side.upper(), symbol.upper(), quantity, price, stop_price,
        )

        fields = validate_order_request(
            symbol=symbol,
            side=side,
            order_type="STOP",
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            strict_symbol=strict_symbol,
        )
        request = OrderRequest(**fields)
        return self._submit(request)

    # ── Utility methods ──────────────────────────────────────────────────

    def get_order(self, order_id: int) -> Optional[OrderResponse]:
        """O(1) lookup of a placed order by its Binance order ID."""
        return self._index.get(order_id)

    def get_recent_orders(self, n: int = 10) -> List[OrderResponse]:
        """Return last *n* orders (newest last)."""
        return self.history.recent(n)

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Fetch live open orders from Binance API."""
        return self._client.get_open_orders(symbol)

    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """Cancel an open order on Binance."""
        log.info("Cancelling order id=%s symbol=%s", order_id, symbol)
        return self._client.cancel_order(symbol, order_id)

    def get_account_balance(self) -> List[Dict]:
        """Return non-zero asset balances from account info."""
        account = self._client.get_account_info()
        assets  = account.get("assets", [])
        return [a for a in assets if float(a.get("walletBalance", 0)) != 0]

    def get_positions(self) -> List[Dict]:
        """Return open positions (positionAmt != 0)."""
        positions = self._client.get_positions()
        return [p for p in positions if float(p.get("positionAmt", 0)) != 0]

    def get_ticker(self, symbol: str) -> Optional[float]:
        """Get latest mark price for a symbol."""
        return self._client.get_ticker_price(symbol)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OrderManager":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Convenience factory (used by CLI)
# ---------------------------------------------------------------------------

def create_order_manager() -> OrderManager:
    """
    Build and return a fully initialised OrderManager.
    Validates credentials before returning.
    """
    settings.validate()
    client = BinanceClient()
    return OrderManager(client=client)
