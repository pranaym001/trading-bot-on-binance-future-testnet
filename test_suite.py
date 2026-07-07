"""
test_suite.py
~~~~~~~~~~~~~
Self-contained validation suite for the trading bot.
Tests all DSA structures and validation logic without needing API credentials.
Run: python test_suite.py
"""

import sys
import traceback

PASS = 0
FAIL = 0


def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  [PASS]  {name}")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL]  {name}")
        print(f"          {e}")
        traceback.print_exc()
        FAIL += 1


# ── Models ─────────────────────────────────────────────────────────────────────

def test_circular_buffer():
    from bot.models import CircularBuffer
    buf = CircularBuffer(5)
    for i in range(8):
        buf.append(i)
    assert buf.to_list() == [3, 4, 5, 6, 7], f"got {buf.to_list()}"
    assert len(buf) == 5
    assert buf.most_recent(3) == [5, 6, 7]


def test_trade_history():
    from bot.models import TradeHistory, OrderResponse
    th = TradeHistory(capacity=10)
    for i in range(5):
        resp = OrderResponse(
            order_id=i, client_order_id=f"cid{i}", symbol="BTCUSDT",
            side="BUY", order_type="MARKET", orig_qty="0.001",
            executed_qty="0.001", avg_price="65000", status="FILLED",
            time_in_force="GTC", price="0", stop_price=None, raw={}
        )
        th.add(resp)
    assert th.get(3) is not None
    assert th.get(3).order_id == 3
    assert th.get(99) is None
    assert len(th.recent(3)) == 3


def test_order_request_params():
    from bot.models import OrderRequest, OrderSide, OrderType, TimeInForce
    req = OrderRequest(
        symbol="BTCUSDT", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, quantity=0.001,
        price=65000.0, time_in_force=TimeInForce.GTC
    )
    params = req.to_api_params()
    assert params["symbol"] == "BTCUSDT"
    assert params["timeInForce"] == "GTC"
    assert params["price"] == "65000.0"
    assert "stopPrice" not in params


# ── Validators ─────────────────────────────────────────────────────────────────

def test_trie_symbol():
    from bot.validators import SymbolTrie
    t = SymbolTrie()
    for s in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
        t.insert(s)
    assert t.search("BTCUSDT")
    assert not t.search("XYZUSDT")
    assert t.starts_with("ETH")
    sug = t.suggestions("BNB")
    assert "BNBUSDT" in sug
    assert len(t) == 3


def test_validate_symbol():
    from bot.validators import validate_symbol, ValidationError
    assert validate_symbol("btcusdt", strict=False) == "BTCUSDT"
    try:
        validate_symbol("", strict=False)
        assert False, "Should have raised"
    except ValidationError:
        pass
    try:
        validate_symbol("INVALID@!", strict=False)
        assert False, "Should have raised"
    except ValidationError:
        pass


def test_validate_side():
    from bot.validators import validate_side, ValidationError
    from bot.models import OrderSide
    assert validate_side("buy") == OrderSide.BUY
    assert validate_side("SELL") == OrderSide.SELL
    try:
        validate_side("LONG")
        assert False
    except ValidationError:
        pass


def test_validate_quantity():
    from bot.validators import validate_quantity, ValidationError
    assert validate_quantity(0.001) == 0.001
    assert validate_quantity("0.5") == 0.5
    try:
        validate_quantity(-1)
        assert False
    except ValidationError:
        pass
    try:
        validate_quantity(0)
        assert False
    except ValidationError:
        pass


def test_validate_price():
    from bot.validators import validate_price, ValidationError
    assert validate_price(65000) == 65000.0
    assert validate_price(None, required=False) is None
    try:
        validate_price(None, required=True)
        assert False
    except ValidationError:
        pass
    try:
        validate_price(-100)
        assert False
    except ValidationError:
        pass


def test_full_market_validation():
    from bot.validators import validate_order_request
    r = validate_order_request("BTCUSDT", "BUY", "MARKET", 0.001, strict_symbol=True)
    assert r["symbol"] == "BTCUSDT"
    assert r["price"] is None


def test_full_limit_validation():
    from bot.validators import validate_order_request, ValidationError
    r = validate_order_request("BTCUSDT", "SELL", "LIMIT", 0.001, price=65000, strict_symbol=True)
    assert r["price"] == 65000.0
    try:
        validate_order_request("BTCUSDT", "BUY", "LIMIT", 0.001, strict_symbol=True)  # no price
        assert False
    except ValidationError:
        pass


