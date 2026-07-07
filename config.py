"""
config.py
~~~~~~~~~
Centralised configuration for the trading bot.

Loads values from environment variables (or a .env file via python-dotenv).
All callers import the singleton `settings` object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Optional: load a .env file if present (python-dotenv)
try:
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=_dotenv_path, override=False)
except ImportError:
    pass  # python-dotenv not installed — rely on real env vars


@dataclass(frozen=True)
class Settings:
    """Immutable configuration object built from environment variables."""

    # ── Binance Testnet credentials ──────────────────────────────────────
    api_key: str = field(
        default_factory=lambda: os.environ.get("BINANCE_API_KEY", "")
    )
    api_secret: str = field(
        default_factory=lambda: os.environ.get("BINANCE_API_SECRET", "")
    )

    # ── Endpoints ────────────────────────────────────────────────────────
    base_url: str = field(
        default_factory=lambda: os.environ.get(
            "BINANCE_BASE_URL", "https://testnet.binancefuture.com"
        )
    )

    # ── Request / retry settings ─────────────────────────────────────────
    request_timeout: int = field(
        default_factory=lambda: int(os.environ.get("REQUEST_TIMEOUT", "10"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.environ.get("MAX_RETRIES", "3"))
    )
    retry_backoff_base: float = field(
        default_factory=lambda: float(os.environ.get("RETRY_BACKOFF_BASE", "1.5"))
    )

    # ── Logging ──────────────────────────────────────────────────────────
    log_dir: str = field(
        default_factory=lambda: os.environ.get("LOG_DIR", "logs")
    )
    log_level: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "DEBUG")
    )
    console_log_level: str = field(
        default_factory=lambda: os.environ.get("CONSOLE_LOG_LEVEL", "INFO")
    )

    # ── Trade history ────────────────────────────────────────────────────
    history_capacity: int = field(
        default_factory=lambda: int(os.environ.get("HISTORY_CAPACITY", "200"))
    )

    # ── Web UI ───────────────────────────────────────────────────────────
    ui_host: str = field(
        default_factory=lambda: os.environ.get("UI_HOST", "127.0.0.1")
    )
    ui_port: int = field(
        default_factory=lambda: int(os.environ.get("UI_PORT", "5000"))
    )
    ui_debug: bool = field(
        default_factory=lambda: os.environ.get("UI_DEBUG", "false").lower() == "true"
    )

    def validate(self) -> None:
        """Raise ValueError if required credentials are missing."""
        if not self.api_key:
            raise ValueError(
                "BINANCE_API_KEY is not set. "
                "Copy .env.example → .env and fill in your testnet credentials."
            )
        if not self.api_secret:
            raise ValueError(
                "BINANCE_API_SECRET is not set. "
                "Copy .env.example → .env and fill in your testnet credentials."
            )

    @property
    def futures_order_url(self) -> str:
        return f"{self.base_url}/fapi/v1/order"

    @property
    def futures_exchange_info_url(self) -> str:
        return f"{self.base_url}/fapi/v1/exchangeInfo"

    @property
    def futures_account_url(self) -> str:
        return f"{self.base_url}/fapi/v2/account"

    @property
    def futures_ticker_url(self) -> str:
        return f"{self.base_url}/fapi/v1/ticker/price"

    @property
    def futures_open_orders_url(self) -> str:
        return f"{self.base_url}/fapi/v1/openOrders"

    @property
    def futures_positions_url(self) -> str:
        return f"{self.base_url}/fapi/v2/positionRisk"


# Singleton — import this everywhere
settings = Settings()
