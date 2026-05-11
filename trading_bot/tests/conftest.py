"""Pytest configuration: isolate DB and kill-switch per test."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so `import app.*` works when running pytest from anywhere
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    # Per-test DB
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("MODE", "paper")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ACCOUNT_EQUITY", "1000")
    monkeypatch.setenv("MIN_NOTIONAL_USDT", "10")
    monkeypatch.setenv("PAPER_SLIPPAGE_PCT", "0.001")
    monkeypatch.setenv("RISK_PER_TRADE", "0.03")
    monkeypatch.setenv("MAX_RISK_PER_TRADE", "0.05")

    # Reset cached singletons in config + db
    from app import config as cfg
    cfg._settings = None
    from app.storage import db as db_mod
    db_mod._engine = None
    db_mod._SessionLocal = None

    # Ensure no kill switch file leaks between tests
    ks = ROOT / "KILL_SWITCH"
    if ks.exists():
        ks.unlink()
    yield
    if ks.exists():
        ks.unlink()
