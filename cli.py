#!/usr/bin/env python3
"""
cli.py
~~~~~~
Command-line interface for the Binance Futures Testnet Trading Bot.

Features:
  - Click-based subcommands (place-order, list-orders, cancel-order,
    account, positions, price, interactive)
  - Rich colored terminal output (tables, banners, status blocks)
  - Input validation with helpful error messages
  - Interactive menu mode (bonus UX)
"""

from __future__ import annotations

import io
import logging
import sys
import time
from typing import Optional

# Force UTF-8 output on Windows so box-drawing / emoji render correctly
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import click

from bot.client import BinanceAPIError, NetworkError
from bot.logging_config import get_logger, setup_logging
from bot.models import OrderResponse
from bot.orders import OrderManager, create_order_manager
from bot.validators import ValidationError, validate_symbol
from config import settings

# ── ANSI colours (no third-party dependency) ─────────────────────────────────
_R  = "\033[0m"       # reset
_B  = "\033[1m"       # bold
_G  = "\033[32m"      # green
_Y  = "\033[33m"      # yellow
_C  = "\033[36m"      # cyan
_M  = "\033[35m"      # magenta
_W  = "\033[97m"      # bright white
_GR = "\033[90m"      # grey
_RED= "\033[31m"      # red
_BG_D = "\033[48;5;235m"  # dark background

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

BANNER = f"""
{_C}{_B}+======================================================+
|   {_W}[**] Binance Futures Testnet Trading Bot [**]{_C}       |
|   {_GR}USDT-M Perpetuals  |  REST API  |  v1.0.0{_C}          |
+======================================================+{_R}
"""


def _print_banner() -> None:
    click.echo(BANNER)


def _ok(msg: str) -> None:
    click.echo(f"  {_G}{_B}✔  {_R}{msg}")


def _warn(msg: str) -> None:
    click.echo(f"  {_Y}{_B}⚠  {_R}{msg}", err=True)


def _err(msg: str) -> None:
    click.echo(f"  {_RED}{_B}✘  {_R}{msg}", err=True)


def _section(title: str) -> None:
    w = 56
    line = "─" * w
    click.echo(f"\n{_C}{line}{_R}")
    click.echo(f"  {_B}{_W}{title}{_R}")
    click.echo(f"{_C}{line}{_R}")


def _print_order_response(resp: OrderResponse, request_summary: str) -> None:
    """Pretty-print a placed order's details."""
    _section("Order Request")
    click.echo(f"  {_GR}{request_summary}{_R}")

    _section("Order Response")
    for line in resp.display_lines():
        label, _, value = line.partition(":")
        status_color = _G if resp.status in ("FILLED", "NEW") else _Y
        if "Status" in label:
            click.echo(f"  {_GR}{label}:{_R}{status_color}{_B}{value}{_R}")
        else:
            click.echo(f"  {_GR}{label}:{_R}{_W}{value}{_R}")

    click.echo()
    if resp.status == "FILLED":
        _ok(f"Order FILLED — {resp.executed_qty} {resp.symbol} @ avg {resp.avg_price}")
    elif resp.status == "NEW":
        _ok(f"Order placed (NEW) — id={resp.order_id}")
    else:
        _warn(f"Order status: {resp.status}")


def _table(headers: list, rows: list) -> None:
    """Minimal aligned table renderer."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    sep   = "  ".join("─" * w for w in col_widths)
    hdr   = "  ".join(f"{_B}{_C}{h:<{col_widths[i]}}{_R}" for i, h in enumerate(headers))
    click.echo(f"  {hdr}")
    click.echo(f"  {_GR}{sep}{_R}")
    for row in rows:
        cells = "  ".join(f"{_W}{str(c):<{col_widths[i]}}{_R}" for i, c in enumerate(row))
        click.echo(f"  {cells}")
    click.echo()


# ---------------------------------------------------------------------------
# Error handler decorator
# ---------------------------------------------------------------------------

def _handle_errors(func):
    """Decorator: catch trading-bot exceptions and print clean messages."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValidationError as exc:
            _err(f"Validation error: {exc}")
            log.error("Validation error: %s", exc)
            sys.exit(1)
        except BinanceAPIError as exc:
            _err(f"Binance API error [{exc.code}]: {exc.message}")
            log.error("BinanceAPIError code=%s msg=%s", exc.code, exc.message)
            sys.exit(2)
        except NetworkError as exc:
            _err(f"Network error: {exc}")
            log.error("NetworkError: %s", exc)
            sys.exit(3)
        except ValueError as exc:
            _err(f"Configuration error: {exc}")
            log.error("Config error: %s", exc)
            sys.exit(4)
        except KeyboardInterrupt:
            click.echo(f"\n{_Y}Interrupted by user.{_R}")
            sys.exit(0)

    return wrapper


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.option("--log-level", default="DEBUG", show_default=True,
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
              help="File log verbosity level.")
