"""Binance spot adapter via CCXT."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import ccxt

from ..config import get_settings
from ..utils.logger import get_logger
from .base import ExchangeBase, MarketInfo, OHLCV, OrderResult


logger = get_logger(__name__)


class BinanceCCXT(ExchangeBase):
    name = "binance"

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = True, sandbox: bool = True):
        params: Dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if api_key and api_secret:
            params["apiKey"] = api_key
            params["secret"] = api_secret
        self._client = ccxt.binance(params)
        if testnet:
            # CCXT exposes sandbox mode for Binance spot testnet
            try:
                self._client.set_sandbox_mode(True)
            except Exception as exc:
                logger.warning("could_not_enable_sandbox", extra={"err": str(exc)})
        self._markets_loaded = False

    def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            self._client.load_markets()
            self._markets_loaded = True

    def health_check(self) -> bool:
        try:
            self._client.fetch_time()
            self._ensure_markets()
            return True
        except Exception as exc:
            logger.error("exchange_health_check_failed", extra={"err": str(exc)})
            return False

    def get_market_info(self, symbol: str) -> MarketInfo:
        self._ensure_markets()
        m = self._client.market(symbol)
        limits = m.get("limits", {}) or {}
        amount_min = (limits.get("amount") or {}).get("min") or 0.0
        cost_min = (limits.get("cost") or {}).get("min") or 0.0
        precision = m.get("precision", {}) or {}
        return MarketInfo(
            symbol=symbol,
            base=m["base"],
            quote=m["quote"],
            min_amount=float(amount_min or 0.0),
            min_notional=float(cost_min or 0.0),
            amount_precision=int(precision.get("amount") or 8),
            price_precision=int(precision.get("price") or 8),
        )

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200, since: Optional[int] = None) -> List[OHLCV]:
        raw = self._client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        return [OHLCV(ts, o, h, l, c, v) for ts, o, h, l, c, v in raw]

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return self._client.fetch_ticker(symbol)

    def fetch_balance(self) -> Dict[str, float]:
        bal = self._client.fetch_balance()
        free = bal.get("free", {}) or {}
        return {k: float(v) for k, v in free.items() if v}

    def _to_result(self, order: Dict[str, Any], symbol: str, side: str) -> OrderResult:
        fee = 0.0
        fees = order.get("fees") or []
        for f in fees:
            try:
                fee += float(f.get("cost") or 0.0)
            except (TypeError, ValueError):
                pass
        return OrderResult(
            id=str(order.get("id") or ""),
            symbol=symbol,
            side=side,
            type=str(order.get("type") or "market"),
            status=str(order.get("status") or "unknown"),
            price=float(order["average"]) if order.get("average") else (float(order["price"]) if order.get("price") else None),
            quantity=float(order.get("amount") or 0.0),
            filled=float(order.get("filled") or 0.0),
            fees=fee,
            raw=order,
        )

    # TODO: support limit orders, OCO, stop-market orders in v2.
    def create_market_buy_order(self, symbol: str, quantity: float) -> OrderResult:
        order = self._client.create_order(symbol, type="market", side="buy", amount=quantity)
        return self._to_result(order, symbol, "buy")

    def create_market_sell_order(self, symbol: str, quantity: float) -> OrderResult:
        order = self._client.create_order(symbol, type="market", side="sell", amount=quantity)
        return self._to_result(order, symbol, "sell")


def build_binance_from_settings() -> BinanceCCXT:
    s = get_settings()
    return BinanceCCXT(
        api_key=s.BINANCE_API_KEY,
        api_secret=s.BINANCE_API_SECRET,
        testnet=s.BINANCE_TESTNET,
    )
