"""FastAPI endpoints.

- POST /webhook/tradingview  — TradingView entry signal webhook
- POST /command              — emergency command bus (status / kill / positions)
  Body: {"secret": "...", "command": "status|kill|positions"}
- GET  /health
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from ..alerts.telegram import build_telegram_from_settings
from ..config import KILL_SWITCH_FILE, get_settings
from ..execution.order_manager import OrderManager
from ..execution.paper_broker import PaperBroker
from ..risk.risk_manager import RiskManager
from ..storage import repository as repo
from ..storage.db import init_db
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


class CommandPayload(BaseModel):
    secret: str = Field(..., min_length=1)
    command: str


def _safe_payload(p: TVPayload) -> dict:
    return {"symbol": p.symbol, "side": p.side, "strategy": p.strategy, "price": p.price, "timeframe": p.timeframe}


def create_app() -> FastAPI:
    app = FastAPI(title="Crypto Trading Bot Webhook", version="0.1.0")
    settings = get_settings()
    init_db()
    tg = build_telegram_from_settings()
    risk = RiskManager(settings)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "mode": settings.MODE,
            "live": settings.is_live,
            "kill_switch": settings.kill_switch_active,
            "open_positions": len(repo.get_open_positions()),
        }

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
            symbol=payload.symbol, side="buy", price=payload.price,
            stop_loss=payload.price * (1.0 - settings.STOP_LOSS_PCT),
            take_profit_1=payload.price * (1.0 + settings.TP1_PCT),
            take_profit_2=payload.price * (1.0 + settings.TP2_PCT),
            strategy_name=payload.strategy or "TV_WEBHOOK",
            raw=_safe_payload(payload),
        )

        decision = risk.evaluate(signal)
        repo.save_signal(
            symbol=signal.symbol, side=signal.side, strategy_name=signal.strategy_name,
            price=signal.price, raw=_safe_payload(payload),
            accepted=decision.approved, rejection_reason=decision.reason,
        )

        if not decision.approved:
            tg.signal_rejected(signal.symbol, decision.reason or "rejected")
            return {"accepted": False, "reason": decision.reason}

        if settings.is_live:
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

    # ---- Emergency command endpoint ----

    @app.post("/command")
    async def command(payload: CommandPayload):
        if not settings.COMMAND_SECRET:
            raise HTTPException(status_code=503, detail="command_secret_not_configured")
        if payload.secret != settings.COMMAND_SECRET:
            log_event(logger, "warning", "command_invalid_secret", command=payload.command)
            raise HTTPException(status_code=401, detail="invalid_secret")

        cmd = payload.command.strip().lower().lstrip("/")
        log_event(logger, "info", "command_received", command=cmd)

        if cmd == "status":
            return {
                "mode": settings.MODE,
                "live": settings.is_live,
                "kill_switch": settings.kill_switch_active,
                "symbols": settings.SYMBOLS,
                "timeframe": settings.TIMEFRAME,
                "open_positions": len(repo.get_open_positions()),
                "trades_today": repo.trades_today_count(),
                "daily_pnl_pct": repo.daily_pnl_pct(settings.ACCOUNT_EQUITY),
                "daily_notional_usdt": repo.daily_traded_notional(),
                "consecutive_losses": repo.consecutive_losses(),
            }
        if cmd == "kill":
            KILL_SWITCH_FILE.write_text("kill")
            repo.log_bot_event("kill_switch_created", "kill switch via /command", severity="warning")
            tg.kill_switch()
            return {"kill_switch": True}
        if cmd == "unkill":
            if KILL_SWITCH_FILE.exists():
                KILL_SWITCH_FILE.unlink()
                repo.log_bot_event("kill_switch_removed", "kill switch removed via /command")
            return {"kill_switch": False}
        if cmd == "positions":
            positions = repo.get_open_positions()
            return {
                "open_positions": [
                    {
                        "id": p.id, "symbol": p.symbol, "side": p.side, "mode": p.mode,
                        "entry": p.entry_price, "qty": p.quantity,
                        "sl": p.stop_loss, "tp1": p.take_profit_1, "tp2": p.take_profit_2,
                        "tp1_hit": bool(p.tp1_hit), "trailing": p.trailing_stop,
                    }
                    for p in positions
                ]
            }
        raise HTTPException(status_code=400, detail="unknown_command")

    return app


app = create_app()
