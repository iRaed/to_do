"""Telegram alerts. Silently noop if credentials are missing."""
from __future__ import annotations

from typing import Any, Dict, List

import httpx

from ..config import get_settings
from ..utils.logger import get_logger


logger = get_logger(__name__)


class TelegramNotifier:
    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token) and bool(self.chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.post(url, json=payload)
                if r.status_code >= 400:
                    logger.warning("telegram_send_failed", extra={"status": r.status_code})
                    return False
                return True
        except Exception as exc:
            logger.warning("telegram_exception", extra={"err": str(exc)})
            return False

    # ---- High level helpers ----

    def bot_started(self, mode: str, symbols: List[str]) -> None:
        self.send(f"*Bot started* mode={mode} symbols={','.join(symbols)}")

    def bot_stopped(self, reason: str = "manual") -> None:
        self.send(f"*Bot stopped* reason={reason}")

    def startup_checklist(self, lines: List[str]) -> None:
        body = "\n".join(f"• {l}" for l in lines)
        self.send(f"*Startup checklist*\n{body}")

    def heartbeat(self, mode: str, open_positions: int, daily_pnl_pct: float, kill: bool) -> None:
        ks = " | KILL_SWITCH" if kill else ""
        self.send(
            f"*Heartbeat* mode={mode} open={open_positions} dailyPnL={daily_pnl_pct:.2%}{ks}"
        )

    def signal_detected(self, sig: Dict[str, Any]) -> None:
        self.send(
            "*Signal* {symbol} {side} @ {price}\nSL: {sl}  TP1: {tp1}  TP2: {tp2}\nStrategy: {strat}".format(
                symbol=sig.get("symbol"), side=sig.get("side"), price=sig.get("price"),
                sl=sig.get("stop_loss"), tp1=sig.get("take_profit_1"), tp2=sig.get("take_profit_2"),
                strat=sig.get("strategy_name"),
            )
        )

    def signal_rejected(self, symbol: str, reason: str) -> None:
        self.send(f"*Signal rejected* {symbol} reason={reason}")

    def trade_opened(self, mode: str, symbol: str, price: float, qty: float,
                     sl: float, tp1: float, tp2: float, risk: float) -> None:
        self.send(
            f"*{mode.upper()} BUY* {symbol}\nPrice: {price}  Qty: {qty}\n"
            f"SL: {sl}  TP1: {tp1}  TP2: {tp2}\nRisk: {risk:.2%}"
        )

    def exit_event(self, event: str, symbol: str, price: float, pnl: float, pnl_pct: float) -> None:
        self.send(f"*{event}* {symbol} @ {price}  PnL: {pnl:.4f} ({pnl_pct:.2%})")

    def kill_switch(self) -> None:
        self.send("*KILL SWITCH ACTIVATED* — new trades blocked")

    def daily_loss_hit(self, pct: float) -> None:
        self.send(f"*Daily loss limit hit* {pct:.2%}")

    def consecutive_losses_hit(self, n: int) -> None:
        self.send(f"*Max consecutive losses hit* count={n}")

    def exchange_error(self, message: str) -> None:
        self.send(f"*Exchange error*: {message}")


def build_telegram_from_settings() -> TelegramNotifier:
    s = get_settings()
    return TelegramNotifier(token=s.TELEGRAM_BOT_TOKEN, chat_id=s.TELEGRAM_CHAT_ID)
