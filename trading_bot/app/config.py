"""Strongly typed configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KILL_SWITCH_FILE = PROJECT_ROOT / "KILL_SWITCH"


class LiveConfirmationMissing(RuntimeError):
    """Raised when MODE=live and LIVE_TRADING=true but the human-confirmation flag is missing."""


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
    I_UNDERSTAND_THIS_CAN_LOSE_MONEY: bool = False

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
    MAX_ORDER_NOTIONAL_USDT: float = 250.0
    MAX_DAILY_NOTIONAL_USDT: float = 1000.0

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
    HEARTBEAT_HOURS: int = 6

    # Webhooks
    TRADINGVIEW_WEBHOOK_SECRET: str = ""
    COMMAND_SECRET: str = ""

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
    def live_requested(self) -> bool:
        """True if env asks for live trading, regardless of confirmation."""
        return self.MODE == "live" and self.LIVE_TRADING is True

    @property
    def is_live(self) -> bool:
        """Real money trading is enabled only when ALL three gates align."""
        return self.live_requested and self.I_UNDERSTAND_THIS_CAN_LOSE_MONEY is True

    def assert_live_allowed(self) -> None:
        """Raise if MODE=live + LIVE_TRADING=true but I_UNDERSTAND... is not set."""
        if self.live_requested and not self.I_UNDERSTAND_THIS_CAN_LOSE_MONEY:
            raise LiveConfirmationMissing(
                "Refusing to start: MODE=live and LIVE_TRADING=true but "
                "I_UNDERSTAND_THIS_CAN_LOSE_MONEY is not set to true. "
                "Add I_UNDERSTAND_THIS_CAN_LOSE_MONEY=true to .env to acknowledge "
                "that this bot can lose real money."
            )

    @property
    def kill_switch_active(self) -> bool:
        return KILL_SWITCH_FILE.exists()

    def safe_dump(self) -> dict:
        d = self.model_dump()
        for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "TELEGRAM_BOT_TOKEN",
                  "TRADINGVIEW_WEBHOOK_SECRET", "COMMAND_SECRET"):
            if d.get(k):
                d[k] = "***REDACTED***"
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
