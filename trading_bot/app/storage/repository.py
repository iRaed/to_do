"""Repository layer: small typed helpers over SQLAlchemy sessions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

from sqlalchemy import desc, select

from ..utils.time_utils import utc_now, utc_today_start
from .db import session_scope
from .models import BotEvent, DailyStat, Order, Position, Signal, Trade


# ---------- Signals ----------

def save_signal(
    *,
    symbol: str,
    side: str,
    strategy_name: str,
    price: float,
    raw: dict,
    accepted: bool,
    rejection_reason: Optional[str] = None,
) -> int:
    with session_scope() as s:
        sig = Signal(
            symbol=symbol,
            side=side,
            strategy_name=strategy_name,
            price=price,
            raw_signal_json=json.dumps(raw, default=str),
            accepted=1 if accepted else 0,
            rejection_reason=rejection_reason,
        )
        s.add(sig)
        s.commit()
        return sig.id


def recent_signal_exists(symbol: str, minutes: int = 5) -> bool:
    cutoff = utc_now() - timedelta(minutes=minutes)
    with session_scope() as s:
        q = (
            select(Signal)
            .where(Signal.symbol == symbol, Signal.timestamp >= cutoff, Signal.accepted == 1)
            .limit(1)
        )
        return s.execute(q).first() is not None


# ---------- Trades ----------

def create_trade(**fields) -> int:
    with session_scope() as s:
        t = Trade(**fields)
        s.add(t)
        s.commit()
        return t.id


def close_trade(
    trade_id: int,
    *,
    exit_price: float,
    realized_pnl: float,
    realized_pnl_pct: float,
    fees: float,
    reason: str,
) -> None:
    with session_scope() as s:
        t = s.get(Trade, trade_id)
        if not t:
            return
        t.exit_price = exit_price
        t.realized_pnl = realized_pnl
        t.realized_pnl_pct = realized_pnl_pct
        t.fees = (t.fees or 0.0) + fees
        t.reason = reason
        t.status = "closed"
        t.closed_at = utc_now()
        s.commit()


def list_trades(limit: int = 20) -> List[Trade]:
    with session_scope() as s:
        q = select(Trade).order_by(desc(Trade.timestamp)).limit(limit)
        return list(s.execute(q).scalars())


def trades_today_count() -> int:
    start = utc_today_start()
    with session_scope() as s:
        q = select(Trade).where(Trade.timestamp >= start)
        return len(list(s.execute(q).scalars()))


def consecutive_losses() -> int:
    with session_scope() as s:
        q = (
            select(Trade)
            .where(Trade.status == "closed")
            .order_by(desc(Trade.closed_at))
            .limit(20)
        )
        count = 0
        for t in s.execute(q).scalars():
            if (t.realized_pnl or 0.0) < 0:
                count += 1
            else:
                break
        return count


def last_loss_at() -> Optional[datetime]:
    with session_scope() as s:
        q = (
            select(Trade)
            .where(Trade.status == "closed")
            .order_by(desc(Trade.closed_at))
            .limit(1)
        )
        t = s.execute(q).scalars().first()
        if t and (t.realized_pnl or 0.0) < 0:
            return t.closed_at
        return None


def daily_pnl_pct(account_equity: float) -> float:
    start = utc_today_start()
    with session_scope() as s:
        q = select(Trade).where(Trade.closed_at >= start, Trade.status == "closed")
        pnl = sum((t.realized_pnl or 0.0) for t in s.execute(q).scalars())
        if account_equity <= 0:
            return 0.0
        return pnl / account_equity


# ---------- Orders ----------

def save_order(**fields) -> int:
    with session_scope() as s:
        o = Order(**fields)
        s.add(o)
        s.commit()
        return o.id


# ---------- Positions ----------

def create_position(**fields) -> int:
    with session_scope() as s:
        p = Position(**fields)
        s.add(p)
        s.commit()
        return p.id


def update_position(position_id: int, **fields) -> None:
    with session_scope() as s:
        p = s.get(Position, position_id)
        if not p:
            return
        for k, v in fields.items():
            setattr(p, k, v)
        s.commit()


def close_position(position_id: int) -> None:
    with session_scope() as s:
        p = s.get(Position, position_id)
        if not p:
            return
        p.status = "closed"
        p.closed_at = utc_now()
        s.commit()


def get_open_positions(symbol: Optional[str] = None) -> List[Position]:
    with session_scope() as s:
        stmt = select(Position).where(Position.status == "open")
        if symbol:
            stmt = stmt.where(Position.symbol == symbol)
        return list(s.execute(stmt).scalars())


def open_position_for_symbol(symbol: str) -> Optional[Position]:
    positions = get_open_positions(symbol)
    return positions[0] if positions else None


# ---------- Events ----------

def log_bot_event(event_type: str, message: str, severity: str = "info", data: Optional[dict] = None) -> None:
    with session_scope() as s:
        e = BotEvent(
            event_type=event_type,
            severity=severity,
            message=message,
            data_json=json.dumps(data, default=str) if data else None,
        )
        s.add(e)
        s.commit()
