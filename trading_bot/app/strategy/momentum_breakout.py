"""Momentum + volume breakout strategy (long-only spot)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from .base import Signal, StrategyBase
from .indicators import ema, rolling_average_volume, rolling_highest_high, rsi


class MomentumBreakoutStrategy(StrategyBase):
    name = "MomentumBreakout"

    def __init__(
        self,
        *,
        stop_loss_pct: float,
        tp1_pct: float,
        tp2_pct: float,
        volume_multiplier: float,
        breakout_lookback: int,
        rsi_min: float = 55.0,
        rsi_max: float = 75.0,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.tp1_pct = tp1_pct
        self.tp2_pct = tp2_pct
        self.volume_multiplier = volume_multiplier
        self.breakout_lookback = breakout_lookback
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max

    def _enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["ema20"] = ema(out["close"], 20)
        out["ema50"] = ema(out["close"], 50)
        out["rsi"] = rsi(out["close"], 14)
        out["hh"] = rolling_highest_high(out["high"], self.breakout_lookback)
        out["avg_vol"] = rolling_average_volume(out["volume"], 20)
        return out

    def generate_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Signal]:
        if df is None or len(df) < max(50, self.breakout_lookback + 5):
            return None
        ctx = context or {}
        e = self._enrich(df)
        row = e.iloc[-1]

        # Skip if any indicator is NaN
        for k in ("ema20", "ema50", "rsi", "hh", "avg_vol"):
            if pd.isna(row[k]):
                return None

        close = float(row["close"])
        cond_trend = close > row["ema20"] and close > row["ema50"] and row["ema20"] > row["ema50"]
        cond_rsi = self.rsi_min <= row["rsi"] <= self.rsi_max
        cond_volume = row["volume"] > self.volume_multiplier * row["avg_vol"]
        cond_breakout = close > row["hh"]

        # Optional market filter: ETH/SOL require BTC > EMA50
        cond_market = True
        if symbol.upper() in ("ETH/USDT", "SOL/USDT"):
            btc_df = ctx.get("BTC/USDT")
            if isinstance(btc_df, pd.DataFrame) and len(btc_df) >= 50:
                btc_ema50 = ema(btc_df["close"], 50).iloc[-1]
                if pd.isna(btc_ema50) or btc_df["close"].iloc[-1] <= btc_ema50:
                    cond_market = False

        if not (cond_trend and cond_rsi and cond_volume and cond_breakout and cond_market):
            return None

        entry = close
        sl = entry * (1.0 - self.stop_loss_pct)
        tp1 = entry * (1.0 + self.tp1_pct)
        tp2 = entry * (1.0 + self.tp2_pct)
        return Signal(
            symbol=symbol,
            side="buy",
            price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            strategy_name=self.name,
            raw={
                "ema20": float(row["ema20"]),
                "ema50": float(row["ema50"]),
                "rsi": float(row["rsi"]),
                "hh": float(row["hh"]),
                "avg_vol": float(row["avg_vol"]),
                "volume": float(row["volume"]),
                "market_filter": cond_market,
            },
        )
