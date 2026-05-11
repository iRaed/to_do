"""Paper trading broker. Simulates fills with slippage + fees."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..config import Settings
from ..storage import repository as repo
from ..strategy.base import Signal
from ..utils.logger import get_logger, log_event


logger = get_logger(__name__)


@dataclass
class FillResult:
    fill_price: float
    quantity: float
    fees: float
    order_id: int
    trade_id: int
    position_id: int


class PaperBroker:
    mode = "paper"

    def __init__(self, settings: Settings):
        self.s = settings

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = self.s.PAPER_SLIPPAGE_PCT
        return price * (1 + slip) if side == "buy" else price * (1 - slip)

    def open_long(self, signal: Signal, quantity: float) -> Optional[FillResult]:
        fill_price = self._apply_slippage(signal.price, "buy")
        notional = fill_price * quantity
        fees = notional * self.s.TAKER_FEE_PCT

        trade_id = repo.create_trade(
            symbol=signal.symbol,
            side="buy",
            status="open",
            mode=self.mode,
            entry_price=fill_price,
            quantity=quantity,
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
            quantity=quantity,
            fees=fees,
            trade_id=trade_id,
            reason="entry",
        )
        position_id = repo.create_position(
            symbol=signal.symbol,
            side="long",
            status="open",
            mode=self.mode,
            entry_price=fill_price,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            trade_id=trade_id,
            strategy_name=signal.strategy_name,
        )
        log_event(
            logger,
            "info",
            "paper_fill_open",
            symbol=signal.symbol,
            price=fill_price,
            qty=quantity,
            fees=fees,
            trade_id=trade_id,
        )
        return FillResult(fill_price, quantity, fees, order_id, trade_id, position_id)

    def close_long(self, position_id: int, trade_id: int, symbol: str, quantity: float, price: float, reason: str) -> float:
        fill_price = self._apply_slippage(price, "sell")
        notional = fill_price * quantity
        fees = notional * self.s.TAKER_FEE_PCT

        repo.save_order(
            symbol=symbol,
            side="sell",
            status="filled",
            mode=self.mode,
            order_type="market",
            price=fill_price,
            quantity=quantity,
            fees=fees,
            trade_id=trade_id,
            reason=reason,
        )

        # PnL = (exit - entry) * qty - fees (entry fees already booked on trade)
        # Compute using the trade row for entry price.
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
        log_event(
            logger,
            "info",
            "paper_fill_close",
            symbol=symbol,
            price=fill_price,
            qty=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
        )
        return pnl
