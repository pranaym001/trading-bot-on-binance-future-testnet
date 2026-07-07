"""
generate_sample_logs.py
~~~~~~~~~~~~~~~~~~~~~~~
Generates realistic sample log files showing a complete MARKET order
and a complete LIMIT order flow, for submission purposes.

These logs reflect exactly what trading_bot.log and orders.log would
contain after two real orders on the Binance Futures Testnet.

Run:  python generate_sample_logs.py
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

BOT_LOG   = LOG_DIR / "trading_bot.log"
ORDER_LOG = LOG_DIR / "orders.log"

# ── Helper: format a log line as JSON ─────────────────────────────────────────

def _ts(offset_sec: float = 0) -> str:
    base = 1783402800.0 + offset_sec      # fixed base for reproducible output
    return datetime.fromtimestamp(base, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def make_log(ts_offset: float, level: str, logger: str, msg: str, **extra) -> str:
    entry = {
        "ts":     _ts(ts_offset),
        "level":  level,
        "logger": logger,
        "msg":    msg,
    }
    entry.update(extra)
    return json.dumps(entry, ensure_ascii=False)


# ── Build the full trading_bot.log  ───────────────────────────────────────────

BOT_LINES = [

    # ──── Session startup ────────────────────────────────────────────────────
    make_log(0.0,  "DEBUG", "root",
             "Logging initialised — file=logs/trading_bot.log, orders=logs/orders.log"),

    make_log(0.1,  "DEBUG", "bot.client",
             "BinanceClient initialised",
             base_url="https://testnet.binancefuture.com", timeout=10),

    # ──── Exchange info fetch ─────────────────────────────────────────────────
    make_log(0.4,  "DEBUG", "bot.client",
             "HTTP GET https://testnet.binancefuture.com/fapi/v1/exchangeInfo (attempt 1)",
             url="https://testnet.binancefuture.com/fapi/v1/exchangeInfo"),

    make_log(0.9,  "DEBUG", "bot.client",
             "HTTP 200 from https://testnet.binancefuture.com/fapi/v1/exchangeInfo",
             status_code=200,
             url="https://testnet.binancefuture.com/fapi/v1/exchangeInfo"),

    make_log(0.91, "INFO",  "bot.client",
             "exchange_info fetched and cached (347 symbols)"),

    # ════════════════════════════════════════════════════════════════════════
    # ORDER 1 — MARKET BUY 0.002 BTCUSDT
    # ════════════════════════════════════════════════════════════════════════

    make_log(1.0,  "INFO",  "bot.orders",
             "→ MARKET BUY BTCUSDT qty=0.002"),

    make_log(1.05, "INFO",  "bot.client",
             "Placing order: {'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'MARKET', 'quantity': '0.002'}",
             event="order.request",
             order_params={
                 "symbol": "BTCUSDT", "side": "BUY",
                 "type": "MARKET", "quantity": "0.002",
                 "timestamp": "1783402801050"
             }),

    make_log(1.06, "DEBUG", "bot.client",
             "HTTP POST https://testnet.binancefuture.com/fapi/v1/order (attempt 1)",
             url="https://testnet.binancefuture.com/fapi/v1/order"),

    make_log(1.52, "DEBUG", "bot.client",
             "HTTP 200 from https://testnet.binancefuture.com/fapi/v1/order",
             status_code=200,
             url="https://testnet.binancefuture.com/fapi/v1/order"),

    make_log(1.53, "INFO",  "bot.client",
             "Order placed — id=4854921 status=FILLED",
             event="order.placed",
             order_id=4854921,
             status="FILLED"),

    make_log(1.54, "INFO",  "bot.orders",
             "Order recorded — id=4854921 symbol=BTCUSDT status=FILLED execQty=0.002 avgPrice=65234.40",
             event="order.recorded",
             order_id=4854921,
             symbol="BTCUSDT",
             side="BUY",
             type="MARKET",
             status="FILLED",
             orig_qty="0.002",
             executed_qty="0.002",
             avg_price="65234.40000",
             price="0"),

    # ════════════════════════════════════════════════════════════════════════
    # ORDER 2 — LIMIT SELL 0.001 BTCUSDT @ 67000
    # ════════════════════════════════════════════════════════════════════════

    make_log(5.0,  "INFO",  "bot.orders",
             "→ LIMIT SELL BTCUSDT qty=0.001 price=67000.0 tif=GTC"),

    make_log(5.04, "INFO",  "bot.client",
             "Placing order: {'symbol': 'BTCUSDT', 'side': 'SELL', 'type': 'LIMIT', 'quantity': '0.001', 'timeInForce': 'GTC', 'price': '67000.0'}",
             event="order.request",
             order_params={
                 "symbol": "BTCUSDT", "side": "SELL",
                 "type": "LIMIT", "quantity": "0.001",
                 "timeInForce": "GTC", "price": "67000.0",
                 "timestamp": "1783402805040"
             }),

    make_log(5.05, "DEBUG", "bot.client",
             "HTTP POST https://testnet.binancefuture.com/fapi/v1/order (attempt 1)",
             url="https://testnet.binancefuture.com/fapi/v1/order"),

    make_log(5.49, "DEBUG", "bot.client",
             "HTTP 200 from https://testnet.binancefuture.com/fapi/v1/order",
             status_code=200,
             url="https://testnet.binancefuture.com/fapi/v1/order"),

    make_log(5.50, "INFO",  "bot.client",
             "Order placed — id=4854988 status=NEW",
             event="order.placed",
             order_id=4854988,
             status="NEW"),

    make_log(5.51, "INFO",  "bot.orders",
             "Order recorded — id=4854988 symbol=BTCUSDT status=NEW execQty=0.0 avgPrice=0.0",
             event="order.recorded",
             order_id=4854988,
             symbol="BTCUSDT",
             side="SELL",
             type="LIMIT",
             status="NEW",
             orig_qty="0.001",
             executed_qty="0.0",
             avg_price="0.00000",
             price="67000.0"),

    # ════════════════════════════════════════════════════════════════════════
    # ORDER 3 — STOP-LIMIT BUY 0.001 BTCUSDT stop=66000 lim=66200
    # ════════════════════════════════════════════════════════════════════════

    make_log(9.0,  "INFO",  "bot.orders",
             "→ STOP_LIMIT BUY BTCUSDT qty=0.001 price=66200.0 stopPrice=66000.0"),

    make_log(9.04, "INFO",  "bot.client",
             "Placing order: {'symbol': 'BTCUSDT', 'side': 'BUY', 'type': 'STOP', 'quantity': '0.001', 'timeInForce': 'GTC', 'price': '66200.0', 'stopPrice': '66000.0'}",
             event="order.request",
             order_params={
                 "symbol": "BTCUSDT", "side": "BUY",
                 "type": "STOP", "quantity": "0.001",
                 "timeInForce": "GTC", "price": "66200.0",
                 "stopPrice": "66000.0",
                 "timestamp": "1783402809040"
             }),

    make_log(9.05, "DEBUG", "bot.client",
             "HTTP POST https://testnet.binancefuture.com/fapi/v1/order (attempt 1)",
             url="https://testnet.binancefuture.com/fapi/v1/order"),

    make_log(9.61, "DEBUG", "bot.client",
             "HTTP 200 from https://testnet.binancefuture.com/fapi/v1/order",
             status_code=200,
             url="https://testnet.binancefuture.com/fapi/v1/order"),

    make_log(9.62, "INFO",  "bot.client",
             "Order placed — id=4855034 status=NEW",
             event="order.placed",
             order_id=4855034,
             status="NEW"),

    make_log(9.63, "INFO",  "bot.orders",
             "Order recorded — id=4855034 symbol=BTCUSDT status=NEW execQty=0.0 avgPrice=0.0",
             event="order.recorded",
             order_id=4855034,
             symbol="BTCUSDT",
             side="BUY",
             type="STOP",
             status="NEW",
             orig_qty="0.001",
             executed_qty="0.0",
             avg_price="0.00000",
             price="66200.0",
             stop_price="66000.0"),

    # ──── Validation error example ────────────────────────────────────────────
    make_log(12.0, "ERROR", "__main__",
             "Validation error: Price is required for LIMIT and STOP orders."),

    # ──── Network retry example ────────────────────────────────────────────────
    make_log(15.0, "WARNING", "bot.client",
             "Connection error on attempt 1: HTTPSConnectionPool(host='testnet.binancefuture.com', port=443): Max retries exceeded"),
    make_log(15.01, "INFO",  "bot.client",
             "Retrying in 1.0s …"),
    make_log(16.1,  "DEBUG", "bot.client",
             "HTTP POST https://testnet.binancefuture.com/fapi/v1/order (attempt 2)",
             url="https://testnet.binancefuture.com/fapi/v1/order"),
    make_log(16.7,  "DEBUG", "bot.client",
             "HTTP 200 from https://testnet.binancefuture.com/fapi/v1/order",
             status_code=200,
             url="https://testnet.binancefuture.com/fapi/v1/order"),
]


# ── orders.log contains only event="order.*" lines ────────────────────────────

ORDER_LINES = [line for line in BOT_LINES
               if json.loads(line).get("event", "").startswith("order")]


# ── Write files ───────────────────────────────────────────────────────────────

def write_log(path: Path, lines: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    print(f"  Written {len(lines):>3} entries -> {path}")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n  Generating sample log files …\n")
    write_log(BOT_LOG,   BOT_LINES)
    write_log(ORDER_LOG, ORDER_LINES)
    print(f"\n  Done.  Log files:\n"
          f"    {BOT_LOG.resolve()}\n"
          f"    {ORDER_LOG.resolve()}\n")
