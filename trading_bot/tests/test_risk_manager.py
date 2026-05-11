"""Risk manager tests."""
import os
import time

import pytest

from app.config import KILL_SWITCH_FILE, reload_settings
from app.risk.risk_manager import RiskManager
from app.storage import repository as repo
from app.storage.db import init_db
from app.strategy.base import Signal


def _sig(symbol="BTC/USDT", price=100.0, sl=97.5):
    return Signal(
        symbol=symbol, side="buy", price=price,
        stop_loss=sl, take_profit_1=price * 1.03, take_profit_2=price * 1.06,
        strategy_name="test", raw={},
    )


def test_max_risk_rule(monkeypatch):
    monkeypatch.setenv("RISK_PER_TRADE", "0.06")
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "0.05")
    s = reload_settings()
    init_db()
    d = RiskManager(s).evaluate(_sig())
    assert not d.approved
    assert d.reason == "risk_per_trade_exceeds_max"


def test_max_open_positions_rule(monkeypatch):
    monkeypatch.setenv("MAX_OPEN_POSITIONS", "1")
    s = reload_settings()
    init_db()
    repo.create_position(
        symbol="ETH/USDT", side="long", status="open", mode="paper",
        entry_price=100.0, quantity=0.1, stop_loss=97.5,
        take_profit_1=103.0, take_profit_2=106.0, strategy_name="t",
    )
    d = RiskManager(s).evaluate(_sig(symbol="SOL/USDT"))
    assert not d.approved
    assert d.reason == "max_open_positions_reached"


def test_symbol_already_open(monkeypatch):
    s = reload_settings()
    init_db()
    repo.create_position(
        symbol="BTC/USDT", side="long", status="open", mode="paper",
        entry_price=100.0, quantity=0.1, stop_loss=97.5,
        take_profit_1=103.0, take_profit_2=106.0, strategy_name="t",
    )
    d = RiskManager(s).evaluate(_sig())
    assert not d.approved
    assert d.reason == "symbol_already_open"


def test_daily_loss_rule(monkeypatch):
    monkeypatch.setenv("MAX_DAILY_LOSS", "0.10")
    monkeypatch.setenv("ACCOUNT_EQUITY", "1000")
    s = reload_settings()
    init_db()
    tid = repo.create_trade(
        symbol="ZZ/USDT", side="buy", status="open", mode="paper",
        entry_price=100.0, quantity=1.0, stop_loss=95.0,
        take_profit_1=103, take_profit_2=106, strategy_name="t",
    )
    repo.close_trade(tid, exit_price=85.0, realized_pnl=-150.0, realized_pnl_pct=-0.15, fees=0.0, reason="stop_loss")
    d = RiskManager(s).evaluate(_sig())
    assert not d.approved
    assert d.reason == "max_daily_loss_reached"


def test_duplicate_signal_rule(monkeypatch):
    s = reload_settings()
    init_db()
    repo.save_signal(
        symbol="BTC/USDT", side="buy", strategy_name="t",
        price=100.0, raw={}, accepted=True,
    )
    d = RiskManager(s).evaluate(_sig())
    assert not d.approved
    assert d.reason == "duplicate_signal_5min"


def test_kill_switch_blocks(monkeypatch):
    s = reload_settings()
    init_db()
    KILL_SWITCH_FILE.write_text("kill")
    try:
        d = RiskManager(s).evaluate(_sig())
        assert not d.approved
        assert d.reason == "kill_switch_active"
    finally:
        if KILL_SWITCH_FILE.exists():
            KILL_SWITCH_FILE.unlink()


def test_min_notional_rule(monkeypatch):
    monkeypatch.setenv("MIN_NOTIONAL_USDT", "100000")
    s = reload_settings()
    init_db()
    d = RiskManager(s).evaluate(_sig())
    assert not d.approved
    assert d.reason and d.reason.startswith("notional_below_min")


def test_position_size_formula(monkeypatch):
    monkeypatch.setenv("ACCOUNT_EQUITY", "1000")
    monkeypatch.setenv("RISK_PER_TRADE", "0.03")
    s = reload_settings()
    rm = RiskManager(s)
    qty = rm.position_size(entry_price=100.0, stop_loss=97.0)
    # risk_amount = 30; stop_distance = 3; qty = 10
    assert abs(qty - 10.0) < 1e-9
