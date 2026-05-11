"""Indicator unit tests."""
import numpy as np
import pandas as pd

from app.strategy.indicators import ema, rolling_average_volume, rolling_highest_high, rsi


def test_ema_constant_series():
    s = pd.Series([10.0] * 50)
    out = ema(s, 20).dropna()
    assert np.allclose(out.values, 10.0)


def test_ema_responds_to_change():
    s = pd.Series([10.0] * 40 + [20.0] * 40)
    out = ema(s, 20).dropna()
    assert out.iloc[-1] > out.iloc[20]
    assert out.iloc[-1] < 20.0  # smoothed, not instant


def test_rsi_overbought_on_uptrend():
    s = pd.Series(np.linspace(100, 200, 100))
    r = rsi(s, 14).iloc[-1]
    assert r > 70


def test_rsi_oversold_on_downtrend():
    s = pd.Series(np.linspace(200, 100, 100))
    r = rsi(s, 14).iloc[-1]
    assert r < 30


def test_rolling_highest_high_excludes_current():
    h = pd.Series([1, 2, 3, 4, 5, 6, 7], dtype=float)
    hh = rolling_highest_high(h, 3)
    # At index 4: max of indices 1,2,3 = 4
    assert hh.iloc[4] == 4.0
    # At index 5: max of indices 2,3,4 = 5
    assert hh.iloc[5] == 5.0


def test_rolling_average_volume_excludes_current():
    v = pd.Series([10, 10, 10, 10, 100], dtype=float)
    av = rolling_average_volume(v, 4)
    assert av.iloc[4] == 10.0
