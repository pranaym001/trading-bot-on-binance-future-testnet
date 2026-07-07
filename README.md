# ⚡ Binance Futures Testnet Trading Bot

A lightweight, production-quality Python CLI trading bot for **Binance USDT-M Futures Testnet** — featuring clean layered architecture, structured logging, and an optional web dashboard.

---

## Features

- **Market, Limit, and Stop-Limit orders** via CLI or web UI
- **BUY and SELL** sides with full input validation
- **CLI**: Click-based with interactive menu mode + direct commands
- **Web UI**: Flask dashboard with live order form, position viewer, and log tail
- **Logging**: Dual handlers — rotating JSON file log + colored console output
- **Error handling**: Clean messages for API errors, network failures, and bad input
- **DSA-backed**: Trie (symbol validation), LRU Cache (exchange info), Circular Buffer (trade history), Min-Heap (order queue), HashMap (O(1) order lookup)

---

## Project Structure

```
trading_bot/
├── bot/
│   ├── __init__.py          # Package exports
│   ├── client.py            # Binance REST client (HMAC-SHA256, LRU cache, retry stack)
│   ├── models.py            # Dataclasses: OrderRequest, OrderResponse, TradeHistory
│   ├── orders.py            # Order placement logic + min-heap queue
│   ├── validators.py        # Input validation (Trie-based symbol check)
│   └── logging_config.py   # Dual-handler structured logging
├── ui/
│   ├── app.py               # Flask dashboard app
│   ├── static/style.css     # Dashboard CSS (dark mode, glassmorphism)
│   └── templates/index.html # Dashboard HTML + vanilla JS
├── cli.py                   # CLI entry point (Click)
├── config.py                # Settings singleton (env vars / .env)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Get Testnet Credentials

1. Go to [testnet.binancefuture.com](https://testnet.binancefuture.com)
2. Register / log in
3. Navigate to **API Management** → **Create API**
4. Copy your **API Key** and **Secret Key**

### 2. Clone / Download

```bash
git clone <repository-url>
cd trading_bot
```

### 3. Create a Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Credentials

```bash
# Copy the example file
cp .env.example .env

# Edit .env with your credentials
# BINANCE_API_KEY=your_key
# BINANCE_API_SECRET=your_secret
```

---

## Running Examples

### CLI — Place Orders

**Market Order (BUY):**
```bash
python cli.py place-order --symbol BTCUSDT --side BUY --type MARKET --quantity 0.001
```

**Limit Order (SELL):**
```bash
python cli.py place-order --symbol ETHUSDT --side SELL --type LIMIT --quantity 0.01 --price 3000
```

**Stop-Limit Order (BUY):**
```bash
python cli.py place-order \
  --symbol BTCUSDT \
  --side BUY \
  --type STOP \
  --quantity 0.001 \
  --stop-price 65000 \
  --price 65500
```

### CLI — Other Commands

**View account balances:**
```bash
python cli.py account
```

**View open positions:**
```bash
python cli.py positions
```

**Get live price:**
```bash
python cli.py price BTCUSDT
```

**List recent orders:**
```bash
python cli.py list-orders --last 20
```

**Cancel an order:**
```bash
python cli.py cancel-order --symbol BTCUSDT --order-id 123456789
```

**Interactive menu mode:**
```bash
python cli.py interactive
# or simply:
python cli.py
```

### CLI — Flags

| Flag | Description |
|---|---|
| `--log-level` | File log verbosity: `DEBUG` / `INFO` / `WARNING` / `ERROR` (default: `DEBUG`) |
| `--console-level` | Console log verbosity (default: `INFO`) |
| `--no-strict-symbol` | Skip Trie-based symbol validation (useful for new/obscure pairs) |
| `--tif` | Time-in-force for LIMIT/STOP: `GTC` / `IOC` / `FOK` / `GTX` (default: `GTC`) |

### Web UI Dashboard

```bash
python ui/app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

**Dashboard features:**
- Real-time BTC / ETH price ticker (auto-refreshes every 10s)
- Account balance summary
- Open positions table
- Order placement form (Market / Limit / Stop-Limit)
- Order history table with cancel button
- Live log viewer with filter

---

## Log Files

Logs are written to the `logs/` directory:

| File | Contents |
|---|---|
| `logs/trading_bot.log` | All events (JSON lines, rotating, 5 × 5 MB) |
| `logs/orders.log` | Order-specific events only (filtered) |

**Example log entry:**
```json
{"ts": "2024-01-15T10:23:45", "level": "INFO", "logger": "bot.orders", "msg": "Order recorded — id=123456 symbol=BTCUSDT status=FILLED execQty=0.001 avgPrice=65234.5", "event": "order.recorded", "order_id": 123456, "symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "status": "FILLED", "executed_qty": "0.001", "avg_price": "65234.5"}
```

---

## Architecture & DSA Concepts

| Concept | Where Used | Complexity |
|---|---|---|
| **Trie (Prefix Tree)** | `validators.py` — symbol validation & autocomplete | O(L) lookup |
| **LRU Cache (OrderedDict)** | `client.py` — exchange info caching | O(1) get/put |
| **Circular Buffer (deque)** | `models.py` — bounded trade history | O(1) append |
| **HashMap (dict)** | `models.py`, `orders.py` — order ID → response | O(1) lookup |
| **Min-Heap (heapq)** | `orders.py` — order priority queue by price | O(log n) push/pop |
| **Stack (list)** | `client.py` — exponential backoff retry stack | O(1) push/pop |

---

## Assumptions

1. This bot targets the **Binance Futures USDT-M Testnet** only — do not use production keys.
2. Symbol validation uses a pre-loaded Trie of ~40 common pairs. Use `--no-strict-symbol` for others.
3. Quantity precision is not auto-adjusted per symbol — ensure your input matches the symbol's step size.
4. The Flask UI is single-user (no auth) — run it locally only.
5. Stop-Limit uses Binance type `STOP` (not `STOP_MARKET`) — both `price` and `stop-price` are required.

---

## Error Handling

| Error | Response |
|---|---|
| Invalid input (bad symbol, negative qty) | `ValidationError` → clear message + exit code 1 |
| Binance API error (e.g. insufficient balance) | `BinanceAPIError` → error code + message + exit code 2 |
| Network failure / timeout | `NetworkError` → retry with backoff → exit code 3 if exhausted |
| Missing credentials | `ValueError` → prompt to fill in `.env` |

---

## Requirements

- Python 3.9+
- `requests`
- `click`
- `flask`
- `python-dotenv`
