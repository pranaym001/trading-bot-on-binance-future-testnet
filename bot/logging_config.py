"""
bot/logging_config.py
~~~~~~~~~~~~~~~~~~~~~
Structured logging configuration for the trading bot.

  - RotatingFileHandler  : keeps log files manageable (5 × 5 MB)
  - StreamHandler        : colored console output via ANSI codes
  - JSONFormatter        : machine-readable structured logs in the file
  - HumanFormatter       : readable timestamped lines on the console
"""

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ── ANSI colour codes (works on Windows 10+ with VT enabled) ────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_GREY   = "\033[90m"

_LEVEL_COLORS = {
    logging.DEBUG:    _GREY,
    logging.INFO:     _GREEN,
    logging.WARNING:  _YELLOW,
    logging.ERROR:    _RED,
    logging.CRITICAL: _RED + _BOLD,
}

# ── Formatters ───────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """
    Emit each log record as a single-line JSON object.
    Fields: ts (ISO-8601), level, logger, message, [extra keys].
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Attach any extra fields (e.g., api_url, status_code) logged via
        # logger.info("...", extra={"api_url": "...", "status_code": 200})
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                try:
                    json.dumps(val)   # only attach JSON-serialisable extras
                    payload[key] = val
                except (TypeError, ValueError):
                    payload[key] = str(val)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """
    Colored, human-readable console formatter.
    Format: HH:MM:SS  LEVEL  logger — message
    """

    def format(self, record: logging.LogRecord) -> str:
        color   = _LEVEL_COLORS.get(record.levelno, _RESET)
        ts      = time.strftime("%H:%M:%S", time.localtime(record.created))
        level   = f"{color}{record.levelname:<8}{_RESET}"
        name    = f"{_CYAN}{record.name}{_RESET}"
        message = record.getMessage()

        line = f"{_GREY}{ts}{_RESET}  {level}  {name} — {message}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)

        return line


# ── Setup ────────────────────────────────────────────────────────────────────

_LOGGERS_CONFIGURED: set = set()


def setup_logging(
    log_dir: str = "logs",
    log_level: int = logging.DEBUG,
    console_level: int = logging.INFO,
) -> None:
    """
    Configure root logger with:
      1. A rotating JSON file handler → logs/trading_bot.log
      2. A colored console handler    → stdout

    Call once at application startup (idempotent — safe to call multiple times).
    """
    if "root" in _LOGGERS_CONFIGURED:
        return

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(log_level)

    # ── File handler (JSON structured) ────────────────────────────────────
    log_path = os.path.join(log_dir, "trading_bot.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(JSONFormatter())

    # ── Orders log: separate file just for order events ───────────────────
    orders_path = os.path.join(log_dir, "orders.log")
    orders_handler = logging.handlers.RotatingFileHandler(
        orders_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    orders_handler.setLevel(logging.INFO)
    orders_handler.setFormatter(JSONFormatter())
    orders_handler.addFilter(_OrderFilter())

    # ── Console handler (human-readable colored) ──────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(HumanFormatter())

    root.addHandler(file_handler)
    root.addHandler(orders_handler)
    root.addHandler(console_handler)

    _LOGGERS_CONFIGURED.add("root")

    root.debug("Logging initialised — file=%s, orders=%s", log_path, orders_path)


class _OrderFilter(logging.Filter):
    """Pass only log records tagged with event='order.*'."""

    def filter(self, record: logging.LogRecord) -> bool:
        event = getattr(record, "event", "")
        return isinstance(event, str) and event.startswith("order")


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.  Always call setup_logging() before this.
    Usage::
        log = get_logger(__name__)
        log.info("Hello", extra={"event": "order.placed", "order_id": 123})
    """
    return logging.getLogger(name)
