# NSE Swing Trading System

A complete end-to-end swing trading system for NSE (National Stock Exchange of India) built in three layers:
**Pine Script** for visual chart analysis → **Python backtester** for strategy validation → **Alert bot** for automated daily screening.

---

## What this does

| Layer | Tool | Purpose |
|---|---|---|
| Visual | TradingView Pine Script | See signals, EMA mesh, SL/TP lines live on any NSE chart |
| Validation | Python backtester | Test the strategy on 10 years of daily data across 869 stocks |
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
| Signal | Trigger | Share of trades |
|---|---|---|
| **PB-L** | Price pulls back to touch EMA 21, closes above it with a bullish candle | 46% |
| **BO-L** | Price breaks out above the 12-bar swing high with a strong close | 74% |
| **BASE-BO** | Breakout from a 15-bar flat base (range < 5%), needs 1.2× the normal volume | 1.5% |
| **PB-S / BO-S** | Short mirrors of the above | 0.3% combined |

Signal priority when several fire on the same bar: PB-L > BASE-BO > BO-L.
The short side produces 84 trades in a decade and loses money — treat it as
inactive. `PB50-L` appears in some encodings but **no entry logic generates it**.

### Quality filters
- ADX ≥ 18 long / ≥ 20 short — trend has enough strength
- Volume ≥ 1.1× 20-day average — institutional participation confirmed
- RSI in healthy zone — not overbought at entry
- Candle closes in top 50% of day's range

### Risk management (Walk-Forward Optimised)
- **Stop Loss** — Entry − ATR × 1.5
- **Take Profit** — Entry + ATR × 3.5
- **Risk/Reward** — ~1:2.33 on average
- ATR (Average True Range) is used so volatile stocks get proportionally wider levels

### Conviction score (0–7)
Each of these adds 1 point: bull trend active · ADX confirmed · volume confirmed · RSI in zone · bullish candle · price above weekly EMA 50 · price near support.

### Fundamental score (0–10)
Piotroski-inspired quality gate: ROE/ROA levels + trend checks (debt falling, margins stable, no dilution). Tiers: HIGH (7–10) / MEDIUM (4–6) / LOW (0–3). Scores are cached for 90 days.

---

## Backtest results (2016-10 → 2026-04, 869 NSE stocks, daily bars)

### Signal-level (all 15,773 trades, no capital constraint)

| Metric | Value |
|---|---|
| Total trades | 15,773 |
| Win rate | 39.5% |
| Exit split | 16,529 SL / 11,626 TP / 1,389 MeshBreak |
| Risk/reward | ~1:2.33 (TP 3.5 ATR vs SL 1.5 ATR) |

> **Read this before quoting any Sharpe figure.** `backtester.py` runs one ticker
> at a time with no portfolio limit, so pooling per-ticker results implies ~115
> concurrent positions and ~2,237% of equity deployed — 99.4% of days exceed 100%
> of capital. Trade-based Sharpe from `analysis.py` treats those overlapping,
> correlated positions as sequential and independent, which overstates it by
> roughly √(concurrent positions). Use `core/portfolio.py` for any figure meant
> to describe a real account.

### Portfolio-level — ₹1,00,000, 15 concurrent positions, no leverage

Marked to market daily via `tools/run_portfolio.py`:

| Scenario | Final value | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| All 869 names @ 0.20% costs | ₹7,14,673 | 23.0% | 1.33 | −30.6% |
| All names @ 0.50% costs | ₹5,08,572 | 18.6% | 1.10 | −34.9% |
| **Liquid only** (≥₹25 cr/day) @ 0.20% | ₹3,78,834 | 15.0% | 1.11 | **−21.2%** |
| All names @ 1.00% costs | ₹2,62,101 | 10.7% | 0.69 | −35.0% |
| *Nifty 50 buy & hold* | *₹2,76,299* | *11.3%* | *0.75* | *−38.4%* |

**Honest summary:** the strategy beats the index on a risk-adjusted basis —
higher Sharpe and roughly half the drawdown. But much of the headline return
came from illiquid smallcaps where 0.05% slippage is unrealistic. Filter to
tradeable names and the return advantage over the Nifty narrows to a few points
a year, while the drawdown advantage holds up. At ~1% round-trip costs the edge
disappears entirely.

Caveats: the universe is built from *current* listings, so delisted companies
are absent (survivorship bias, inflates all of the above). 2025 returned −11%
even on liquid names. See `docs/PARAMETERS.md`.

### Is it alpha or just market exposure?

`python tools/alpha_beta.py` — daily portfolio returns regressed on the Nifty:

