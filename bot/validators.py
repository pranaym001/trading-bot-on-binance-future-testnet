"""
bot/validators.py
~~~~~~~~~~~~~~~~~
Input validation for the trading bot CLI.

DSA concepts used:
  - Trie (Prefix Tree): O(L) symbol lookup where L = symbol length.
    Much faster than a list scan for large symbol universes (500+ symbols).
    Space: O(∑ lengths of all symbols).
  - Set: O(1) membership test for side / order-type enums.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from bot.models import OrderSide, OrderType, TimeInForce


# ---------------------------------------------------------------------------
# Trie — fast symbol validation
# ---------------------------------------------------------------------------

class _TrieNode:
    """Single node in the Trie."""
    __slots__ = ("children", "is_end")

    def __init__(self) -> None:
        self.children: Dict[str, "_TrieNode"] = {}
        self.is_end: bool = False


class SymbolTrie:
    """
    Trie that stores uppercase trading symbol strings.

    insert(symbol)  — O(L)
    search(symbol)  — O(L)
    starts_with(p)  — O(L) prefix check
    suggestions(p)  — O(L + K) autocomplete (K = number of suggestions)
    """

    def __init__(self) -> None:
        self._root = _TrieNode()
        self._size = 0

    def insert(self, symbol: str) -> None:
        symbol = symbol.upper().strip()
        node = self._root
        for ch in symbol:
            if ch not in node.children:
                node.children[ch] = _TrieNode()
            node = node.children[ch]
        if not node.is_end:
            node.is_end = True
            self._size += 1

    def search(self, symbol: str) -> bool:
        """Return True if exact symbol exists in the Trie."""
        node = self._root
        for ch in symbol.upper().strip():
            if ch not in node.children:
                return False
            node = node.children[ch]
        return node.is_end

    def starts_with(self, prefix: str) -> bool:
        """Return True if any symbol starts with *prefix*."""
        node = self._root
        for ch in prefix.upper().strip():
            if ch not in node.children:
                return False
            node = node.children[ch]
        return True

    def suggestions(self, prefix: str, limit: int = 5) -> List[str]:
        """Return up to *limit* symbols beginning with *prefix*."""
        prefix = prefix.upper().strip()
        node = self._root
        for ch in prefix:
            if ch not in node.children:
                return []
            node = node.children[ch]

        results: List[str] = []
        self._dfs(node, prefix, results, limit)
        return results

    def _dfs(self, node: _TrieNode, current: str, results: List[str], limit: int) -> None:
        if len(results) >= limit:
            return
        if node.is_end:
            results.append(current)
        for ch, child in sorted(node.children.items()):
            self._dfs(child, current + ch, results, limit)

    def __len__(self) -> int:
        return self._size


# ---------------------------------------------------------------------------
# Default known testnet symbols (pre-loaded into the Trie)
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS: List[str] = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "SOLUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT",
    "LINKUSDT", "UNIUSDT", "AVAXUSDT", "ATOMUSDT", "NEARUSDT",
    "FTMUSDT", "ALGOUSDT", "VETUSDT", "ICPUSDT", "FILUSDT",
    "TRXUSDT", "XLMUSDT", "EOSUSDT", "AAVEUSDT", "SUSHIUSDT",
    "SANDUSDT", "MANAUSDT", "AXSUSDT", "GALAUSDT", "APEUSDT",
    "GMTUSDT", "OPUSDT", "ARBUSDT", "LDOUSDT", "SUIUSDT",
    "PEPEUSDT", "SHIBUSDT", "FLOKIUSDT", "WIFUSDT", "BONKUSDT",
]

# Global trie instance — shared across the process
_symbol_trie: SymbolTrie = SymbolTrie()
for _sym in _DEFAULT_SYMBOLS:
    _symbol_trie.insert(_sym)


def load_symbols_into_trie(symbols: List[str]) -> None:
    """
    Bulk-load exchange symbols (from exchangeInfo) into the global Trie.
    Call once after fetching live symbol list from the API.
    """
    for s in symbols:
        _symbol_trie.insert(s)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,20}$")


class ValidationError(ValueError):
    """Raised when user input fails validation."""


def validate_symbol(symbol: str, strict: bool = True) -> str:
    """
    Validate and normalise a trading symbol.

    Parameters
    ----------
    symbol : raw user input
    strict : if True, also check against the Trie (known symbols).
             Set False during initial setup before exchange info is fetched.

    Returns the uppercased symbol on success, raises ValidationError otherwise.
    """
    if not symbol or not symbol.strip():
        raise ValidationError("Symbol must not be empty.")

    cleaned = symbol.strip().upper()

    if not _SYMBOL_RE.match(cleaned):
        raise ValidationError(
            f"Invalid symbol format '{symbol}'. "
            "Expected 3–20 uppercase alphanumeric characters (e.g. BTCUSDT)."
        )

    if strict and not _symbol_trie.search(cleaned):
        suggestions = _symbol_trie.suggestions(cleaned[:3], limit=5)
        hint = f"  Did you mean: {', '.join(suggestions)}" if suggestions else ""
        raise ValidationError(
            f"Unknown symbol '{cleaned}'.{hint}\n"
            "Use --no-strict-symbol to bypass this check."
        )

    return cleaned


def validate_side(side: str) -> OrderSide:
    """Parse and validate order side (BUY/SELL)."""
    cleaned = side.strip().upper()
    try:
        return OrderSide(cleaned)
    except ValueError:
        valid = [s.value for s in OrderSide]
        raise ValidationError(
            f"Invalid side '{side}'. Must be one of: {', '.join(valid)}."
        )


def validate_order_type(order_type: str) -> OrderType:
    """Parse and validate order type (MARKET/LIMIT/STOP)."""
    cleaned = order_type.strip().upper()
    try:
        return OrderType(cleaned)
    except ValueError:
        valid = [t.value for t in OrderType]
        raise ValidationError(
            f"Invalid order type '{order_type}'. Must be one of: {', '.join(valid)}."
        )


def validate_quantity(quantity: str | float) -> float:
    """Validate that quantity is a positive finite number."""
    try:
        qty = float(quantity)
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid quantity '{quantity}'. Must be a positive number.")

    if qty <= 0:
        raise ValidationError(f"Quantity must be > 0, got {qty}.")
    if qty > 1_000_000:
        raise ValidationError(f"Quantity {qty} exceeds maximum allowed (1,000,000).")

    return round(qty, 8)


def validate_price(price: str | float | None, required: bool = False) -> Optional[float]:
    """Validate an optional or required price field."""
    if price is None or str(price).strip() == "":
        if required:
            raise ValidationError("Price is required for LIMIT and STOP orders.")
        return None

    try:
        p = float(price)
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid price '{price}'. Must be a positive number.")

    if p <= 0:
        raise ValidationError(f"Price must be > 0, got {p}.")

    return round(p, 8)


def validate_time_in_force(tif: str) -> TimeInForce:
    """Parse and validate time-in-force value."""
    cleaned = tif.strip().upper()
    try:
        return TimeInForce(cleaned)
    except ValueError:
        valid = [t.value for t in TimeInForce]
        raise ValidationError(
            f"Invalid timeInForce '{tif}'. Must be one of: {', '.join(valid)}."
        )


def validate_order_request(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str | float,
    price: Optional[str | float] = None,
    stop_price: Optional[str | float] = None,
    time_in_force: str = "GTC",
    strict_symbol: bool = True,
) -> dict:
    """
    Fully validate all fields for a new order.

    Returns a clean dict ready to pass to ``OrderRequest(**result)``.
    Raises ``ValidationError`` on the first problem found.
    """
    sym   = validate_symbol(symbol, strict=strict_symbol)
    s     = validate_side(side)
    otype = validate_order_type(order_type)
    qty   = validate_quantity(quantity)
    tif   = validate_time_in_force(time_in_force)

    # Price is required for LIMIT and STOP orders
    price_required = otype in (OrderType.LIMIT, OrderType.STOP)
    p = validate_price(price, required=price_required)

    # Stop-price is required for STOP (stop-limit) orders
    sp: Optional[float] = None
    if otype == OrderType.STOP:
        sp = validate_price(stop_price, required=True)
        if p is not None and sp is not None:
            # Stop-price should be below limit price for buy-stop, etc.
            # We just ensure they are different here; the API enforces direction.
            if sp == p:
                raise ValidationError(
                    "Stop price and limit price must not be equal."
                )

    return {
        "symbol": sym,
        "side": s,
        "order_type": otype,
        "quantity": qty,
        "price": p,
        "stop_price": sp,
        "time_in_force": tif,
    }
