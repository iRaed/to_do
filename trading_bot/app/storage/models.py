"""SQLAlchemy ORM models for persistent state."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase

from ..utils.time_utils import utc_now


class Base(DeclarativeBase):
    pass


class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utc_now, index=True)
    symbol = Column(String, index=True)
    side = Column(String)
    strategy_name = Column(String)
    price = Column(Float)
    raw_signal_json = Column(Text)
    accepted = Column(Integer, default=0)  # 0/1
    rejection_reason = Column(String, nullable=True)


class Trade(Base):
    """A round-trip trade (entry through exit)."""
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utc_now, index=True)
    closed_at = Column(DateTime, nullable=True)
    symbol = Column(String, index=True)
    side = Column(String)
    status = Column(String, default="open")  # open | closed
    mode = Column(String)  # paper | live
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Float)
    stop_loss = Column(Float)
    take_profit_1 = Column(Float)
    take_profit_2 = Column(Float)
    realized_pnl = Column(Float, default=0.0)
    realized_pnl_pct = Column(Float, default=0.0)
    fees = Column(Float, default=0.0)
    reason = Column(String, nullable=True)
    strategy_name = Column(String)
    raw_signal_json = Column(Text, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utc_now, index=True)
    symbol = Column(String, index=True)
    side = Column(String)
    status = Column(String)  # submitted | filled | rejected | error
    mode = Column(String)
    order_type = Column(String, default="market")
    price = Column(Float)
    quantity = Column(Float)
    fees = Column(Float, default=0.0)
    exchange_order_id = Column(String, nullable=True)
    trade_id = Column(Integer, nullable=True, index=True)
    reason = Column(String, nullable=True)


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    opened_at = Column(DateTime, default=utc_now, index=True)
    closed_at = Column(DateTime, nullable=True)
    symbol = Column(String, index=True)
    side = Column(String)
    status = Column(String, default="open")  # open | closed
    mode = Column(String)
    entry_price = Column(Float)
    quantity = Column(Float)
    stop_loss = Column(Float)
    take_profit_1 = Column(Float)
    take_profit_2 = Column(Float)
    trailing_stop = Column(Float, nullable=True)
    tp1_hit = Column(Integer, default=0)
    trade_id = Column(Integer, nullable=True, index=True)
    strategy_name = Column(String)


class DailyStat(Base):
    __tablename__ = "daily_stats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, unique=True, index=True)  # YYYY-MM-DD UTC
    trades_count = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    consecutive_losses = Column(Integer, default=0)
    pnl = Column(Float, default=0.0)
    pnl_pct = Column(Float, default=0.0)


class BotEvent(Base):
    __tablename__ = "bot_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utc_now, index=True)
    event_type = Column(String, index=True)
    severity = Column(String, default="info")
    message = Column(Text)
    data_json = Column(Text, nullable=True)
