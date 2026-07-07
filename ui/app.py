"""
ui/app.py
~~~~~~~~~
Lightweight Flask web dashboard for the trading bot.

Provides a real-time view of:
  - Account balances
  - Open positions
  - Recent order history
  - Order placement form
  - Live log tail
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List

# Ensure project root is on path when running from ui/ directory
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from flask import Flask, jsonify, render_template, request, Response

from bot.client import BinanceAPIError, NetworkError
from bot.logging_config import get_logger, setup_logging
from bot.orders import OrderManager, create_order_manager
from bot.validators import ValidationError
from config import settings

setup_logging(log_dir=settings.log_dir)
log = get_logger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "trading-bot-secret-2024")

# Shared OrderManager instance for the web session
_manager: OrderManager | None = None


def _get_manager() -> OrderManager:
    global _manager
    if _manager is None:
        _manager = create_order_manager()
    return _manager


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Main dashboard page."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API endpoints (JSON)
# ---------------------------------------------------------------------------

@app.route("/api/account")
def api_account():
    """GET /api/account — return non-zero balances."""
    try:
        mgr      = _get_manager()
        balances = mgr.get_account_balance()
        return jsonify({"ok": True, "balances": balances})
    except Exception as exc:
        log.error("API /account error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/positions")
def api_positions():
    """GET /api/positions — return open positions."""
    try:
        mgr       = _get_manager()
        positions = mgr.get_positions()
        return jsonify({"ok": True, "positions": positions})
    except Exception as exc:
        log.error("API /positions error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/orders")
def api_orders():
    """GET /api/orders — recent session orders + live open orders."""
    try:
        mgr     = _get_manager()
        history = [r.raw for r in mgr.get_recent_orders(20)]

        try:
            symbol = request.args.get("symbol")
            live   = mgr.get_open_orders(symbol)
        except Exception:
            live = []

        return jsonify({"ok": True, "history": history, "open": live})
    except Exception as exc:
        log.error("API /orders error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/price/<symbol>")
def api_price(symbol: str):
    """GET /api/price/<SYMBOL> — latest mark price."""
    try:
        mgr   = _get_manager()
        price = mgr.get_ticker(symbol.upper())
        return jsonify({"ok": True, "symbol": symbol.upper(), "price": price})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/order", methods=["POST"])
def api_place_order():
    """
    POST /api/order
    Body (JSON):
      {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": 0.001,
        "price": null,
        "stop_price": null,
        "tif": "GTC"
      }
    """
    try:
        data       = request.get_json(force=True)
        symbol     = data.get("symbol", "").upper()
        side       = data.get("side", "").upper()
        order_type = data.get("type", "").upper()
        quantity   = float(data.get("quantity", 0))
        price      = data.get("price")
        stop_price = data.get("stop_price")
        tif        = data.get("tif", "GTC").upper()

        mgr = _get_manager()

        if order_type == "MARKET":
            resp = mgr.place_market_order(symbol, side, quantity, strict_symbol=False)
        elif order_type == "LIMIT":
            if not price:
                return jsonify({"ok": False, "error": "price required for LIMIT orders"}), 400
            resp = mgr.place_limit_order(symbol, side, quantity, float(price), tif, strict_symbol=False)
        elif order_type == "STOP":
            if not price or not stop_price:
                return jsonify({"ok": False, "error": "price and stop_price required for STOP orders"}), 400
            resp = mgr.place_stop_limit_order(
                symbol, side, quantity, float(price), float(stop_price), tif, strict_symbol=False
            )
        else:
            return jsonify({"ok": False, "error": f"Unsupported order type: {order_type}"}), 400

        log.info("Web UI placed order id=%s", resp.order_id)
        return jsonify({"ok": True, "order": resp.raw})

    except ValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 422
    except BinanceAPIError as exc:
        return jsonify({"ok": False, "error": f"Binance [{exc.code}]: {exc.message}"}), 502
    except NetworkError as exc:
        return jsonify({"ok": False, "error": f"Network error: {exc}"}), 503
    except Exception as exc:
        log.error("Unexpected error in /api/order: %s", exc, exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/cancel", methods=["POST"])
def api_cancel_order():
    """POST /api/cancel  Body: {"symbol": "BTCUSDT", "order_id": 12345}"""
    try:
        data     = request.get_json(force=True)
        symbol   = data["symbol"].upper()
        order_id = int(data["order_id"])
        mgr      = _get_manager()
        result   = mgr.cancel_order(symbol, order_id)
        return jsonify({"ok": True, "result": result})
    except (BinanceAPIError, NetworkError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/logs")
def api_logs():
    """GET /api/logs — return last 100 lines of the trading_bot.log."""
    try:
        log_path = Path(settings.log_dir) / "trading_bot.log"
        if not log_path.exists():
            return jsonify({"ok": True, "lines": []})

        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-100:]

        # Parse JSON lines, fall back to raw string
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"msg": line, "level": "INFO"})

        return jsonify({"ok": True, "lines": entries})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host=settings.ui_host,
        port=settings.ui_port,
        debug=settings.ui_debug,
    )
