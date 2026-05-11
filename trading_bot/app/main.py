"""CLI entry point for the trading bot."""
from __future__ import annotations

import json
import signal as os_signal
import sys
import time
from typing import List, Optional

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from .alerts.telegram import build_telegram_from_settings
from .config import KILL_SWITCH_FILE, get_settings, reload_settings
from .exchange.binance_ccxt import build_binance_from_settings
from .execution.order_manager import OrderManager
from .execution.paper_broker import PaperBroker
from .risk.risk_manager import RiskManager
from .storage import repository as repo
from .storage.db import init_db
from .strategy.indicators import ema
from .strategy.momentum_breakout import MomentumBreakoutStrategy
from .utils.logger import configure_logging, get_logger, log_event


cli = typer.Typer(add_completion=False, help="Personal crypto trading bot (spot, v1)")
console = Console()
logger = get_logger(__name__)


def _df_from_ohlcv(ohlcv) -> pd.DataFrame:
    return pd.DataFrame(
        [(r.timestamp, r.open, r.high, r.low, r.close, r.volume) for r in ohlcv],
        columns=["ts", "open", "high", "low", "close", "volume"],
    ).sort_values("ts").reset_index(drop=True)


def _build_strategy(s):
    return MomentumBreakoutStrategy(
        stop_loss_pct=s.STOP_LOSS_PCT,
        tp1_pct=s.TP1_PCT,
        tp2_pct=s.TP2_PCT,
        volume_multiplier=s.VOLUME_MULTIPLIER,
        breakout_lookback=s.BREAKOUT_LOOKBACK,
    )


def _build_broker(settings):
    if settings.is_live:
        from .execution.live_broker import LiveBroker
        exchange = build_binance_from_settings()
        return LiveBroker(settings, exchange), exchange
    return PaperBroker(settings), build_binance_from_settings()


# --------------- CLI commands ---------------

@cli.command("run")
def run_cmd(
    once: bool = typer.Option(False, help="Run a single cycle then exit (useful for cron)."),
):
    """Run the live or paper trading loop."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    init_db()
    tg = build_telegram_from_settings()
    strategy = _build_strategy(settings)
    risk = RiskManager(settings)

    if settings.is_live:
        console.print("[bold red]LIVE TRADING ENABLED — real funds at risk[/bold red]")
    else:
        console.print(f"[bold green]Mode: {settings.MODE.upper()} (paper)[/bold green]")

    broker, exchange = _build_broker(settings)
    om = OrderManager(settings, broker, tg)
    tg.bot_started(settings.MODE, settings.SYMBOLS)
    repo.log_bot_event("bot_started", f"mode={settings.MODE} live={settings.is_live}")

    stop = {"flag": False}

    def _handle(_sig, _frame):
        stop["flag"] = True
        log_event(logger, "info", "shutdown_requested")

    os_signal.signal(os_signal.SIGINT, _handle)
    os_signal.signal(os_signal.SIGTERM, _handle)

    try:
        while not stop["flag"]:
            cycle_start = time.time()
            try:
                _cycle(settings, exchange, strategy, risk, om, tg)
            except Exception as exc:
                log_event(logger, "error", "cycle_error", err=str(exc))
                tg.exchange_error(str(exc))
            if once:
                break
            elapsed = time.time() - cycle_start
            sleep_for = max(1.0, settings.LOOP_INTERVAL_SECONDS - elapsed)
            for _ in range(int(sleep_for)):
                if stop["flag"]:
                    break
                time.sleep(1)
    finally:
        tg.bot_stopped("shutdown")
        repo.log_bot_event("bot_stopped", "shutdown")


def _cycle(settings, exchange, strategy, risk, om, tg) -> None:
    # 1. kill switch check
    if settings.kill_switch_active:
        log_event(logger, "warning", "kill_switch_active")
        tg.kill_switch()
        # Still manage existing positions if user opted in
        if not settings.KILL_SWITCH_CLOSE_POSITIONS:
            return

    # 2. fetch candles per symbol, in one place to limit API calls
    needed = max(200, settings.BREAKOUT_LOOKBACK + 60)
    market_data: dict[str, pd.DataFrame] = {}
    for sym in settings.SYMBOLS:
        ohlcv = exchange.fetch_ohlcv(sym, settings.TIMEFRAME, limit=needed)
        market_data[sym] = _df_from_ohlcv(ohlcv)

    # 3. manage existing positions
    for sym, df in market_data.items():
        pos = repo.open_position_for_symbol(sym)
        if pos is None or df.empty:
            continue
        last_close = float(df["close"].iloc[-1])
        ema20_series = ema(df["close"], 20)
        ema20_val = float(ema20_series.iloc[-1]) if not pd.isna(ema20_series.iloc[-1]) else last_close
        om.manage_position(pos, last_close, ema20_val)

    # 4. signals
    for sym, df in market_data.items():
        context = {"BTC/USDT": market_data.get("BTC/USDT")}
        sig = strategy.generate_signal(sym, df, context=context)
        if sig is None:
            continue
        log_event(logger, "info", "signal_detected", symbol=sym, price=sig.price)
        tg.signal_detected({
            "symbol": sig.symbol, "side": sig.side, "price": sig.price,
            "stop_loss": sig.stop_loss, "take_profit_1": sig.take_profit_1,
            "take_profit_2": sig.take_profit_2, "strategy_name": sig.strategy_name,
        })
        decision = risk.evaluate(sig)
        repo.save_signal(
            symbol=sig.symbol,
            side=sig.side,
            strategy_name=sig.strategy_name,
            price=sig.price,
            raw=sig.raw,
            accepted=decision.approved,
            rejection_reason=decision.reason,
        )
        if not decision.approved:
            log_event(logger, "warning", "signal_rejected", symbol=sym, reason=decision.reason)
            tg.signal_rejected(sym, decision.reason or "rejected")
            continue
        om.submit_entry(sig, decision.quantity)


@cli.command("backtest")
def backtest_cmd(
    symbol: str = typer.Option(..., "--symbol"),
    timeframe: str = typer.Option("5m", "--timeframe"),
    days: int = typer.Option(90, "--days"),
    out_dir: str = typer.Option("./data/backtests", "--out"),
):
    """Run a historical backtest."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    init_db()
    from .backtesting.backtester import Backtester
    exchange = build_binance_from_settings()
    bt = Backtester(settings, exchange)
    report = bt.run(symbol, timeframe, days, out_dir=out_dir)
    console.print_json(json.dumps(report.metrics.to_dict(), default=str))


