# NSE Swing Trading System

A complete end-to-end swing trading system for NSE (National Stock Exchange of India) built in three layers:
**Pine Script** for visual chart analysis → **Python backtester** for strategy validation → **Alert bot** for automated daily screening.

---

## What this does

| Layer | Tool | Purpose |
|---|---|---|
| Visual | TradingView Pine Script | See signals, EMA mesh, SL/TP lines live on any NSE chart |
| Validation | Python backtester | Test the strategy on 10 years of daily data across 185+ stocks |
| Automation | Python alert bot | Scan all stocks every morning, email signals with trade levels |

The bot emails you every weekday at 11 AM with any stocks that fired a signal — entry price, stop loss, take profit, conviction score. You open the chart, confirm with your own TA, and place the trade manually.

---

## Strategy logic

The strategy is a **trend-following swing system** based on three entry types, all requiring a confirmed bull/bear trend first.

### Trend filter — all four must be true
- EMA 21 > EMA 50 (green mesh)
- EMA 50 > EMA 200 (above long-term trend)
- EMA 21 slope rising over 5 bars
- EMA 50 slope rising over 5 bars

### Entry signals (longs)
| Signal | Trigger |
|---|---|
| **PB-L** | Price pulls back to touch EMA 21, closes above it with a bullish candle |
| **PB50-L** | Deeper pullback to EMA 50, closes above with a bullish candle |
| **BO-L** | Price breaks out above the 12-bar swing high with a strong close |

### Quality filters
- ADX ≥ 12 — trend has enough strength
- Volume ≥ 1.1× 20-day average — institutional participation confirmed
- RSI in healthy zone — not overbought at entry
- Candle closes in top 50% of day's range

### Risk management (Walk-Forward Optimised)
- **Stop Loss** — Entry − ATR × 1.5
- **Take Profit** — Entry + ATR × 3.5
- **Risk/Reward** — ~1:2.33 on average
- ATR (Average True Range) is used so volatile stocks get proportionally wider levels

### Conviction score (0–6)
Each of these adds 1 point: bull trend active · ADX confirmed · volume confirmed · RSI in zone · bullish candle · price above weekly EMA 50.

### Fundamental score (0–10)
Piotroski-inspired quality gate: ROE/ROA levels + trend checks (debt falling, margins stable, no dilution). Tiers: HIGH (7–10) / MEDIUM (4–6) / LOW (0–3). Scores are cached for 90 days.

---

## Backtest results (2019–2026, 185 NSE stocks, daily bars)

| Metric | Value |
|---|---|
| Total trades | 2,484 |
| Win rate | 50.5% |
| Avg win / avg loss | +8.16% / −5.44% |
| Profit factor | 1.53 |
| Expectancy per trade | +1.43% |
| Sharpe ratio (ann.) | 3.23 |
| Sortino ratio (ann.) | 13.54 |
| Walk-forward OOS/IS | 99% — no overfitting |
| Monte Carlo profitable | 100% of 10,000 simulations |

**Top performers:** ALKYLAMINE, WIPRO, TECHM, BHARTIARTL, PERSISTENT, BHEL, CANBK

**Excluded from live alerts** (statistically significant negative edge): CIPLA, KOTAKBANK, ACC, SHREECEM, ZEEL

---

## Project structure

