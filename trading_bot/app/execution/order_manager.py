"""Order manager: owns position state transitions and exit logic."""
from __future__ import annotations

from typing import Optional, Protocol

from ..alerts.telegram import TelegramNotifier
from ..config import Settings
from ..storage import repository as repo
from ..storage.models import Position
from ..strategy.base import Signal
from ..utils.logger import get_logger, log_event


logger = get_logger(__name__)


class BrokerProto(Protocol):
    mode: str
    def open_long(self, signal: Signal, quantity: float): ...
    def close_long(self, position_id: int, trade_id: int, symbol: str, quantity: float, price: float, reason: str): ...


class OrderManager:
    def __init__(self, settings: Settings, broker, telegram: Optional[TelegramNotifier] = None):
        self.s = settings
        self.broker = broker
        self.tg = telegram

    # ---------- entries ----------

    def submit_entry(self, signal: Signal, quantity: float) -> bool:
        # Prevent duplicate entries: same symbol already open
        if repo.open_position_for_symbol(signal.symbol):
            log_event(logger, "warning", "duplicate_entry_blocked", symbol=signal.symbol)
            return False

        if self.broker.mode == "paper":
            fill = self.broker.open_long(signal, quantity)
        else:
            fill = self.broker.open_long(signal, quantity)

        if fill is None:
            return False

        if self.tg:
            risk = (signal.price - signal.stop_loss) * quantity / max(self.s.ACCOUNT_EQUITY, 1e-9)
            self.tg.trade_opened(
                self.broker.mode,
                signal.symbol,
                fill.fill_price,
                fill.quantity,
                signal.stop_loss,
                signal.take_profit_1,
                signal.take_profit_2,
                risk,
            )
        return True

    # ---------- exits ----------

    def _close(self, pos: Position, price: float, reason: str) -> None:
        if self.broker.mode == "paper":
            pnl = self.broker.close_long(pos.id, pos.trade_id, pos.symbol, pos.quantity, price, reason)
        else:
            pnl = self.broker.close_long(pos.id, pos.trade_id, pos.symbol, pos.quantity, reason)
        if pnl is None:
            return
        pnl_pct = pnl / max(pos.entry_price * pos.quantity, 1e-9)
        if self.tg:
            self.tg.exit_event(reason.upper(), pos.symbol, price, pnl, pnl_pct)

    def manage_position(self, pos: Position, last_close: float, ema20: float) -> None:
        """Evaluate exits for an open position given the latest candle close."""
        # 7. kill switch close-positions toggle
        if self.s.kill_switch_active and self.s.KILL_SWITCH_CLOSE_POSITIONS:
            self._close(pos, last_close, "kill_switch_close")
            return

        # 1. stop loss
        if last_close <= pos.stop_loss:
            self._close(pos, last_close, "stop_loss")
            return

        # 3. TP2 (full close)
        if last_close >= pos.take_profit_2:
            self._close(pos, last_close, "take_profit_2")
            return

        # 2 + 4. TP1: move SL to break-even, activate trailing stop
        if not pos.tp1_hit and last_close >= pos.take_profit_1:
            new_sl = max(pos.stop_loss, pos.entry_price)
            trailing = last_close * (1.0 - self.s.TRAILING_STOP_PCT)
            repo.update_position(pos.id, tp1_hit=1, stop_loss=new_sl, trailing_stop=trailing)
            log_event(
                logger,
                "info",
                "tp1_hit",
                symbol=pos.symbol,
                new_sl=new_sl,
                trailing=trailing,
            )
            if self.tg:
                self.tg.exit_event("TP1_HIT", pos.symbol, last_close, 0.0, 0.0)
            return

        # 5. trailing stop update / trigger after TP1
        if pos.tp1_hit:
            new_trailing = last_close * (1.0 - self.s.TRAILING_STOP_PCT)
            if pos.trailing_stop is None or new_trailing > pos.trailing_stop:
                repo.update_position(pos.id, trailing_stop=new_trailing)
            if pos.trailing_stop and last_close <= pos.trailing_stop:
                self._close(pos, last_close, "trailing_stop")
                return

        # 6. exit if close < EMA20
        if last_close < ema20:
            self._close(pos, last_close, "below_ema20")
            return
