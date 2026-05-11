"""Exchange interface. Add new exchanges by subclassing ExchangeBase."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class OHLCV:
    timestamp: int  # ms
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketInfo:
    symbol: str
    base: str
    quote: str
    min_amount: float
    min_notional: float
    amount_precision: int
    price_precision: int


@dataclass
class OrderResult:
    id: str
    symbol: str
    side: str
    type: str
    status: str
    price: Optional[float]
    quantity: float
    filled: float
    fees: float
    raw: Dict[str, Any]


class ExchangeBase(ABC):
    name: str = "base"

    @abstractmethod
    def health_check(self) -> bool: ...

    @abstractmethod
    def get_market_info(self, symbol: str) -> MarketInfo: ...

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200, since: Optional[int] = None) -> List[OHLCV]: ...

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]: ...

    @abstractmethod
    def fetch_balance(self) -> Dict[str, float]: ...

    @abstractmethod
    def create_market_buy_order(self, symbol: str, quantity: float) -> OrderResult: ...

    @abstractmethod
    def create_market_sell_order(self, symbol: str, quantity: float) -> OrderResult: ...
