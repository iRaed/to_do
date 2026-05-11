"""Risk manager: gatekeeper for every order."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from ..config import KILL_SWITCH_FILE, Settings
from ..storage import repository as repo
from ..strategy.base import Signal
from ..utils.time_utils import utc_now


@dataclass
class RiskDecision:
    approved: bool
    reason: Optional[str] = None
    quantity: float = 0.0
    notional: float = 0.0


class RiskManager:
    def __init__(self, settings: Settings):
        self.s = settings

    def position_size(self, entry_price: float, stop_loss: float) -> float:
        """quantity = (equity * risk_per_trade) / stop_distance"""
        if entry_price <= 0 or stop_loss <= 0 or stop_loss >= entry_price:
            return 0.0
        risk_amount = self.s.ACCOUNT_EQUITY * self.s.RISK_PER_TRADE
        stop_distance = entry_price - stop_loss
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def evaluate(
        self,
        signal: Signal,
        *,
        free_quote_balance: Optional[float] = None,
        min_exchange_notional: Optional[float] = None,
        slippage_pct: Optional[float] = None,
    ) -> RiskDecision:
        s = self.s

        # 10. kill switch file
        if KILL_SWITCH_FILE.exists():
            return RiskDecision(False, "kill_switch_active")

        # 1. configured risk above hard cap
        if s.RISK_PER_TRADE > s.MAX_RISK_PER_TRADE:
            return RiskDecision(False, "risk_per_trade_exceeds_max")

        # 11. duplicate signal within 5 minutes
        if repo.recent_signal_exists(signal.symbol, minutes=5):
            return RiskDecision(False, "duplicate_signal_5min")

        # 3. existing open position for same symbol
        if repo.open_position_for_symbol(signal.symbol) is not None:
            return RiskDecision(False, "symbol_already_open")

        # 2. max open positions
        if len(repo.get_open_positions()) >= s.MAX_OPEN_POSITIONS:
            return RiskDecision(False, "max_open_positions_reached")

        # 4. daily loss limit
        if repo.daily_pnl_pct(s.ACCOUNT_EQUITY) <= -abs(s.MAX_DAILY_LOSS):
            return RiskDecision(False, "max_daily_loss_reached")

        # 5. consecutive losses
        if repo.consecutive_losses() >= s.MAX_CONSECUTIVE_LOSSES:
            return RiskDecision(False, "max_consecutive_losses_reached")

        # 7. max trades per day
        if repo.trades_today_count() >= s.MAX_TRADES_PER_DAY:
            return RiskDecision(False, "max_trades_per_day_reached")

        # 6. cooldown after a losing trade
        last_loss = repo.last_loss_at()
        if last_loss and (utc_now() - last_loss) < timedelta(minutes=s.COOLDOWN_MINUTES):
            return RiskDecision(False, "cooldown_after_loss")

        # 8. excessive slippage
        sl_pct = slippage_pct if slippage_pct is not None else s.PAPER_SLIPPAGE_PCT
        if sl_pct > 0.01:  # >1% slippage rejected
            return RiskDecision(False, "slippage_too_high")

        # Position size
        qty = self.position_size(signal.price, signal.stop_loss)
        if qty <= 0:
            return RiskDecision(False, "invalid_position_size")
        notional = qty * signal.price

        # 9. min notional
        min_notional = max(s.MIN_NOTIONAL_USDT, min_exchange_notional or 0.0)
        if notional < min_notional:
            return RiskDecision(False, f"notional_below_min({min_notional})")

        # Available balance check
        if free_quote_balance is not None and notional > free_quote_balance:
            return RiskDecision(False, "insufficient_balance")

        # Max risk cap (defence in depth)
        risk_amount = qty * (signal.price - signal.stop_loss)
        if risk_amount > s.ACCOUNT_EQUITY * s.MAX_RISK_PER_TRADE:
            return RiskDecision(False, "risk_amount_exceeds_max")

        return RiskDecision(approved=True, quantity=qty, notional=notional)
