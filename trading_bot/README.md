# Personal Crypto Trading Bot (v1, spot only)

> **EXPERIMENTAL SOFTWARE. HIGH RISK. YOU CAN LOSE ALL YOUR MONEY.**
>
> This is a personal, experimental crypto trading bot. It is **not** financial advice,
> not a guaranteed strategy, and not production-grade for managing real capital.
> Cryptocurrency markets are extremely volatile. Bugs, misconfigurations,
> exchange outages, or strategy underperformance **can and will lose money**.
>
> The bot defaults to **paper trading**. Real orders are only sent when both
> `MODE=live` and `LIVE_TRADING=true` are set in `.env`. Even then, start on the
> Binance **spot testnet** with `BINANCE_TESTNET=true` until you are confident.

---

## What this bot does

A personal automated crypto trading bot that:

- Trades **spot** crypto on **Binance** via [CCXT](https://github.com/ccxt/ccxt) (architecture supports other exchanges later).
- Implements a **MomentumBreakoutStrategy** (long-only) with EMA/RSI/ATR/volume filters and a breakout trigger.
- Supports **paper trading**, **live trading** (gated by env), and **backtesting** against historical OHLCV.
- Logs **signals, trades, orders, positions, daily stats, and bot events** to **SQLite**.
- Sends optional **Telegram** alerts.
- Exposes an optional **TradingView FastAPI webhook**.
- Enforces strict **risk controls**, a **kill switch**, and refuses to submit duplicate/unsafe orders.

> v1 is **spot only**. Futures/leverage are **not** implemented and not coming until safety/observability work matures.

---

## Project layout

```
trading_bot/
  app/
    config.py
    main.py             # CLI entrypoint (typer)
    exchange/           # base + binance_ccxt adapter
    strategy/           # indicators + MomentumBreakoutStrategy
    risk/               # RiskManager
    execution/          # paper_broker, live_broker, order_manager
    storage/            # SQLAlchemy models + repository
    alerts/             # Telegram
    backtesting/        # backtester + metrics
    webhooks/           # FastAPI TradingView endpoint
    utils/              # logger, time helpers
  tests/                # pytest
  .env.example
  requirements.txt
  Dockerfile
  docker-compose.yml
```

---

## Setup

Requires **Python 3.11+**.

```bash
cd trading_bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env  (DO NOT commit .env)
```

### Create your `.env`

The full reference is in `.env.example`. Key fields:

```ini
MODE=paper                    # paper | live
LIVE_TRADING=false            # Hard gate. Must be literal "true" for real orders.

EXCHANGE=binance
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_TESTNET=true          # Use Binance spot testnet while you build trust.

SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT
TIMEFRAME=5m                  # 5m | 15m | 1h

ACCOUNT_EQUITY=1000
RISK_PER_TRADE=0.03
MAX_RISK_PER_TRADE=0.05
...
```

Never commit `.env` or share API keys.

---

## Run paper trading

```bash
python -m app.main run
```

Verify config first:

```bash
python -m app.main check-config
python -m app.main status
```

A single cycle (useful for cron) is `python -m app.main run --once`.

## Run a backtest

```bash
python -m app.main backtest --symbol BTC/USDT --timeframe 5m --days 90
```

Outputs:

- JSON report: `data/backtests/backtest_<SYMBOL>_<TF>.json`
- Trade CSV: `data/backtests/backtest_<SYMBOL>_<TF>_trades.csv`

Metrics include total return, win rate, max drawdown, profit factor, average win/loss, largest win/loss, consecutive wins/losses, exposure time, total trades.

## CLI cheat sheet

| Command | Description |
|---|---|
| `python -m app.main run` | Trading loop |
| `python -m app.main backtest --symbol BTC/USDT --timeframe 5m --days 90` | Backtest |
| `python -m app.main status` | Bot status summary |
| `python -m app.main positions` | Open positions |
| `python -m app.main trades --limit 20` | Recent trades |
| `python -m app.main kill` | Create kill switch |
| `python -m app.main unkill` | Remove kill switch |
| `python -m app.main check-config` | Print effective config (secrets redacted) |
| `python -m app.main webhook` | Run FastAPI webhook server |

---

## Telegram alerts

1. Create a bot with [@BotFather](https://t.me/BotFather), grab the token.
2. Start a chat with the bot, then get your chat id (e.g. via `getUpdates` API).
3. Set in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```
The bot sends concise alerts for: bot start/stop, signals, rejections, trade opens, SL/TP/trailing/exit hits, daily loss limit, max consecutive losses, kill switch, exchange errors. Tokens and secrets are never included.

---

## Kill switch

A file named `KILL_SWITCH` in the project root halts new entries instantly.

```bash
python -m app.main kill     # create the file
python -m app.main unkill   # remove it
```

When the file exists:

- All risk checks reject new entries (`reason=kill_switch_active`).
- A Telegram alert is sent on the next cycle.
- A `bot_events` row is recorded.
- If `KILL_SWITCH_CLOSE_POSITIONS=true`, the order manager closes open positions on the next cycle.

You can also create the file manually: `touch trading_bot/KILL_SWITCH`.

---

## Switching to live mode

> Real funds are at stake. Read this carefully.

1. Backtest the strategy on the timeframe and symbols you care about, with realistic slippage and fees.
2. Paper trade for **at least a week** through varied market regimes.
3. Generate Binance API keys with **spot trading** scope only (no withdrawals).
4. Start on the **testnet**: `BINANCE_TESTNET=true`, real keys for the testnet.
5. Confirm: `python -m app.main check-config`.
6. Move to mainnet by setting `BINANCE_TESTNET=false` **and** keeping risk small.
7. Flip both flags:
   ```ini
   MODE=live
   LIVE_TRADING=true
   ```
8. Run with very low `ACCOUNT_EQUITY` initially. Monitor obsessively. Be ready to kill.

The `LiveBroker` validates connectivity, allowed symbols, balance, notional, and risk-manager approval before every order. It uses **market orders only** in v1 and **never** blindly retries an order whose state is unknown.

---

## Strategy: MomentumBreakoutStrategy

Long-only, single-direction breakout filter:

**Entry conditions (all must hold):**
1. `close > EMA20`
2. `close > EMA50`
3. `EMA20 > EMA50`
4. `55 <= RSI(14) <= 75`
5. `volume > VOLUME_MULTIPLIER * avg(volume, last 20 candles)`
6. `close > rolling highest high of previous BREAKOUT_LOOKBACK candles`
7. If symbol is `ETH/USDT` or `SOL/USDT`, **`BTC/USDT` close must be above its EMA50**.

**Exits:**
- Stop loss at `STOP_LOSS_PCT` below entry (default 2.5%).
- TP1 at +`TP1_PCT` (3%): SL is raised to break-even, trailing stop activates.
- TP2 at +`TP2_PCT` (6%): full close.
- Trailing stop at `TRAILING_STOP_PCT` (1.5%) after TP1.
- Exit if close drops below EMA20.
- Exit if kill switch is active and `KILL_SWITCH_CLOSE_POSITIONS=true`.

**Position sizing:**
```
risk_amount  = ACCOUNT_EQUITY * RISK_PER_TRADE
stop_dist    = entry - stop_loss
quantity     = risk_amount / stop_dist
```
The amount is then clamped by available balance, MIN_NOTIONAL, and `MAX_RISK_PER_TRADE`.

---

## Risk settings

| Variable | Purpose |
|---|---|
| `RISK_PER_TRADE` | Fraction of equity risked per trade (3% default). |
| `MAX_RISK_PER_TRADE` | Hard cap. If configured risk exceeds this, all entries are rejected. |
| `MAX_OPEN_POSITIONS` | Concurrent open positions cap. |
| `MAX_DAILY_LOSS` | Stops new entries when realised loss today exceeds this fraction of equity. |
| `MAX_CONSECUTIVE_LOSSES` | Stops new entries after N losses in a row. |
| `MAX_TRADES_PER_DAY` | Hard cap on number of trades per UTC day. |
| `COOLDOWN_MINUTES` | Cooldown after a losing trade before another entry is allowed. |
| `STOP_LOSS_PCT`, `TP1_PCT`, `TP2_PCT`, `TRAILING_STOP_PCT` | Exit parameters. |
| `MIN_NOTIONAL_USDT` | Hard floor for trade notional (also enforced via exchange info). |
| `PAPER_SLIPPAGE_PCT` | Slippage applied to paper fills. Trades rejected if > 1%. |

Risk manager also rejects:

- Trades when **kill switch** is active.
- Duplicate signals for the same symbol within 5 minutes.
- Symbols that already have an open position.
- Trades that would breach available balance or exchange minimums.

---

## TradingView webhook

Start the FastAPI server:

```bash
python -m app.main webhook --host 0.0.0.0 --port 8000
```

Configure TradingView to POST JSON to `http://<host>:8000/webhook/tradingview`:

```json
{
  "secret": "matches TRADINGVIEW_WEBHOOK_SECRET",
  "symbol": "BTC/USDT",
  "side": "buy",
  "strategy": "TV_BREAKOUT",
  "price": 65000,
  "timeframe": "5m"
}
```

The endpoint validates the secret, allowed symbols, side (buy only in v1), and 5-minute dedup. Accepted webhooks pass through the same `RiskManager` and broker as the loop.

---

## Docker

```bash
cd trading_bot
docker compose up --build -d        # bot + webhook
docker compose logs -f bot
```

`./data` and `./logs` are mounted into the container. `.env` is mounted via `env_file`; it never enters the image.

---

## Tests

```bash
cd trading_bot
python -m pytest -q
```

Tests cover indicators, strategy entry/rejection, risk-manager rules, kill switch, and a backtester smoke run.

---

## Common errors

| Symptom | Cause / fix |
|---|---|
| `LiveTradingDisabled: LIVE_TRADING is not enabled` | Set both `MODE=live` and `LIVE_TRADING=true`. By design. |
| `notional_below_min` | Increase `ACCOUNT_EQUITY` or `RISK_PER_TRADE`, or lower stop distance. |
| `risk_per_trade_exceeds_max` | Lower `RISK_PER_TRADE` or raise `MAX_RISK_PER_TRADE` (carefully). |
| `kill_switch_active` | Remove `KILL_SWITCH` file or run `python -m app.main unkill`. |
| Sandbox `set_sandbox_mode` warning | Some Binance endpoints don't support sandbox. Use real testnet keys with `BINANCE_TESTNET=true`. |
| `Insufficient balance` on live | Free USDT below required notional. Top up or reduce position size. |
| Empty backtest | Symbol/timeframe combination has too few candles, or exchange returned nothing. Increase `--days`. |

---

## Roadmap (future, not in v1)

- Limit orders, OCO orders, stop-market orders on exchange-side.
- Additional strategies (mean reversion, EMA pullback, funding-rate-aware).
- Portfolio-level risk (correlated symbol exposure cap).
- Real-time websocket data feed.
- Web dashboard for live monitoring.
- Multi-exchange routing.
- Optional **futures** support behind a separate hard gate, with isolated margin only.

---

## License

MIT (see repository root LICENSE).
