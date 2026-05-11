"""Time helpers (UTC-first)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def utc_today_start() -> datetime:
    now = utc_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


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
