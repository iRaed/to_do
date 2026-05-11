"""Strategy unit tests."""
import numpy as np
import pandas as pd

from app.strategy.momentum_breakout import MomentumBreakoutStrategy


def _build_df(n: int = 200, breakout: bool = True, volume_spike: bool = True, downtrend: bool = False):
    """Build a candle frame whose state we control end-to-end.

    Strategy must see: EMA20>EMA50 with close above both, RSI 55–75, volume spike,
    and breakout above the prior `lookback` highest high.
    """
    rng = np.random.default_rng(42)
    if downtrend:
        base = np.linspace(200, 100, n)
        noise = rng.normal(0, 0.05, n)
        close = base + noise
    else:
        # Slight uptrend in baseline with oscillation so RSI lands mid-range
        base = 100.0 + 0.02 * np.arange(n)
        oscillation = 1.5 * np.sin(np.arange(n) * 0.6)
        noise = rng.normal(0, 0.15, n)
        close = base + oscillation + noise
    if breakout and not downtrend:
        # Push final candle clearly above prior 20-candle high
        prior_high = float(np.max(close[-21:-1]))
        close[-1] = prior_high * 1.02
    high = close + 0.3
    low = close - 0.3
    open_ = close - 0.05
    vol_base = np.full(n, 100.0)
    if volume_spike:
        vol_base[-1] = 1000.0
    df = pd.DataFrame({
        "ts": np.arange(n),
        "open": open_, "high": high, "low": low, "close": close, "volume": vol_base,
    })
    return df


def _strategy():
    return MomentumBreakoutStrategy(
        stop_loss_pct=0.025, tp1_pct=0.03, tp2_pct=0.06,
        volume_multiplier=1.5, breakout_lookback=20,
    )


def test_breakout_detection_generates_signal():
    df = _build_df()
    sig = _strategy().generate_signal("BTC/USDT", df)
    assert sig is not None
    assert sig.side == "buy"
    assert sig.stop_loss < sig.price
    assert sig.take_profit_1 > sig.price
    assert sig.take_profit_2 > sig.take_profit_1


def test_strategy_rejects_when_rsi_too_high():
    # parabolic ramp pushes RSI above 75
    n = 200
    close = np.geomspace(100, 250, n)
    df = pd.DataFrame({
        "ts": np.arange(n),
        "open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
        "close": close,
        "volume": np.concatenate([np.full(n - 1, 100.0), [1000.0]]),
    })
    sig = _strategy().generate_signal("BTC/USDT", df)
    assert sig is None


def test_strategy_rejects_when_volume_low():
    df = _build_df(volume_spike=False)
    sig = _strategy().generate_signal("BTC/USDT", df)
    assert sig is None


def test_strategy_rejects_when_no_breakout():
    df = _build_df(breakout=False)
    # also blunt last candle so it doesn't accidentally exceed prior high
    df.loc[df.index[-1], "close"] = float(df["close"].iloc[-30:-1].min())
    df.loc[df.index[-1], "high"] = df.loc[df.index[-1], "close"] + 0.1
    sig = _strategy().generate_signal("BTC/USDT", df)
    assert sig is None


def test_strategy_market_filter_blocks_eth_when_btc_weak():
    n = 200
    # Build a valid ETH breakout
    eth_df = _build_df(n=n, breakout=True, volume_spike=True)
    # BTC below its EMA50 (downtrend)
    btc_df = _build_df(n=n, breakout=False, volume_spike=False, downtrend=True)
    sig = _strategy().generate_signal("ETH/USDT", eth_df, context={"BTC/USDT": btc_df})
    assert sig is None