@cli.command("status")
def status_cmd():
    """Show bot status."""
    settings = reload_settings()
    configure_logging(settings.LOG_LEVEL)
    init_db()
    t = Table(title="Bot Status")
    t.add_column("Key"); t.add_column("Value")
    t.add_row("MODE", settings.MODE)
    t.add_row("LIVE_TRADING", str(settings.LIVE_TRADING))
    t.add_row("Effective live?", str(settings.is_live))
    t.add_row("Kill switch", "ACTIVE" if settings.kill_switch_active else "off")
    t.add_row("Symbols", ", ".join(settings.SYMBOLS))
    t.add_row("Timeframe", settings.TIMEFRAME)
    t.add_row("Open positions", str(len(repo.get_open_positions())))
    t.add_row("Trades today", str(repo.trades_today_count()))
    t.add_row("Daily PnL %", f"{repo.daily_pnl_pct(settings.ACCOUNT_EQUITY):.2%}")
    t.add_row("Consec losses", str(repo.consecutive_losses()))
    console.print(t)


@cli.command("positions")
def positions_cmd():
    """Show open positions."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    init_db()
    positions = repo.get_open_positions()
    t = Table(title="Open Positions")
    for col in ("ID", "Symbol", "Mode", "Side", "Entry", "Qty", "SL", "TP1", "TP2", "TP1 hit", "Trailing"):
        t.add_column(col)
    for p in positions:
        t.add_row(
            str(p.id), p.symbol, p.mode, p.side,
            f"{p.entry_price:.4f}", f"{p.quantity:.6f}",
            f"{p.stop_loss:.4f}", f"{p.take_profit_1:.4f}", f"{p.take_profit_2:.4f}",
            "yes" if p.tp1_hit else "no",
            f"{p.trailing_stop:.4f}" if p.trailing_stop else "-",
        )
    console.print(t)


@cli.command("trades")
def trades_cmd(limit: int = typer.Option(20, "--limit")):
    """Show last trades."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    init_db()
    rows = repo.list_trades(limit)
    t = Table(title=f"Last {limit} Trades")
    for col in ("ID", "Symbol", "Mode", "Status", "Entry", "Exit", "Qty", "PnL", "PnL %", "Reason"):
        t.add_column(col)
    for r in rows:
        t.add_row(
            str(r.id), r.symbol, r.mode, r.status,
            f"{r.entry_price:.4f}" if r.entry_price else "-",
            f"{r.exit_price:.4f}" if r.exit_price else "-",
            f"{r.quantity:.6f}" if r.quantity else "-",
            f"{r.realized_pnl:.4f}",
            f"{(r.realized_pnl_pct or 0.0):.2%}",
            r.reason or "-",
        )
    console.print(t)


@cli.command("kill")
def kill_cmd():
    """Create the kill switch file."""
    KILL_SWITCH_FILE.write_text("kill")
    init_db()
    repo.log_bot_event("kill_switch_created", "kill switch file created", severity="warning")
    console.print(f"[bold red]Kill switch created at {KILL_SWITCH_FILE}[/bold red]")


@cli.command("unkill")
def unkill_cmd():
    """Remove the kill switch file."""
    if KILL_SWITCH_FILE.exists():
        KILL_SWITCH_FILE.unlink()
        init_db()
        repo.log_bot_event("kill_switch_removed", "kill switch file removed")
        console.print("[bold green]Kill switch removed[/bold green]")
    else:
        console.print("Kill switch was not active.")


@cli.command("check-config")
def check_config_cmd():
    """Print effective config (secrets redacted)."""
    s = reload_settings()
    console.print_json(json.dumps(s.safe_dump(), default=str))


@cli.command("webhook")
def webhook_cmd(host: str = "0.0.0.0", port: int = 8000):
    """Run FastAPI webhook server."""
    import uvicorn
    uvicorn.run("app.webhooks.tradingview:app", host=host, port=port, reload=False)


def main():
    cli()


if __name__ == "__main__":
    main()
