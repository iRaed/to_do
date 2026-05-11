"""Time helpers. We use *naive UTC* everywhere so SQLite DateTime columns
compare cleanly. The whole app is UTC; nothing else is supported."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


def utc_now() -> datetime:
    """Naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_today_start() -> datetime:
    n = utc_now()
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def timeframe_to_minutes(tf: str) -> int:
    tf = tf.lower().strip()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 60 * 24
    raise ValueError(f"Unsupported timeframe: {tf}")


def candles_since(days: int, tf: str) -> int:
    return int(days * 24 * 60 / timeframe_to_minutes(tf))


def minutes_ago(minutes: int) -> datetime:
    return utc_now() - timedelta(minutes=minutes)


def seconds_since(then: datetime) -> float:
    return (utc_now() - then).total_seconds()
