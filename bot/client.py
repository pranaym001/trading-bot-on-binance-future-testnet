"""
bot/client.py
~~~~~~~~~~~~~
Binance Futures Testnet REST client.

Design principles:
  - Thin wrapper around `requests.Session`; no third-party Binance SDK needed.
  - HMAC-SHA256 request signing per Binance API spec.
  - LRU Cache (collections.OrderedDict): caches exchange info to avoid
    hammering the API on repeated CLI calls — O(1) get/put, bounded size.
  - Retry Stack: an explicit stack (list) tracks pending retries with
    exponential back-off so the retry logic is transparent and testable.
  - All HTTP interactions are logged (request + response headers + body).
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bot.logging_config import get_logger
from config import settings

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# LRU Cache
# ---------------------------------------------------------------------------

class LRUCache:
    """
    Simple LRU cache backed by collections.OrderedDict.

    get(key)        — O(1) : returns value or None
    put(key, value) — O(1) : inserts / promotes; evicts LRU if full
    """

    def __init__(self, capacity: int = 64) -> None:
        if capacity <= 0:
            raise ValueError("LRUCache capacity must be > 0")
        self._cap = capacity
        self._data: OrderedDict = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._data:
            return None
        self._data.move_to_end(key)          # promote to MRU
        return self._data[key]

    def put(self, key: str, value: Any) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        if len(self._data) > self._cap:
            self._data.popitem(last=False)   # evict LRU (front)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BinanceAPIError(Exception):
    """Raised when Binance returns a non-2xx response or an error payload."""

    def __init__(self, code: int, message: str, http_status: int = 0) -> None:
        self.code       = code
        self.message    = message
        self.http_status = http_status
        super().__init__(f"Binance API error {code}: {message}")


class NetworkError(Exception):
    """Raised on connection/timeout failures."""


# ---------------------------------------------------------------------------
# Retry Stack helper
# ---------------------------------------------------------------------------

def _build_retry_stack(max_retries: int, backoff_base: float) -> List[float]:
    """
    Build a stack of wait durations using exponential back-off.

      Durations: [base^(n-1), ..., base^1, base^0]  (top = base^0 = shortest)

    DSA: stack (list with append/pop).  Pop the top delay before each retry.
    The shortest wait is tried first; longest is the final fallback.
    """
    return [backoff_base ** i for i in range(max_retries - 1, -1, -1)]


# ---------------------------------------------------------------------------
# Binance REST Client
# ---------------------------------------------------------------------------

class BinanceClient:
    """
    Authenticated Binance Futures REST client.

    Usage::
        client = BinanceClient()
        response = client.place_order(params)
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = "",
        timeout: int = 0,
        max_retries: int = 0,
        backoff_base: float = 0.0,
    ) -> None:
        self._api_key    = api_key    or settings.api_key
        self._api_secret = api_secret or settings.api_secret
        self._base_url   = (base_url  or settings.base_url).rstrip("/")
        self._timeout    = timeout    or settings.request_timeout
        self._max_retries = max_retries or settings.max_retries
        self._backoff    = backoff_base or settings.retry_backoff_base

        # LRU cache for exchange info (symbol → precision metadata)
        self._cache: LRUCache = LRUCache(capacity=64)

        # Persistent session with connection pooling
        self._session = self._build_session()

        log.debug(
            "BinanceClient initialised",
            extra={"base_url": self._base_url, "timeout": self._timeout},
        )

    # ── Session ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        # urllib3 retry only for connection-level errors (not HTTP 4xx/5xx)
        retry = Retry(
            total=0,               # we handle retries ourselves
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    # ── HMAC Signing ─────────────────────────────────────────────────────

    def _sign(self, params: Dict[str, str]) -> Dict[str, str]:
        """
        Append a HMAC-SHA256 'signature' field to params.
        Binance requires: signature = HMAC_SHA256(secret, query_string).
        """
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {**params, "signature": signature}

    def _auth_headers(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self._api_key}

    # ── Low-level request dispatcher ─────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, str]] = None,
        signed: bool = False,
    ) -> Any:
        """
        Execute an HTTP request with retry logic (stack-based backoff).

        Returns the parsed JSON body on success.
        Raises BinanceAPIError or NetworkError on failure.
        """
        params = params or {}

        if signed:
            params["timestamp"] = str(int(time.time() * 1000))
            params = self._sign(params)

        retry_stack = _build_retry_stack(self._max_retries, self._backoff)
        attempt = 0

        while True:
            attempt += 1
            log.debug(
                "HTTP %s %s (attempt %d)",
                method, url, attempt,
                extra={"url": url, "params": {k: v for k, v in params.items() if k != "signature"}},
            )

            try:
                response = self._session.request(
                    method,
                    url,
                    params=params if method == "GET" else None,
                    data=params  if method == "POST" else None,
                    headers=self._auth_headers(),
                    timeout=self._timeout,
                )
            except requests.exceptions.ConnectionError as exc:
                log.warning("Connection error on attempt %d: %s", attempt, exc)
                if not retry_stack:
                    raise NetworkError(f"Connection failed after {attempt} attempts: {exc}") from exc
                wait = retry_stack.pop()
                log.info("Retrying in %.1fs …", wait)
                time.sleep(wait)
                continue
            except requests.exceptions.Timeout as exc:
                log.warning("Request timed out on attempt %d", attempt)
                if not retry_stack:
                    raise NetworkError(f"Request timed out after {attempt} attempts") from exc
                wait = retry_stack.pop()
                time.sleep(wait)
                continue

            log.debug(
                "HTTP %d from %s",
                response.status_code, url,
                extra={"status_code": response.status_code, "url": url},
            )

            # Parse JSON
            try:
                data = response.json()
            except ValueError:
                raise BinanceAPIError(-1, f"Non-JSON response: {response.text[:200]}", response.status_code)

            # Binance error payload has "code" (negative int) + "msg" fields
            if isinstance(data, dict) and "code" in data and data["code"] < 0:
                err_code = data["code"]
                err_msg  = data.get("msg", "Unknown error")
                log.error(
                    "Binance API error %d: %s",
                    err_code, err_msg,
                    extra={"event": "order.error", "api_code": err_code, "api_msg": err_msg},
                )

                # Retry only on server-side transient errors (5xx equiv codes)
                transient = {-1000, -1001, -1007, -1016}
                if err_code in transient and retry_stack:
                    wait = retry_stack.pop()
                    log.info("Transient error — retrying in %.1fs …", wait)
                    time.sleep(wait)
                    continue

                raise BinanceAPIError(err_code, err_msg, response.status_code)

            return data

    # ── Public API methods ────────────────────────────────────────────────

    def get_exchange_info(self) -> Dict:
        """
        Fetch and cache exchange metadata (symbol filters, precision).
        Result cached in LRU cache under key 'exchange_info'.
        """
        cached = self._cache.get("exchange_info")
        if cached is not None:
            log.debug("exchange_info served from LRU cache")
            return cached

        url  = f"{self._base_url}/fapi/v1/exchangeInfo"
        data = self._request("GET", url, signed=False)
        self._cache.put("exchange_info", data)
        log.info("exchange_info fetched and cached (%d symbols)", len(data.get("symbols", [])))
        return data

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Return symbol-level metadata from exchange info (LRU cached)."""
        cache_key = f"sym:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        info = self.get_exchange_info()
        for sym_data in info.get("symbols", []):
            if sym_data["symbol"] == symbol:
                self._cache.put(cache_key, sym_data)
                return sym_data
        return None

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """Return the latest mark price for a symbol."""
        url  = f"{self._base_url}/fapi/v1/ticker/price"
        data = self._request("GET", url, params={"symbol": symbol}, signed=False)
        try:
            return float(data["price"])
        except (KeyError, ValueError):
            return None

    def place_order(self, params: Dict[str, str]) -> Dict:
        """POST /fapi/v1/order — place a new futures order."""
        url = f"{self._base_url}/fapi/v1/order"
        log.info(
            "Placing order: %s",
            {k: v for k, v in params.items() if k not in ("signature", "timestamp")},
            extra={"event": "order.request", "order_params": params},
        )
        data = self._request("POST", url, params=params, signed=True)
        log.info(
            "Order placed — id=%s status=%s",
            data.get("orderId"), data.get("status"),
            extra={"event": "order.placed", "order_id": data.get("orderId"), "status": data.get("status")},
        )
        return data

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """GET /fapi/v1/openOrders — list open orders."""
        url    = f"{self._base_url}/fapi/v1/openOrders"
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", url, params=params, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """DELETE /fapi/v1/order — cancel an order by ID."""
        url    = f"{self._base_url}/fapi/v1/order"
        params = {"symbol": symbol, "orderId": str(order_id)}
        data   = self._request("DELETE", url, params=params, signed=True)
        log.info(
            "Order cancelled — id=%s status=%s",
            data.get("orderId"), data.get("status"),
            extra={"event": "order.cancelled", "order_id": data.get("orderId")},
        )
        return data

    def get_account_info(self) -> Dict:
        """GET /fapi/v2/account — fetch account balance and positions."""
        url = f"{self._base_url}/fapi/v2/account"
        return self._request("GET", url, signed=True)

    def get_positions(self) -> List[Dict]:
        """GET /fapi/v2/positionRisk — fetch all open positions."""
        url = f"{self._base_url}/fapi/v2/positionRisk"
        return self._request("GET", url, signed=True)

    def close(self) -> None:
        """Release underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()
