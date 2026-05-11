"""Pytest configuration: isolate DB, env, and kill-switch per test."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("MODE", "paper")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("I_UNDERSTAND_THIS_CAN_LOSE_MONEY", "false")
    monkeypatch.setenv("ACCOUNT_EQUITY", "1000")
    monkeypatch.setenv("MIN_NOTIONAL_USDT", "10")
    monkeypatch.setenv("PAPER_SLIPPAGE_PCT", "0.001")
    monkeypatch.setenv("RISK_PER_TRADE", "0.03")
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "0.05")
    # New caps: default high so existing tests are unaffected unless they override.
    monkeypatch.setenv("MAX_ORDER_NOTIONAL_USDT", "100000")
    monkeypatch.setenv("MAX_DAILY_NOTIONAL_USDT", "1000000")
    monkeypatch.setenv("HEARTBEAT_HOURS", "6")
    monkeypatch.setenv("COMMAND_SECRET", "")
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_SECRET", "")

    from app import config as cfg
    cfg._settings = None
    from app.storage import db as db_mod
    db_mod._engine = None
    db_mod._SessionLocal = None

    ks = ROOT / "KILL_SWITCH"
    if ks.exists():
        ks.unlink()
    yield
    if ks.exists():
        ks.unlink()
