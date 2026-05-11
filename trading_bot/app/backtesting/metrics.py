"""Backtest performance metrics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List


@dataclass
class BacktestMetrics:
    total_trades: int
    win_rate: float
    total_return_pct: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    profit_factor: float
    max_drawdown_pct: float
    consecutive_wins: int
    consecutive_losses: int
    exposure_time_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(
    equity_curve: List[float],
    trade_pnls: List[float],
    candles_in_position: int,
    total_candles: int,
) -> BacktestMetrics:
    n = len(trade_pnls)
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = (len(wins) / n) if n else 0.0
    total_return_pct = ((equity_curve[-1] / equity_curve[0]) - 1.0) if len(equity_curve) >= 2 else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    largest_win = max(wins) if wins else 0.0
    largest_loss = min(losses) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Max drawdown
    peak = equity_curve[0] if equity_curve else 1.0
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Streaks
    cur_w = cur_l = max_w = max_l = 0
    for p in trade_pnls:
        if p > 0:
            cur_w += 1
            cur_l = 0
        elif p < 0:
            cur_l += 1
            cur_w = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)

    exposure = (candles_in_position / total_candles) if total_candles > 0 else 0.0
    return BacktestMetrics(
        total_trades=n,
        win_rate=win_rate,
        total_return_pct=total_return_pct,
        avg_win=avg_win,
        avg_loss=avg_loss,
        largest_win=largest_win,
        largest_loss=largest_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=max_dd,
        consecutive_wins=max_w,
        consecutive_losses=max_l,
        exposure_time_pct=exposure,
    )
