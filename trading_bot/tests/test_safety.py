"""Tests for hardening features: live confirmation gate, notional caps,
balance fetcher, command endpoint."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import LiveConfirmationMissing, reload_settings
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


# ---------- Live-mode confirmation gate ----------

def test_live_requested_without_understand_raises(monkeypatch):
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.delenv("I_UNDERSTAND_THIS_CAN_LOSE_MONEY", raising=False)
    s = reload_settings()
    assert s.live_requested is True
    assert s.is_live is False
    with pytest.raises(LiveConfirmationMissing):
        s.assert_live_allowed()


def test_live_with_understand_allowed(monkeypatch):
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("I_UNDERSTAND_THIS_CAN_LOSE_MONEY", "true")
    s = reload_settings()
    s.assert_live_allowed()  # does not raise
    assert s.is_live is True


def test_paper_mode_does_not_require_understand(monkeypatch):
    s = reload_settings()
    s.assert_live_allowed()  # no exception
    assert s.is_live is False


def test_livebroker_refuses_without_understand(monkeypatch):
    monkeypatch.setenv("MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.delenv("I_UNDERSTAND_THIS_CAN_LOSE_MONEY", raising=False)
    s = reload_settings()
    from app.execution.live_broker import LiveBroker, LiveTradingDisabled
    # We don't even reach exchange health check; the assert_live_allowed gate fires.
    with pytest.raises((LiveConfirmationMissing, LiveTradingDisabled)):
        LiveBroker(s, exchange=object())  # type: ignore[arg-type]


# ---------- MAX_ORDER_NOTIONAL_USDT ----------

def test_order_notional_cap(monkeypatch):
    # qty=10, notional=1000 — exceeds MAX_ORDER_NOTIONAL_USDT=250
    monkeypatch.setenv("MAX_ORDER_NOTIONAL_USDT", "250")
    s = reload_settings()
    init_db()
    d = RiskManager(s).evaluate(_sig(price=100.0, sl=97.0))
    assert not d.approved
    assert d.reason == "order_notional_exceeds_max"


# ---------- MAX_DAILY_NOTIONAL_USDT ----------

def test_daily_notional_cap(monkeypatch):
    # Allow a single order through but keep daily cap small so a second would breach.
    monkeypatch.setenv("MAX_ORDER_NOTIONAL_USDT", "10000")
    monkeypatch.setenv("MAX_DAILY_NOTIONAL_USDT", "900")
    s = reload_settings()
    init_db()
    # Seed an existing filled buy of 800 notional today.
    repo.save_order(
        symbol="XX/USDT", side="buy", status="filled", mode="paper",
        order_type="market", price=100.0, quantity=8.0, fees=0.0, reason="entry",
    )
    # Position size formula: qty = 1000*0.03 / 3 = 10, notional = 1000.
    d = RiskManager(s).evaluate(_sig(price=100.0, sl=97.0))
    assert not d.approved
    assert d.reason == "daily_notional_exceeds_max"


# ---------- Balance fetcher ----------

def test_balance_fetcher_insufficient(monkeypatch):
    monkeypatch.setenv("MAX_ORDER_NOTIONAL_USDT", "10000")
    monkeypatch.setenv("MAX_DAILY_NOTIONAL_USDT", "10000")
    s = reload_settings()
    init_db()

    def fetcher(_quote: str) -> float:
        return 5.0  # well below 1000 needed

    d = RiskManager(s).evaluate(_sig(price=100.0, sl=97.0), balance_fetcher=fetcher)
    assert not d.approved
    assert d.reason == "insufficient_balance"


def test_balance_fetcher_failure_is_blocking(monkeypatch):
    monkeypatch.setenv("MAX_ORDER_NOTIONAL_USDT", "10000")
    monkeypatch.setenv("MAX_DAILY_NOTIONAL_USDT", "10000")
    s = reload_settings()
    init_db()

    def fetcher(_quote: str) -> float:
        raise RuntimeError("network down")

    d = RiskManager(s).evaluate(_sig(price=100.0, sl=97.0), balance_fetcher=fetcher)
    assert not d.approved
    assert d.reason == "balance_check_failed"


# ---------- Startup checklist ----------

def test_startup_checklist_contains_required_keys(monkeypatch):
    s = reload_settings()
    from app.main import _build_startup_checklist
    lines = _build_startup_checklist(s)
    joined = "\n".join(lines)
    for key in (
        "mode:", "live trading enabled:", "symbols:", "timeframe:",
        "risk per trade:", "max open positions:", "daily loss limit:",
        "max order notional:", "max daily notional:", "kill switch:",
    ):
        assert key in joined


# ---------- Command endpoint ----------

@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setenv("COMMAND_SECRET", "topsecret")
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_SECRET", "tvsecret")
    reload_settings()
    from app.webhooks.tradingview import create_app
    return TestClient(create_app())


def test_command_requires_secret(app_client):
    r = app_client.post("/command", json={"secret": "wrong", "command": "status"})
    assert r.status_code == 401


def test_command_status(app_client):
    r = app_client.post("/command", json={"secret": "topsecret", "command": "status"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "paper"
    assert body["live"] is False
    assert "open_positions" in body
    assert "daily_notional_usdt" in body


def test_command_kill_unkill(app_client):
    from app.config import KILL_SWITCH_FILE
    r = app_client.post("/command", json={"secret": "topsecret", "command": "/kill"})
    assert r.status_code == 200
    assert r.json()["kill_switch"] is True
    assert KILL_SWITCH_FILE.exists()
    r = app_client.post("/command", json={"secret": "topsecret", "command": "unkill"})
    assert r.status_code == 200
    assert r.json()["kill_switch"] is False
    assert not KILL_SWITCH_FILE.exists()


def test_command_positions(app_client):
    init_db()
    repo.create_position(
        symbol="BTC/USDT", side="long", status="open", mode="paper",
        entry_price=100.0, quantity=0.1, stop_loss=97.5,
        take_profit_1=103.0, take_profit_2=106.0, strategy_name="t",
    )
    r = app_client.post("/command", json={"secret": "topsecret", "command": "positions"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["open_positions"]) == 1
    assert body["open_positions"][0]["symbol"] == "BTC/USDT"


def test_command_unknown(app_client):
    r = app_client.post("/command", json={"secret": "topsecret", "command": "delete-everything"})
    assert r.status_code == 400


# ---------- Heartbeat helper (smoke) ----------

def test_heartbeat_telegram_smoke(monkeypatch):
    # No token configured -> send returns False but no exception.
    from app.alerts.telegram import TelegramNotifier
    tg = TelegramNotifier(token="", chat_id="")
    tg.heartbeat("paper", open_positions=0, daily_pnl_pct=0.0, kill=False)
    tg.startup_checklist(["mode: paper", "symbols: BTC/USDT"])
