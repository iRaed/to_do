"""Single-symbol backtester for MomentumBreakoutStrategy."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd

from ..config import Settings
from ..exchange.base import ExchangeBase
from ..strategy.indicators import ema
from ..strategy.momentum_breakout import MomentumBreakoutStrategy
from ..utils.logger import get_logger
from ..utils.time_utils import candles_since
from .metrics import BacktestMetrics, compute_metrics


logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    qty: float
    pnl: float
    pnl_pct: float
    reason: str


@dataclass
class BacktestReport:
    symbol: str
    timeframe: str
    candles: int
    metrics: BacktestMetrics
    trades: List[BacktestTrade] = field(default_factory=list)
    final_equity: float = 0.0
    starting_equity: float = 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candles": self.candles,
            "starting_equity": self.starting_equity,
            "final_equity": self.final_equity,
            "metrics": self.metrics.to_dict(),
            "trades": [t.__dict__ for t in self.trades],
        }


class Backtester:
    def __init__(self, settings: Settings, exchange: ExchangeBase):
        self.s = settings
        self.x = exchange
        self.strategy = MomentumBreakoutStrategy(
            stop_loss_pct=settings.STOP_LOSS_PCT,
            tp1_pct=settings.TP1_PCT,
            tp2_pct=settings.TP2_PCT,
            volume_multiplier=settings.VOLUME_MULTIPLIER,
            breakout_lookback=settings.BREAKOUT_LOOKBACK,
        )

    def _load(self, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
        target = candles_since(days, timeframe)
        rows: list = []
        since = None
        # Page in chunks of 1000
        while len(rows) < target:
            chunk = self.x.fetch_ohlcv(symbol, timeframe, limit=1000, since=since)
            if not chunk:
                break
            rows.extend(chunk)
            since = chunk[-1].timestamp + 1
            if len(chunk) < 1000:
                break
        df = pd.DataFrame(
            [(r.timestamp, r.open, r.high, r.low, r.close, r.volume) for r in rows],
            columns=["ts", "open", "high", "low", "close", "volume"],
        )
        df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
        if len(df) > target:
            df = df.tail(target).reset_index(drop=True)
        return df

    def run(self, symbol: str, timeframe: str, days: int, out_dir: Optional[str] = None) -> BacktestReport:
        df = self._load(symbol, timeframe, days)
        if df.empty:
            raise RuntimeError("No data fetched")
        df["ema20"] = ema(df["close"], 20)

        equity = self.s.ACCOUNT_EQUITY
        starting_equity = equity
        equity_curve: List[float] = [equity]
        trades: List[BacktestTrade] = []
        pnls: List[float] = []
        candles_in_position = 0

        in_pos = False
        entry_price = 0.0
        sl = tp1 = tp2 = 0.0
        qty = 0.0
        trailing: Optional[float] = None
        tp1_hit = False
        entry_ts = 0

        slip = self.s.PAPER_SLIPPAGE_PCT
        fee_rate = self.s.TAKER_FEE_PCT

        for i in range(50, len(df)):
            window = df.iloc[: i + 1]
            row = window.iloc[-1]
            ts = int(row["ts"])
            close = float(row["close"])
            ema20 = float(row["ema20"]) if not pd.isna(row["ema20"]) else close

            if in_pos:
                candles_in_position += 1
                exit_reason: Optional[str] = None
                exit_price = close

                if close <= sl:
                    exit_reason, exit_price = "stop_loss", sl
                elif close >= tp2:
                    exit_reason, exit_price = "take_profit_2", tp2
                else:
                    if not tp1_hit and close >= tp1:
                        tp1_hit = True
                        sl = max(sl, entry_price)
                        trailing = close * (1.0 - self.s.TRAILING_STOP_PCT)
                    if tp1_hit:
                        new_trailing = close * (1.0 - self.s.TRAILING_STOP_PCT)
                        if trailing is None or new_trailing > trailing:
                            trailing = new_trailing
                        if trailing and close <= trailing:
                            exit_reason, exit_price = "trailing_stop", trailing
                    if exit_reason is None and close < ema20:
                        exit_reason, exit_price = "below_ema20", close

                if exit_reason:
                    fill = exit_price * (1.0 - slip)
                    fees = fill * qty * fee_rate
                    pnl = (fill - entry_price) * qty - fees - (entry_price * qty * fee_rate)
                    pnl_pct = pnl / max(entry_price * qty, 1e-9)
                    equity += pnl
                    equity_curve.append(equity)
                    pnls.append(pnl)
                    trades.append(
                        BacktestTrade(
                            entry_ts=entry_ts,
                            exit_ts=ts,
                            entry=entry_price,
                            exit=fill,
                            qty=qty,
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            reason=exit_reason,
                        )
                    )
                    in_pos = False
                    trailing = None
                    tp1_hit = False
                continue

            # No position: look for entry
            sig = self.strategy.generate_signal(symbol, window, context=None)
            if sig is None:
                continue
            risk_amount = equity * self.s.RISK_PER_TRADE
            stop_distance = sig.price - sig.stop_loss
            if stop_distance <= 0:
                continue
            qty = risk_amount / stop_distance
            notional = qty * sig.price
            if notional < self.s.MIN_NOTIONAL_USDT:
                continue
            if notional > equity:  # cannot use leverage in v1
                qty = equity / sig.price * 0.99
                notional = qty * sig.price
                if notional < self.s.MIN_NOTIONAL_USDT:
                    continue
            entry_price = sig.price * (1.0 + slip)
            sl = sig.stop_loss
            tp1 = sig.take_profit_1
            tp2 = sig.take_profit_2
            entry_ts = ts
            in_pos = True
            tp1_hit = False
            trailing = None

        metrics = compute_metrics(
            equity_curve=equity_curve,
            trade_pnls=pnls,
            candles_in_position=candles_in_position,
            total_candles=len(df),
        )
        report = BacktestReport(
            symbol=symbol,
            timeframe=timeframe,
            candles=len(df),
            metrics=metrics,
            trades=trades,
            final_equity=equity,
            starting_equity=starting_equity,
        )

        if out_dir:
            self._save(report, out_dir)
        return report

    @staticmethod
    def _save(report: BacktestReport, out_dir: str) -> None:
        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        sym = report.symbol.replace("/", "")
        json_path = d / f"backtest_{sym}_{report.timeframe}.json"
        csv_path = d / f"backtest_{sym}_{report.timeframe}_trades.csv"
        json_path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["entry_ts", "exit_ts", "entry", "exit", "qty", "pnl", "pnl_pct", "reason"])
            for t in report.trades:
                w.writerow([t.entry_ts, t.exit_ts, t.entry, t.exit, t.qty, t.pnl, t.pnl_pct, t.reason])
        logger.info("backtest_saved", extra={"json": str(json_path), "csv": str(csv_path)})