| | Value |
|---|---|
| Beta (index exposure) | **0.40** |
| Alpha, annualised | **+10.1%** (t=2.78, p=0.005) |
| R² explained by index | 28.0% |
| Information ratio | 0.96 |
| Up-capture / down-capture | 59.1% / 50.2% |

A leveraged index tracker would show beta ≈ 1, alpha ≈ 0, R² ≈ 90%. This is a
**low-beta strategy with genuine security-selection alpha** — only 28% of its
variance comes from the index.

Caveats: OLS standard errors are not HAC-corrected, so the true t-stat is likely
nearer 2.0–2.5. Alpha is episodic (concentrated in 2020/2021/2024; ~0 in
2018/2019/2025) and no single year is individually significant. Survivorship bias
inflates the idiosyncratic component specifically — i.e. exactly this number.

### Forward paper trading (2026-05-13 → 2026-08-10, 517 closed)

The honest out-of-sample check — real signals, no hindsight:

| Metric | Paper | Backtest |
|---|---|---|
| Win rate | 38.7% | 39.5% |
| Payoff ratio | 1.98 | ~2.10 |
| Expectancy | +0.87%/trade | — |

Signal quality matched the backtest closely. But the two signal types diverge
sharply:

| Signal | n | Win rate | Avg P&L | Total |
|---|---|---|---|---|
| **PB-L** | 87 (17%) | **51.7%** | **+3.59%** | **+312.6%** |
| BO-L | 428 (83%) | 36.2% | +0.33% | +141.7% |

**PB-L is 17% of trades and 70% of profit.** This independently confirms the
backtest finding that breakouts underperform pullbacks in narrow markets.

Note: the 0–7 conviction score is **confounded with signal type** — every BO-L
scores 4–5, every PB-L scores 6–7, so "score ≥ 6" and "PB-L" select the identical
set. The score does not discriminate *within* a signal type and should not be
read as an independent quality measure.

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
│   ├── portfolio.py          # Single-account replay w/ capital limit + liquidity
│   └── ml/
│       ├── feature_builder.py  # ML feature engineering
│       ├── xgb_scorer.py       # XGBoost quality scorer + walk-forward scoring
│       └── kronos_features.py  # Kronos path features (UNUSED — see note below)
│
├── tools/
│   ├── run_portfolio.py      # Portfolio replay: capital limits, ranking rules
│   ├── liquidity_screen.py   # Does the edge survive on tradeable names?
│   └── repair_data_error_trades.py
│
├── docs/
│   └── PARAMETERS.md         # Every parameter, tunable and hardcoded
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
│   ├── test_paper_trader.py
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
├── data.py                   # Yahoo Finance downloader + cache (869 NSE stocks)
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
pytest tests/                 # 77 tests

# Fundamental scorer specifically
python test_fundamental.py

# Portfolio replay with a real capital limit
python tools/run_portfolio.py

# Does the edge survive on liquid names only?
python tools/liquidity_screen.py

# Linting
pip install ruff && ruff check .
```

---

## Important notes

- **Timeframe mismatch:** The Pine Script is tuned for 3H bars; the backtester uses daily bars (yfinance only provides free intraday data for the last 60 days). Use the bot alert to identify *which* stock to look at, then open the 3H chart on TradingView to time the actual entry.
- **Short selling:** Indian cash equity cannot be shorted overnight — positions must be squared off intraday. Holding a short needs stock futures (F&O, ~180-220 eligible names) or SLB. The backtest's short side is effectively dead anyway (84 trades in a decade, net negative).
- **Liquidity matters more than anything else here:** the backtest assumes 0.05% slippage per side on all 869 names. That is fine for largecaps and fiction for a stock trading ₹20 lakh a day. Run `tools/liquidity_screen.py` before trusting any return figure.
- **Kronos is not wired in:** `core/ml/kronos_features.py` and `vendor/kronos/` were an evaluation of the Kronos candlestick foundation model. Zero-shot forecasts proved unstable on daily NSE bars (the same stock/date swung from −7% to +13% purely on context length), so it is unused. Kept for a future fine-tuned attempt.
- **Not financial advice:** This is a quantitative research and learning project. Always do your own analysis before placing any trade.

---

## Data source

Historical data is fetched from **Yahoo Finance** via `yfinance` using `.NS` suffixed tickers (e.g. `WIPRO.NS`). No NSE subscription or scraping required. Daily OHLCV is cached to `data/raw/`; fundamental data is cached to `data/fundamentals/` for 90 days.

---

## License

MIT — free to use, modify, and share.