@click.option("--console-level", default="INFO", show_default=True,
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
              help="Console log verbosity level.")
@click.pass_context
def cli(ctx: click.Context, log_level: str, console_level: str) -> None:
    """
    \b
    ⚡  Binance Futures Testnet Trading Bot
    ────────────────────────────────────────
    Place and manage orders on Binance USDT-M Futures Testnet.

    Run a subcommand, or omit one to enter interactive mode.
    """
    setup_logging(
        log_dir=settings.log_dir,
        log_level=getattr(logging, log_level.upper()),
        console_level=getattr(logging, console_level.upper()),
    )
    ctx.ensure_object(dict)

    if ctx.invoked_subcommand is None:
        _print_banner()
        ctx.invoke(interactive)


# ---------------------------------------------------------------------------
# place-order command
# ---------------------------------------------------------------------------

@cli.command("place-order")
@click.option("--symbol",       "-s",  required=True,  help="Trading pair, e.g. BTCUSDT")
@click.option("--side",         "-S",  required=True,  type=click.Choice(["BUY", "SELL"], case_sensitive=False), help="BUY or SELL")
@click.option("--type",         "-t",  "order_type",   required=True,  type=click.Choice(["MARKET", "LIMIT", "STOP"], case_sensitive=False), help="Order type")
@click.option("--quantity",     "-q",  required=True,  type=float,     help="Order quantity (base asset)")
@click.option("--price",        "-p",  default=None,   type=float,     help="Limit price (required for LIMIT/STOP)")
@click.option("--stop-price",   "-sp", default=None,   type=float,     help="Stop trigger price (required for STOP)")
@click.option("--tif",          default="GTC",         type=click.Choice(["GTC", "IOC", "FOK", "GTX"], case_sensitive=False), help="Time in force (LIMIT/STOP only)")
@click.option("--no-strict-symbol", is_flag=True, default=False,       help="Skip Trie-based symbol validation")
@_handle_errors
def place_order(
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float],
    stop_price: Optional[float],
    tif: str,
    no_strict_symbol: bool,
) -> None:
    """Place a MARKET, LIMIT, or STOP-LIMIT order on Binance Futures Testnet."""
    _print_banner()
    _section("Placing Order")

    strict = not no_strict_symbol
    sym    = symbol.upper()

    click.echo(f"  Symbol    : {_C}{_B}{sym}{_R}")
    click.echo(f"  Side      : {_G if side.upper()=='BUY' else _RED}{_B}{side.upper()}{_R}")
    click.echo(f"  Type      : {_W}{order_type.upper()}{_R}")
    click.echo(f"  Quantity  : {_W}{quantity}{_R}")
    if price:
        click.echo(f"  Price     : {_W}{price}{_R}")
    if stop_price:
        click.echo(f"  StopPrice : {_W}{stop_price}{_R}")
    click.echo()

    with create_order_manager() as mgr:
        ot = order_type.upper()
        if ot == "MARKET":
            resp = mgr.place_market_order(sym, side, quantity, strict_symbol=strict)
        elif ot == "LIMIT":
            if price is None:
                raise ValidationError("--price is required for LIMIT orders.")
            resp = mgr.place_limit_order(sym, side, quantity, price, tif, strict_symbol=strict)
        else:  # STOP
            if price is None or stop_price is None:
                raise ValidationError("--price and --stop-price are required for STOP orders.")
            resp = mgr.place_stop_limit_order(sym, side, quantity, price, stop_price, tif, strict_symbol=strict)

    summary = f"{ot} {side.upper()} {quantity} {sym}"
    if price:
        summary += f" @ {price}"
    _print_order_response(resp, summary)


# ---------------------------------------------------------------------------
# list-orders command
# ---------------------------------------------------------------------------

@cli.command("list-orders")
@click.option("--symbol", "-s", default=None, help="Filter by symbol (e.g. BTCUSDT)")
@click.option("--last",   "-n", default=10,   show_default=True, help="Show last N orders from history")
@_handle_errors
def list_orders(symbol: Optional[str], last: int) -> None:
    """List recent orders from in-session history and live open orders."""
    _print_banner()

    with create_order_manager() as mgr:
        _section(f"Last {last} Session Orders")
        history = mgr.get_recent_orders(last)
        if not history:
            _warn("No orders placed in this session.")
        else:
            rows = [
                [r.order_id, r.symbol, r.side, r.order_type, r.orig_qty, r.avg_price, r.status]
                for r in history
            ]
            _table(["Order ID", "Symbol", "Side", "Type", "Qty", "Avg Price", "Status"], rows)

        _section("Live Open Orders")
        try:
            open_orders = mgr.get_open_orders(symbol)
            if not open_orders:
                _warn("No open orders on exchange.")
            else:
                rows = [
                    [
                        o["orderId"],
                        o["symbol"],
                        o["side"],
                        o["type"],
                        o.get("origQty", "-"),
                        o.get("price", "-"),
                        o["status"],
                    ]
                    for o in open_orders
                ]
                _table(["Order ID", "Symbol", "Side", "Type", "Qty", "Price", "Status"], rows)
        except (BinanceAPIError, NetworkError) as exc:
            _warn(f"Could not fetch live orders: {exc}")


