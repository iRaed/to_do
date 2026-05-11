"""Vectorised technical indicators on pandas Series."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    roll_down = down.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = roll_up / roll_down
    out = 100.0 - (100.0 / (1.0 + rs))
    # roll_down == 0: pure up moves -> RSI 100; both 0 -> neutral 50
    out = out.where(roll_down != 0, 100.0)
    out = out.where(~((roll_up == 0) & (roll_down == 0)), 50.0)
    return out.fillna(50.0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def rolling_highest_high(high: pd.Series, lookback: int) -> pd.Series:
    """Highest high of the previous `lookback` candles (excluding current)."""
    return high.shift(1).rolling(lookback, min_periods=lookback).max()


def rolling_average_volume(volume: pd.Series, lookback: int = 20) -> pd.Series:
    """Average volume of the previous `lookback` candles (excluding current)."""
    return volume.shift(1).rolling(lookback, min_periods=lookback).mean()
