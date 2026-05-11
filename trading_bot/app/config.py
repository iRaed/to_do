"""Strongly typed configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KILL_SWITCH_FILE = PROJECT_ROOT / "KILL_SWITCH"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Mode / safety
    MODE: Literal["paper", "live"] = "paper"
    LIVE_TRADING: bool = False

    # Exchange
    EXCHANGE: str = "binance"
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_TESTNET: bool = True

    # Markets
    SYMBOLS: List[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    TIMEFRAME: Literal["5m", "15m", "1h"] = "5m"

    # Account / risk
    ACCOUNT_EQUITY: float = 1000.0
    RISK_PER_TRADE: float = 0.03
    MAX_RISK_PER_TRADE: float = 0.05
    MAX_OPEN_POSITIONS: int = 3
    MAX_DAILY_LOSS: float = 0.10
    MAX_CONSECUTIVE_LOSSES: int = 4
    MAX_TRADES_PER_DAY: int = 10

    # Strategy exits
    STOP_LOSS_PCT: float = 0.025
    TP1_PCT: float = 0.03
    TP2_PCT: float = 0.06
    TRAILING_STOP_PCT: float = 0.015
    COOLDOWN_MINUTES: int = 30

    # Strategy entry
    VOLUME_MULTIPLIER: float = 1.5
    BREAKOUT_LOOKBACK: int = 20

    # Execution costs
    PAPER_SLIPPAGE_PCT: float = 0.001
    MIN_NOTIONAL_USDT: float = 10.0
    TAKER_FEE_PCT: float = 0.001

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Webhooks
    TRADINGVIEW_WEBHOOK_SECRET: str = ""

    # Kill switch
    KILL_SWITCH_CLOSE_POSITIONS: bool = False

    # Loop
    LOOP_INTERVAL_SECONDS: int = 60

    # Storage / logs
    DB_PATH: str = "./data/trading_bot.db"
    LOG_LEVEL: str = "INFO"

    @field_validator("SYMBOLS", mode="before")
    @classmethod
    def _split_symbols(cls, v):
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        return v

    @field_validator("STOP_LOSS_PCT")
    @classmethod
    def _validate_sl(cls, v: float) -> float:
        if not (0.005 <= v <= 0.10):
            raise ValueError("STOP_LOSS_PCT must be between 0.5% and 10%")
        return v

    @property
    def is_live(self) -> bool:
        """Real money trading is enabled only when both flags align."""
        return self.MODE == "live" and self.LIVE_TRADING is True

    @property
    def kill_switch_active(self) -> bool:
        return KILL_SWITCH_FILE.exists()

    def safe_dump(self) -> dict:
        """Return config dict with secrets redacted, safe for logs."""
        d = self.model_dump()
        for secret_key in (
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "TELEGRAM_BOT_TOKEN",
            "TRADINGVIEW_WEBHOOK_SECRET",
        ):
            if d.get(secret_key):
                d[secret_key] = "***REDACTED***"
        return d


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = Settings()
    return _settings