# ---------------------------------------------------------------------------
# cancel-order command
# ---------------------------------------------------------------------------

@cli.command("cancel-order")
@click.option("--symbol",   "-s", required=True, help="Trading pair, e.g. BTCUSDT")
@click.option("--order-id", "-i", required=True, type=int,  help="Binance order ID to cancel")
@_handle_errors
def cancel_order(symbol: str, order_id: int) -> None:
    """Cancel an open order by ID."""
    _print_banner()
    _section("Cancelling Order")
    click.echo(f"  Symbol   : {_C}{_B}{symbol.upper()}{_R}")
    click.echo(f"  Order ID : {_W}{order_id}{_R}\n")

    with create_order_manager() as mgr:
        result = mgr.cancel_order(symbol.upper(), order_id)

    _ok(f"Order {result.get('orderId')} cancelled — status: {result.get('status')}")


# ---------------------------------------------------------------------------
# account command
# ---------------------------------------------------------------------------

@cli.command("account")
@_handle_errors
def account() -> None:
    """Show testnet account balances."""
    _print_banner()
    _section("Account Balances")

    with create_order_manager() as mgr:
        balances = mgr.get_account_balance()

    if not balances:
        _warn("No non-zero balances found.")
        return

    rows = [
        [
            b.get("asset", "-"),
            b.get("walletBalance", "0"),
            b.get("availableBalance", "0"),
            b.get("unrealizedProfit", "0"),
        ]
        for b in balances
    ]
    _table(["Asset", "Wallet Balance", "Available", "Unrealized PnL"], rows)


# ---------------------------------------------------------------------------
# positions command
# ---------------------------------------------------------------------------

@cli.command("positions")
@_handle_errors
def positions() -> None:
    """Show open futures positions."""
    _print_banner()
    _section("Open Positions")

    with create_order_manager() as mgr:
        pos_list = mgr.get_positions()

    if not pos_list:
        _warn("No open positions.")
        return

    rows = [
        [
            p.get("symbol", "-"),
            p.get("positionSide", "BOTH"),
            p.get("positionAmt", "0"),
            p.get("entryPrice", "0"),
            p.get("markPrice", "0"),
            p.get("unRealizedProfit", "0"),
            p.get("leverage", "-"),
        ]
        for p in pos_list
    ]
    _table(["Symbol", "Side", "Qty", "Entry Price", "Mark Price", "Unrealized PnL", "Leverage"], rows)


# ---------------------------------------------------------------------------
# price command
# ---------------------------------------------------------------------------

@cli.command("price")
@click.argument("symbol")
@_handle_errors
def price(symbol: str) -> None:
    """Get latest mark price for SYMBOL (e.g. BTCUSDT)."""
    _print_banner()
    sym = symbol.upper()

    with create_order_manager() as mgr:
        p = mgr.get_ticker(sym)

    if p is None:
        _err(f"Could not fetch price for {sym}")
        sys.exit(1)

    _section(f"Mark Price — {sym}")
    click.echo(f"  {_C}{_B}{sym}{_R}  →  {_W}{_B}{p:,.4f} USDT{_R}\n")


# ---------------------------------------------------------------------------
# interactive command (bonus enhanced UX)
# ---------------------------------------------------------------------------

