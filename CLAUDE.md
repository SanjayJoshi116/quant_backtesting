# CLAUDE.md — NSE Swing Trading System

## Project overview

Three-tier quantitative trading system for NSE (Indian equities):

1. **Backtester** (`main.py` + `backtester.py`) — validates strategy on 10 years of daily OHLCV across 185+ stocks
2. **Live screener** (`bot/`) — scans 2,258 NSE stocks each morning, emails actionable signals
3. **Dashboard** (`dashboard.py`) — Streamlit UI for signals, scorecard, patterns, fundamentals

## Entry points

| File | Purpose | How to run |
|---|---|---|
| `main.py` | Full backtest pipeline | `python main.py` |
| `pipeline.py` | Unified Typer CLI | `python pipeline.py [backtest\|screen\|both\|config]` |
| `bot/main.py` | Live screener + email | `python bot/main.py [--dry-run] [--tickers X.NS]` |
| `dashboard.py` | Streamlit dashboard | `streamlit run dashboard.py` |
| `test_fundamental.py` | Fundamental scorer smoke test | `python test_fundamental.py` |
| `tests/` | Pytest suite | `pytest tests/` |

## Configuration

`config/strategy.yaml` is the **single source of truth** for all strategy parameters (RSI thresholds, ADX minimum, ATR multipliers, position sizing, execution costs). It is versioned and loaded via `core/config.py` (`StrategyConfig` Pydantic model).

**Never hardcode strategy parameters in Python files.** Always read from `core/config.py` via `load_config()`.

## Architecture rules

- **No lookahead bias** — all indicators in `indicators.py` and `core/patterns.py` are strictly causal (only use data available at bar `t` to produce values at bar `t`). Never use `.shift(-n)` or future prices.
- **Cache layer** — use `core/data.py` (`fetch_or_load()`) for all data fetching, not raw `yfinance` calls. Both the backtester and live screener share this layer to guarantee identical data.
- **Append-only audit logs** — `core/logging.py` writes one row per backtest run / signal / data fetch to `logs/`. Never truncate these files.
- **Config hash** — each audit log row includes a config version hash so results are traceable to the exact parameter set.
- **Config version** — `config_version` is a first-class field on `StrategyConfig` (read from top-level key in `strategy.yaml`). Audit logs write the real version (e.g. `"1.3"`), not a hardcoded default. Bump `config_version` in `strategy.yaml` whenever any parameter changes.
- **NaN bar handling** — the backtester force-closes any open position that hits a NaN indicator bar, recording exit reason `DATA_GAP`. Positions are never left orphaned.
- **Pandas 2.0 compat** — use `.reindex(idx).ffill()` not `.reindex(idx, method="ffill")`. Use `df = df.ffill().dropna()` not `inplace=True`.

## Key modules — where things live

| What you need | File |
|---|---|
| Signal detection logic | `bot/signal_engine.py` (live bar), `backtester.py` (historical) |
| Indicator computation | `indicators.py` |
| Chart pattern detection | `core/pattern_scanner.py` (11+ patterns), `core/patterns.py` (S/R, pivots) |
| Fundamental quality score | `core/fundamental_scorer.py` |
| ML scoring | `core/ml/xgb_scorer.py`, `core/ml/feature_builder.py` |
| Stock universe | `bot/universe.py` (live), `data.py` (backtest ticker list) |
| Historical performance lookup | `core/scorecard.py` |
| Email alert builder | `bot/notifier.py` |
| Paper trading | `core/paper_trader.py` |
| Walk-forward optimisation | `optimization.py` |
| Monte Carlo simulation | `montecarlo.py` |

## Data

- Source: Yahoo Finance via `yfinance`, tickers use `.NS` suffix (e.g. `WIPRO.NS`)
- Daily OHLCV cache: `data/raw/` (auto-created)
- Fundamental cache: `data/fundamentals/` JSON per ticker, refreshed every 90 days
- Backtest universe: 185 NSE stocks defined in `data.py`, grouped by sector
- Screener universe: 2,258 stocks from `stocks_list.csv`

## Email alerts

Requires a `.env` file in the project root (never commit this):
```
GMAIL_SENDER=you@gmail.com
GMAIL_APP_PASS=xxxx xxxx xxxx xxxx   # 16-char Google App Password
ALERT_RECIPIENTS=you@gmail.com,other@gmail.com
```

Copy `.env.example` → `.env` and fill in values.

## Testing

```bash
pytest tests/                  # unit tests (config, data, logging, signals)
python test_fundamental.py     # fundamental scorer integration test
python main.py                 # full backtest = integration test for the engine
G:\Anaconda\envs\stock\Scripts\ruff.exe check .   # linting (zero errors expected)
```

## What NOT to do

- Don't commit `.env` (contains Gmail credentials)
- Don't hardcode RSI/ADX/ATR values in Python — use `config/strategy.yaml`
- Don't add lookahead bias to indicators (no future data, no `.shift(-n)`)
- Don't call `yfinance` directly in new code — go through `core/data.py`
- Don't truncate or delete files in `logs/` — they are append-only audit trails
- Don't swallow exceptions silently (`except Exception: pass`) — at minimum `warnings.warn(str(e))`
- Don't use `reindex(method="ffill")` or `inplace=True` — both deprecated in pandas 2.0
- Don't use `open(path)` without a context manager — always `with open(path) as f:`
- Don't count breakeven trades (`pnl_pct == 0`) as losses — use `< 0` not `<= 0` for loss filters