def test_stop_limit_validation():
    from bot.validators import validate_order_request, ValidationError
    r = validate_order_request("BTCUSDT", "BUY", "STOP", 0.001, price=66200, stop_price=66000, strict_symbol=True)
    assert r["stop_price"] == 66000.0
    assert r["price"] == 66200.0
    try:
        validate_order_request("BTCUSDT", "BUY", "STOP", 0.001, price=66000, stop_price=66000, strict_symbol=True)
        assert False, "Same price/stop should fail"
    except ValidationError:
        pass


# ── Client DSA ─────────────────────────────────────────────────────────────────

def test_lru_cache():
    from bot.client import LRUCache
    c = LRUCache(3)
    c.put("a", 1); c.put("b", 2); c.put("c", 3)
    assert c.get("a") == 1   # access 'a' → makes 'b' LRU
    c.put("d", 4)            # evicts 'b' (LRU)
    assert c.get("b") is None
    assert c.get("a") == 1
    assert c.get("d") == 4


def test_retry_stack():
    from bot.client import _build_retry_stack
    stack = _build_retry_stack(4, 2.0)
    assert len(stack) == 4
    assert stack[-1] == 1.0    # top: shortest wait
    assert stack[0] == 8.0     # bottom: longest wait
    # Popping simulates retrying
    waits = []
    while stack:
        waits.append(stack.pop())
    assert waits == [1.0, 2.0, 4.0, 8.0]


# ── Orders DSA ─────────────────────────────────────────────────────────────────

def test_order_queue_priority():
    from bot.orders import OrderQueue
    from bot.models import OrderRequest, OrderSide, OrderType, TimeInForce
    q = OrderQueue()
    for price in [65000, 63000, 64000]:
        req = OrderRequest("BTCUSDT", OrderSide.BUY, OrderType.LIMIT, 0.001, price=float(price))
        q.push(req)
    assert len(q) == 3
    first = q.pop()
    assert first.price == 63000.0   # lowest price first (min-heap)
    second = q.pop()
    assert second.price == 64000.0


# ── Log files ──────────────────────────────────────────────────────────────────

def test_log_files_exist_and_valid():
    import json
    from pathlib import Path
    bot_log   = Path("logs/trading_bot.log")
    order_log = Path("logs/orders.log")
    assert bot_log.exists(),   "trading_bot.log missing"
    assert order_log.exists(), "orders.log missing"

    with open(bot_log, encoding="utf-8") as f:
        entries = [json.loads(l) for l in f if l.strip()]
    assert len(entries) >= 5, "Expected at least 5 log entries"

    order_events = [e for e in entries if e.get("event","").startswith("order")]
    assert len(order_events) >= 6, "Expected events for 2+ orders (request+placed+recorded)"

    with open(order_log, encoding="utf-8") as f:
        o_entries = [json.loads(l) for l in f if l.strip()]
    # Every entry in orders.log must have an event starting with 'order'
    for e in o_entries:
        assert e.get("event","").startswith("order"), f"Non-order event in orders.log: {e}"


# ── Run all ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Trading Bot — Test Suite")
    print("=" * 60)

    print("\n[models.py]")
    test("CircularBuffer — capacity and wrap-around",     test_circular_buffer)
    test("TradeHistory — add, get O(1), recent",          test_trade_history)
    test("OrderRequest.to_api_params()",                  test_order_request_params)

    print("\n[validators.py]")
    test("Trie — insert, search, starts_with, suggests",  test_trie_symbol)
    test("validate_symbol — normalise + error cases",     test_validate_symbol)
    test("validate_side — case-insensitive + error",      test_validate_side)
    test("validate_quantity — positive + error cases",    test_validate_quantity)
    test("validate_price — optional + required + error",  test_validate_price)
    test("validate_order_request — MARKET (full)",        test_full_market_validation)
    test("validate_order_request — LIMIT price check",    test_full_limit_validation)
    test("validate_order_request — STOP price mismatch",  test_stop_limit_validation)

    print("\n[client.py]")
    test("LRUCache — capacity eviction, O(1) access",     test_lru_cache)
    test("_build_retry_stack — exponential backoff",      test_retry_stack)

    print("\n[orders.py]")
    test("OrderQueue — min-heap price priority",          test_order_queue_priority)

    print("\n[log files]")
    test("Log files — exist, valid JSON, order events",   test_log_files_exist_and_valid)

    print()
    print("=" * 60)
    print(f"  Results: {PASS} passed, {FAIL} failed")
    print("=" * 60 + "\n")
    sys.exit(0 if FAIL == 0 else 1)
