"""Backtester smoke test against a fake exchange."""
import numpy as np
import pandas as pd

from app.backtesting.backtester import Backtester
from app.config import reload_settings
from app.exchange.base import ExchangeBase, MarketInfo, OHLCV, OrderResult


class FakeExchange(ExchangeBase):
    name = "fake"

    def __init__(self, candles: list[OHLCV]):
        self._candles = candles

    def health_check(self) -> bool:
        return True

    def get_market_info(self, symbol: str) -> MarketInfo:
        return MarketInfo(symbol, "BTC", "USDT", 0.0001, 10.0, 6, 2)

    def fetch_ohlcv(self, symbol, timeframe, limit=200, since=None):
        rows = self._candles
        if since is not None:
            rows = [r for r in rows if r.timestamp > since]
        return rows[:limit]

    def fetch_ticker(self, symbol):
        return {"last": self._candles[-1].close}

    def fetch_balance(self):
        return {"USDT": 10000.0}

    def create_market_buy_order(self, symbol, quantity):
        raise NotImplementedError

    def create_market_sell_order(self, symbol, quantity):
        raise NotImplementedError


def _candles(n: int = 600) -> list[OHLCV]:
    rng = np.random.default_rng(7)
    base = 100 + np.cumsum(rng.normal(0.05, 0.5, n))
    # Inject several breakouts with volume spikes
    out: list[OHLCV] = []
    for i in range(n):
        c = float(base[i])
        h = c + 0.4
        l = c - 0.4
        v = 100.0
        if i in (120, 240, 360, 480) and i > 50:
            c = max(c, max(base[i - 25:i]) * 1.03)
            v = 1500.0
            h = c + 0.5
        out.append(OHLCV(timestamp=i * 60_000, open=c - 0.1, high=h, low=l, close=c, volume=v))
    return out


def test_backtester_runs():
    s = reload_settings()
    exchange = FakeExchange(_candles())
    bt = Backtester(s, exchange)
    report = bt.run("BTC/USDT", "5m", days=2)
    assert report.candles > 100
    assert report.metrics.total_trades >= 0
    assert report.starting_equity == s.ACCOUNT_EQUITY
    # equity stays positive
    assert report.final_equity > 0
