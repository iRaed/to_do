"""FastAPI endpoint for TradingView webhooks.

POST /webhook/tradingview
{
    "secret": "shared-secret",
    "symbol": "BTC/USDT",
    "side": "buy",
    "strategy": "TV_BREAKOUT",
    "price": 65000,
    "timeframe": "5m"
}
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ..alerts.telegram import build_telegram_from_settings
from ..config import get_settings
from ..execution.order_manager import OrderManager
from ..execution.paper_broker import PaperBroker
from ..risk.risk_manager import RiskManager
from ..storage import repository as repo
from ..strategy.base import Signal
from ..utils.logger import get_logger, log_event


logger = get_logger(__name__)


class TVPayload(BaseModel):
    secret: str = Field(..., min_length=1)
    symbol: str
    side: str
    strategy: Optional[str] = "TV_WEBHOOK"
    price: float
    timeframe: Optional[str] = None


def _safe_payload(p: TVPayload) -> dict:
    return {"symbol": p.symbol, "side": p.side, "strategy": p.strategy, "price": p.price, "timeframe": p.timeframe}


def create_app() -> FastAPI:
    app = FastAPI(title="Crypto Trading Bot Webhook", version="0.1.0")
    settings = get_settings()
    tg = build_telegram_from_settings()
    risk = RiskManager(settings)

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.MODE, "live": settings.is_live}

    @app.post("/webhook/tradingview")
    async def tradingview(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_json")

        payload = TVPayload(**body)

        if not settings.TRADINGVIEW_WEBHOOK_SECRET:
            raise HTTPException(status_code=503, detail="webhook_secret_not_configured")
        if payload.secret != settings.TRADINGVIEW_WEBHOOK_SECRET:
            log_event(logger, "warning", "webhook_invalid_secret", symbol=payload.symbol)
            raise HTTPException(status_code=401, detail="invalid_secret")

        log_event(logger, "info", "webhook_received", **_safe_payload(payload))

        if payload.symbol not in settings.SYMBOLS:
            tg.signal_rejected(payload.symbol, "symbol_not_allowed")
            return {"accepted": False, "reason": "symbol_not_allowed"}
        if payload.side.lower() != "buy":
            tg.signal_rejected(payload.symbol, "side_not_buy")
            return {"accepted": False, "reason": "side_not_buy"}
        if repo.recent_signal_exists(payload.symbol, minutes=5):
            tg.signal_rejected(payload.symbol, "duplicate_signal_5min")
            return {"accepted": False, "reason": "duplicate_signal_5min"}

        signal = Signal(
            symbol=payload.symbol,
            side="buy",
            price=payload.price,
            stop_loss=payload.price * (1.0 - settings.STOP_LOSS_PCT),
            take_profit_1=payload.price * (1.0 + settings.TP1_PCT),
            take_profit_2=payload.price * (1.0 + settings.TP2_PCT),
            strategy_name=payload.strategy or "TV_WEBHOOK",
            raw=_safe_payload(payload),
        )

        decision = risk.evaluate(signal)
        repo.save_signal(
            symbol=signal.symbol,
            side=signal.side,
            strategy_name=signal.strategy_name,
            price=signal.price,
            raw=_safe_payload(payload),
            accepted=decision.approved,
            rejection_reason=decision.reason,
        )

        if not decision.approved:
            tg.signal_rejected(signal.symbol, decision.reason or "rejected")
            return {"accepted": False, "reason": decision.reason}

        if settings.is_live:
            # Lazy import to avoid CCXT/exchange instantiation at module load
            from ..exchange.binance_ccxt import build_binance_from_settings
            from ..execution.live_broker import LiveBroker

            exchange = build_binance_from_settings()
            broker = LiveBroker(settings, exchange)
            om = OrderManager(settings, broker, tg)
            ok = om.submit_entry(signal, decision.quantity)
            tg.signal_detected({
                "symbol": signal.symbol, "side": signal.side, "price": signal.price,
                "stop_loss": signal.stop_loss, "take_profit_1": signal.take_profit_1,
                "take_profit_2": signal.take_profit_2, "strategy_name": signal.strategy_name,
            })
            return {"accepted": ok, "mode": "live"}
        else:
            broker = PaperBroker(settings)
            om = OrderManager(settings, broker, tg)
            ok = om.submit_entry(signal, decision.quantity)
            tg.signal_detected({
                "symbol": signal.symbol, "side": signal.side, "price": signal.price,
                "stop_loss": signal.stop_loss, "take_profit_1": signal.take_profit_1,
                "take_profit_2": signal.take_profit_2, "strategy_name": signal.strategy_name,
            })
            return {"accepted": ok, "mode": "paper"}

    return app


app = create_app()
