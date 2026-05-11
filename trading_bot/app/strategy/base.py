"""Strategy interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class Signal:
    symbol: str
    side: str  # "buy" only in v1
    price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    strategy_name: str
    raw: Dict[str, Any] = field(default_factory=dict)


class StrategyBase(ABC):
    name: str = "base"

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Signal]:
        """Return a Signal or None.

        `df` must have columns: open, high, low, close, volume indexed by timestamp.
        `context` may include cross-market data (e.g. BTC df for ETH/SOL filter).
        """
