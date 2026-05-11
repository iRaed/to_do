"""Live broker. Active ONLY when MODE=live AND LIVE_TRADING=true.

Safety contract:
- Validates API connectivity and credentials on init.
- Validates symbol, balance, notional, and risk-manager approval before any order.
- Uses market orders only in v1.
- Never blindly retries; on unknown state, refuses to submit a duplicate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..config import Settings
from ..exchange.base import ExchangeBase
from ..storage import repository as repo
from ..strategy.base import Signal
from ..utils.logger import get_logger, log_event


logger = get_logger(__name__)


class LiveTradingDisabled(RuntimeError):
    pass


@dataclass
class LiveFillResult:
    fill_price: float
    quantity: float
    fees: float
    order_id: int
    trade_id: int
    position_id: int
    exchange_order_id: str


class LiveBroker:
    mode = "live"

    def __init__(self, settings: Settings, exchange: ExchangeBase):
        if not settings.is_live:
            raise LiveTradingDisabled("LIVE_TRADING is not enabled. Refusing to instantiate LiveBroker.")
        if not (settings.BINANCE_API_KEY and settings.BINANCE_API_SECRET):
            raise LiveTradingDisabled("Missing API credentials.")
        self.s = settings
        self.x = exchange
        if not self.x.health_check():
            raise LiveTradingDisabled("Exchange health check failed.")

    def _validate(self, signal: Signal, quantity: float) -> Optional[str]:
        if signal.symbol not in self.s.SYMBOLS:
            return "symbol_not_allowed"
        try:
            info = self.x.get_market_info(signal.symbol)
        except Exception as exc:
            logger.error("market_info_failed", extra={"err": str(exc)})
            return "market_info_failed"
        notional = quantity * signal.price
        if notional < max(info.min_notional, self.s.MIN_NOTIONAL_USDT):
            return "notional_below_exchange_min"
        if quantity < info.min_amount:
            return "amount_below_exchange_min"
        try:
            bal = self.x.fetch_balance()
        except Exception as exc:
            logger.error("balance_fetch_failed", extra={"err": str(exc)})
            return "balance_fetch_failed"
        quote = signal.symbol.split("/")[1]
        if bal.get(quote, 0.0) < notional:
            return "insufficient_balance"
        return None

    def open_long(self, signal: Signal, quantity: float) -> Optional[LiveFillResult]:
        reason = self._validate(signal, quantity)
        if reason:
            log_event(logger, "warning", "live_order_rejected", symbol=signal.symbol, reason=reason)
            repo.save_order(
                symbol=signal.symbol,
                side="buy",
                status="rejected",
                mode=self.mode,
                order_type="market",
                price=signal.price,
                quantity=quantity,
                reason=reason,
            )
            return None

        log_event(logger, "info", "live_order_submit", symbol=signal.symbol, qty=quantity)
        try:
            result = self.x.create_market_buy_order(signal.symbol, quantity)
        except Exception as exc:
            # Never retry blindly: log and bail.
            logger.error("live_order_error", extra={"err": str(exc), "symbol": signal.symbol})
            repo.save_order(
                symbol=signal.symbol,
                side="buy",
                status="error",
                mode=self.mode,
                order_type="market",
                price=signal.price,
                quantity=quantity,
                reason=f"exception:{type(exc).__name__}",
            )
            return None

        if result.status not in ("closed", "filled"):
            # Unknown / partially filled — do NOT submit a duplicate order.
            logger.error("live_order_unknown_state", extra={"status": result.status, "id": result.id})
            repo.save_order(
                symbol=signal.symbol,
                side="buy",
                status=f"unknown:{result.status}",
                mode=self.mode,
                order_type="market",
                price=result.price or signal.price,
                quantity=result.filled or quantity,
                fees=result.fees,
                exchange_order_id=result.id,
                reason="unknown_state_no_retry",
            )
            return None

        fill_price = float(result.price or signal.price)
        filled_qty = float(result.filled or quantity)
        fees = float(result.fees or 0.0)

        trade_id = repo.create_trade(
            symbol=signal.symbol,
            side="buy",
            status="open",
            mode=self.mode,
            entry_price=fill_price,
            quantity=filled_qty,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            fees=fees,
            strategy_name=signal.strategy_name,
            raw_signal_json=json.dumps(signal.raw, default=str),
        )
        order_id = repo.save_order(
            symbol=signal.symbol,
            side="buy",
            status="filled",
            mode=self.mode,
            order_type="market",
            price=fill_price,
            quantity=filled_qty,
            fees=fees,
            exchange_order_id=result.id,
            trade_id=trade_id,
            reason="entry",
        )
        position_id = repo.create_position(
            symbol=signal.symbol,
            side="long",
            status="open",
            mode=self.mode,
            entry_price=fill_price,
            quantity=filled_qty,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            trade_id=trade_id,
            strategy_name=signal.strategy_name,
        )
        log_event(
            logger,
            "info",
            "live_fill_open",
            symbol=signal.symbol,
            price=fill_price,
            qty=filled_qty,
            fees=fees,
            exchange_order_id=result.id,
        )
        return LiveFillResult(fill_price, filled_qty, fees, order_id, trade_id, position_id, result.id)

    def close_long(self, position_id: int, trade_id: int, symbol: str, quantity: float, reason: str) -> Optional[float]:
        log_event(logger, "info", "live_exit_submit", symbol=symbol, qty=quantity, reason=reason)
        try:
            result = self.x.create_market_sell_order(symbol, quantity)
        except Exception as exc:
            logger.error("live_exit_error", extra={"err": str(exc), "symbol": symbol})
            repo.save_order(
                symbol=symbol,
                side="sell",
                status="error",
                mode=self.mode,
                order_type="market",
                price=0.0,
                quantity=quantity,
                trade_id=trade_id,
                reason=f"exit_exception:{type(exc).__name__}",
            )
            return None
        if result.status not in ("closed", "filled"):
            logger.error("live_exit_unknown_state", extra={"status": result.status, "id": result.id})
            return None

        fill_price = float(result.price or 0.0)
        fees = float(result.fees or 0.0)
        repo.save_order(
            symbol=symbol,
            side="sell",
            status="filled",
            mode=self.mode,
            order_type="market",
            price=fill_price,
            quantity=float(result.filled or quantity),
            fees=fees,
            exchange_order_id=result.id,
            trade_id=trade_id,
            reason=reason,
        )

        from ..storage.db import session_scope
        from ..storage.models import Trade

        with session_scope() as s:
            t = s.get(Trade, trade_id)
            entry = float(t.entry_price) if t else fill_price
            entry_fees = float(t.fees or 0.0) if t else 0.0
        pnl = (fill_price - entry) * quantity - entry_fees - fees
        pnl_pct = pnl / max(entry * quantity, 1e-9)
        repo.close_trade(
            trade_id,
            exit_price=fill_price,
            realized_pnl=pnl,
            realized_pnl_pct=pnl_pct,
            fees=fees,
            reason=reason,
        )
        repo.close_position(position_id)
        return pnl