```
quant_backtesting/
│
├── config/
│   └── strategy.yaml         # Single source of truth for all strategy parameters
│
├── core/                     # Shared library used by backtester + bot
│   ├── config.py             # Pydantic StrategyConfig — loads strategy.yaml
│   ├── data.py               # Cache abstraction over yfinance
│   ├── logging.py            # Append-only audit CSV logs (runs, signals, fetches)
│   ├── scorecard.py          # Per-stock historical performance lookup
│   ├── fundamental_scorer.py # Piotroski-style 10-pt fundamental quality score
│   ├── patterns.py           # Pivot/S&R/flat-base detection (strictly causal)
│   ├── pattern_scanner.py    # 11+ chart pattern recogniser (Bull Flag, Cup & Handle, etc.)
│   ├── paper_trader.py       # Paper trading simulation
│   ├── universe_builder.py   # Dynamic stock universe construction
│   └── ml/
│       ├── feature_builder.py  # ML feature engineering
│       └── xgb_scorer.py       # XGBoost quality scorer
│
├── bot/                      # Live alert system
│   ├── main.py               # Entry point — run scan + send email
│   ├── config.py             # Gmail credentials loader (.env)
│   ├── universe.py           # Stock watchlist (2,258 NSE stocks from CSV)
│   ├── screener.py           # Fetch data → detect signals across all stocks
│   ├── signal_engine.py      # Signal detection on today's completed bar
│   └── notifier.py           # HTML email builder & SMTP sender
│
├── tests/                    # Pytest test suite
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_data.py
│   ├── test_logging.py
│   └── test_signals.py
│
├── results/                  # Backtest output (auto-created)
│   ├── summary_report.md     # Full metrics after a backtest run
│   ├── trades_*.csv          # Per-stock trade logs
│   └── charts/               # 10+ PNG visualisations
│
├── logs/                     # Audit logs (auto-created)
│   ├── backtest_runs.csv
│   ├── signals.csv
│   └── fetch_log.csv
│
├── main.py                   # Full backtest pipeline orchestrator
├── backtester.py             # Bar-by-bar backtest engine
├── data.py                   # Yahoo Finance downloader + cache (185 NSE stocks)
├── indicators.py             # EMA, RSI, ADX, ATR, Volume, candle patterns
├── analysis.py               # Sharpe, Sortino, drawdown, Monte Carlo stats
├── charts.py                 # Matplotlib/Seaborn chart generation
├── optimization.py           # Walk-forward + grid search optimiser (108 combos)
├── montecarlo.py             # Bootstrap Monte Carlo simulator (10k paths)
├── dashboard.py              # Streamlit interactive dashboard
├── pipeline.py               # Unified Typer CLI (backtest / screen / both / config)
├── test_fundamental.py       # Fundamental scorer tests
│
├── pine_script.pine          # TradingView strategy (3H timeframe)
├── stocks_list.csv           # 2,258 NSE tickers for the screener universe
├── start_dashboard.bat       # Windows launcher for Streamlit dashboard
├── requirements.txt          # All Python dependencies
└── .env.example              # Email credentials template (copy → .env, never commit)
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure email credentials
```bash
# Copy the template
copy .env.example .env

# Edit .env and fill in:
# GMAIL_SENDER       — Gmail address that sends alerts
# GMAIL_APP_PASS     — 16-char App Password (myaccount.google.com/apppasswords)
# ALERT_RECIPIENTS   — comma-separated recipient addresses
```

### 3. Run the backtester
```bash
python main.py
```
Results are saved to `results/` — trade CSVs, charts, and a summary report.

### 4. Run the alert bot

**Single scan (now):**
```bash
python bot/main.py
```

**Dry run (no email):**
```bash
python bot/main.py --dry-run
```

**Test specific tickers:**
```bash
python bot/main.py --tickers WIPRO.NS PERSISTENT.NS --dry-run
```

### 5. Run the Streamlit dashboard
```bash
streamlit run dashboard.py
# or on Windows: double-click start_dashboard.bat
```
The dashboard shows live signals, historical scorecard, chart pattern scanner, and fundamental quality scores.

### 6. Use the unified CLI
```bash
python pipeline.py --help

python pipeline.py backtest    # run full backtest
python pipeline.py screen      # run live screener
python pipeline.py both        # backtest then screen
python pipeline.py config      # show current strategy config
```

---

## Adding more stocks

Open `bot/universe.py` and append tickers to the relevant section:
```python
"ZOMATO.NS", "PAYTM.NS", "DELHIVERY.NS",   # add here
```
Tickers must use Yahoo Finance format with `.NS` suffix.

---

## Running tests

```bash
pytest tests/

# Fundamental scorer specifically
python test_fundamental.py

# Linting (requires ruff in stock conda env)
G:\Anaconda\envs\stock\Scripts\ruff.exe check .
```

---

## Important notes

- **Timeframe mismatch:** The Pine Script is tuned for 3H bars; the backtester uses daily bars (yfinance only provides free intraday data for the last 60 days). Use the bot alert to identify *which* stock to look at, then open the 3H chart on TradingView to time the actual entry.
- **Short selling:** Backtest includes short signals, but NSE short selling requires F&O or margin account. The bot reports short signals but you decide if your account supports it.
- **Not financial advice:** This is a quantitative research and learning project. Always do your own analysis before placing any trade.

---

## Data source

Historical data is fetched from **Yahoo Finance** via `yfinance` using `.NS` suffixed tickers (e.g. `WIPRO.NS`). No NSE subscription or scraping required. Daily OHLCV is cached to `data/raw/`; fundamental data is cached to `data/fundamentals/` for 90 days.

---

## License

MIT — free to use, modify, and share.