@cli.command("interactive")
@_handle_errors
def interactive() -> None:
    """Launch an interactive menu-driven session."""
    _print_banner()

    MENU = f"""
  {_B}{_W}Main Menu{_R}
  {_GR}─────────────────────────────────{_R}
  {_C}1{_R}  Place a Market order
  {_C}2{_R}  Place a Limit order
  {_C}3{_R}  Place a Stop-Limit order
  {_C}4{_R}  View account balances
  {_C}5{_R}  View open positions
  {_C}6{_R}  Get mark price
  {_C}7{_R}  Cancel an order
  {_C}0{_R}  Exit
  {_GR}─────────────────────────────────{_R}"""

    with create_order_manager() as mgr:
        while True:
            click.echo(MENU)
            choice = click.prompt(f"  {_B}Select option{_R}", default="0").strip()

            if choice == "0":
                click.echo(f"\n  {_G}Goodbye! Happy trading.{_R}\n")
                break

            elif choice == "1":
                _interactive_market(mgr)

            elif choice == "2":
                _interactive_limit(mgr)

            elif choice == "3":
                _interactive_stop_limit(mgr)

            elif choice == "4":
                _section("Account Balances")
                balances = mgr.get_account_balance()
                if balances:
                    rows = [[b.get("asset"), b.get("walletBalance"), b.get("availableBalance")] for b in balances]
                    _table(["Asset", "Wallet Balance", "Available"], rows)
                else:
                    _warn("No non-zero balances.")

            elif choice == "5":
                _section("Open Positions")
                pos = mgr.get_positions()
                if pos:
                    rows = [[p.get("symbol"), p.get("positionAmt"), p.get("entryPrice"), p.get("unRealizedProfit")] for p in pos]
                    _table(["Symbol", "Qty", "Entry Price", "Unrealized PnL"], rows)
                else:
                    _warn("No open positions.")

            elif choice == "6":
                sym = click.prompt(f"  {_B}Symbol{_R}", default="BTCUSDT").strip().upper()
                p = mgr.get_ticker(sym)
                if p:
                    _ok(f"{sym} mark price: {_W}{_B}{p:,.4f} USDT{_R}")
                else:
                    _err(f"Could not fetch price for {sym}")

            elif choice == "7":
                sym = click.prompt(f"  {_B}Symbol{_R}").strip().upper()
                oid = click.prompt(f"  {_B}Order ID{_R}", type=int)
                try:
                    result = mgr.cancel_order(sym, oid)
                    _ok(f"Cancelled order {result.get('orderId')} — status: {result.get('status')}")
                except (BinanceAPIError, NetworkError) as exc:
                    _err(str(exc))

            else:
                _warn("Invalid option. Please choose 0–7.")


def _prompt_symbol() -> str:
    while True:
        sym = click.prompt(f"  {_B}Symbol{_R}", default="BTCUSDT").strip().upper()
        if len(sym) >= 3:
            return sym
        _err("Symbol must be at least 3 characters.")


def _prompt_side() -> str:
    while True:
        side = click.prompt(f"  {_B}Side{_R} [BUY/SELL]", default="BUY").strip().upper()
        if side in ("BUY", "SELL"):
            return side
        _err("Side must be BUY or SELL.")


def _prompt_qty() -> float:
    while True:
        raw = click.prompt(f"  {_B}Quantity{_R}")
        try:
            qty = float(raw)
            if qty > 0:
                return qty
        except ValueError:
            pass
        _err("Enter a positive number.")


def _prompt_price(label: str = "Price") -> float:
    while True:
        raw = click.prompt(f"  {_B}{label}{_R}")
        try:
            p = float(raw)
            if p > 0:
                return p
        except ValueError:
            pass
        _err("Enter a positive number.")


def _interactive_market(mgr: OrderManager) -> None:
    _section("Place Market Order")
    sym  = _prompt_symbol()
    side = _prompt_side()
    qty  = _prompt_qty()
    try:
        resp = mgr.place_market_order(sym, side, qty, strict_symbol=False)
        _print_order_response(resp, f"MARKET {side} {qty} {sym}")
    except (ValidationError, BinanceAPIError, NetworkError) as exc:
        _err(str(exc))


def _interactive_limit(mgr: OrderManager) -> None:
    _section("Place Limit Order")
    sym   = _prompt_symbol()
    side  = _prompt_side()
    qty   = _prompt_qty()
    price = _prompt_price("Limit Price")
    tif   = click.prompt(f"  {_B}Time in Force{_R} [GTC/IOC/FOK]", default="GTC").strip().upper()
    try:
        resp = mgr.place_limit_order(sym, side, qty, price, tif, strict_symbol=False)
        _print_order_response(resp, f"LIMIT {side} {qty} {sym} @ {price}")
    except (ValidationError, BinanceAPIError, NetworkError) as exc:
        _err(str(exc))


def _interactive_stop_limit(mgr: OrderManager) -> None:
    _section("Place Stop-Limit Order")
    sym        = _prompt_symbol()
    side       = _prompt_side()
    qty        = _prompt_qty()
    stop_price = _prompt_price("Stop Trigger Price")
    lim_price  = _prompt_price("Limit Price")
    tif        = click.prompt(f"  {_B}Time in Force{_R} [GTC/IOC/FOK]", default="GTC").strip().upper()
    try:
        resp = mgr.place_stop_limit_order(sym, side, qty, lim_price, stop_price, tif, strict_symbol=False)
        _print_order_response(resp, f"STOP {side} {qty} {sym} lim={lim_price} stop={stop_price}")
    except (ValidationError, BinanceAPIError, NetworkError) as exc:
        _err(str(exc))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
