# Strategy Parameter Inventory

Every input that determines what this strategy does, where it lives, and whether
you can currently change it.

**Status: the 13 indicator constants are now tunable** (`indicators:` section in
`strategy.yaml`, read by `prepare_indicators()` when its args are left at None).
They were previously hardcoded and had never been searched.

**First result from searching them:** `bo_close_frac` — the breakout-candle
close filter — is worth far more than anything in the old grid:

| bo_close_frac | IS Sharpe | OOS Sharpe | OOS CAGR | OOS maxDD |
|---|---|---|---|---|
| 0.96 (old hardcoded) | 0.86 | 1.09 | 15.75% | −18.4% |
| **0.99** | 1.17 | **1.22** | **17.73%** | **−16.2%** |
| 0.995 | **1.36** | 1.20 | 15.86% | −10.6% |

`hh_window` — despite governing 74% of trades — was flat across 8/12/16/20
(Sharpe 1.18–1.25 at bo=0.99). Volume of trades is not the same as leverage over
results.

---

## 1. Tunable — `config/strategy.yaml`

These are read via `core/config.py` (`StrategyConfig`) and are the only values
the optimiser can search.

### Exit / risk
| Param | Value | Meaning |
|---|---|---|
| `sl_mult` | 1.5 | SL = entry − ATR × this |
| `tp_mult_long` | 3.5 | TP = entry + ATR × this |
| `tp_mult_short` | 2.25 | TP = entry − ATR × this |

### Trend filters
| Param | Value | Meaning |
|---|---|---|
| `adx_long` | 18 | min ADX for a long |
| `adx_short` | 20 | min ADX for a short |
| `di_gap_min` | 5.0 | DI− must lead DI+ by this (short only) |
| `min_room_atr` | 3.0 | min ATR room-to-fall (short only) |

### Entry conditions
| Param | Value | Meaning |
|---|---|---|
| `rsi_pb_lo` / `rsi_pb_hi` | 35 / 58 | RSI band for pullback long |
| `pb_tol` | 1.008 | low ≤ EMA21 × this |
| `rsi_bo_lo` / `rsi_bo_hi` | 48 / 75 | RSI band for breakout long |
| `rsi_pbs_lo` / `rsi_pbs_hi` | 45 / 60 | RSI band for pullback short |
| `pb_short_tol` | 0.997 | high ≥ EMA21 × this |
| `rsi_bos_lo` / `rsi_bos_hi` | 30 / 50 | RSI band for breakout short |
| `vol_mult_long` | 1.1 | volume ≥ VOL_SMA20 × this |
| `vol_mult_short` | 1.3 | same, short side |

### Regime / data / sizing / costs / ML
| Param | Value | Meaning |
|---|---|---|
| `regime_enabled` | false | Nifty EMA200 gate (disabled) |
| `nifty_ema_period` | 200 | |
| `data_period` | 2y | yfinance download window (screener) |
| `min_bars` | 260 | skip ticker below this |
| `cache_ttl_hours` | 24 | |
| `starting_capital` | 100000 | |
| `risk_per_trade_pct` | 1.5 | |
| `max_position_pct` | 20.0 | per-position cap |
| `max_positions` | 15 | concurrent positions (portfolio layer) |
| `max_gross_pct` | 100.0 | total deployed cap |
| `commission_pct` | 0.0005 | per side |
| `slippage_pct` | 0.0005 | per side |
| `ml_enabled` | false | |
| `ml_min_score` | 0.50 | |
| `ml_min_score_bear` | 0.53 | |

### Execution / fill model (`execution:`, backtester only)
| Param | Value | Meaning |
|---|---|---|
| `entry_fill` | signal_close | `signal_close` = fill at the signal bar's close (v1.5 behaviour); `next_open` = fill at the next bar's open |
| `exit_fill` | close_at_level | `close_at_level` = trigger on close, book SL/TP level (v1.5); `close_at_close` = book the close; `intraday` = trigger on Low/High, gap-aware fill at Open, SL wins ties |

### Edge reality check (`edge_check:`, pre-registered — `tools/edge_reality_check.py` only)
| Param | Value | Meaning |
|---|---|---|
| `realistic_slippage_pct` | 0.0015 | slippage per side in the realistic scenario |
| `survive_min_sharpe` | 0.5 | min daily-return Sharpe for SURVIVES |
| `survive_beat_benchmark` | true | CAGR must beat Nifty 50 (price index) |
| `survive_min_breakeven_slippage_pct` | 0.0025 | min cost headroom per side |
| `fail_if_any_period_negative` | true | CAGR ≤ 0 in 2016-20 or 2021+ ⇒ FAILS |
| `causal_min_turnover_cr` | 25.0 | causal-liquidity row: min 60-bar median turnover at entry (Rs cr/day); not a verdict criterion |

Changing any `edge_check` value after results exist requires a `config_version` bump.

---

## 2. Hardcoded — not in config, not optimised

### `indicators.py`
| Value | Line | What it controls |
|---|---|---|
| EMA 21 / 50 / 200 | 62-64 | the entire trend definition |
| RSI window 14 | 67 | every RSI band above is relative to this |
| ADX window 14 | 70-73 | |
| ATR window 14 | 79-82 | **sets SL and TP distance and position size** |
| VOL_SMA 20 | 85 | volume baseline |
| Weekly EMA 50, `W-FRI`, min 52 wks | 32-38 | higher-timeframe filter |
| EMA slope lookback 5 bars | 93-94 | part of `bull_trend` |
| `candle_bull` close-off-low ≥ 0.50 | 116-119 | candle quality gate |
| `candle_bear` close-off-high ≥ 0.50 | 120-123 | |
| `bo_candle_bull` close ≥ high × 0.96 | 124-127 | breakout candle gate |
| `bo_candle_bear` close ≤ low × 1.04 | 128-131 | |
| `highest_high_12` window 12 | 136 | **the breakout lookback — BO-L is 74% of trades** |
| `lowest_low_12` window 12 | 137 | |
| `lowest_low_50` window 50 | 140 | room-to-fall base |

### `core/patterns.py`
| Value | Line | What it controls |
|---|---|---|
| `pivot_n` = 3 (window 7) | 27, 133 | swing pivot detection |
| `base_period` = 15 | 85, 134 | flat-base length |
| `max_range_pct` = 5.0 | 86, 135 | flat-base tightness |
| `sr_atr_mult` = 1.5 | 61, 136 | `near_support` distance |
| volume contraction 0.85 | 108 | base quality +1 |

### `backtester.py`
| Value | What it controls |
|---|---|
| BASE-BO volume `× 1.2` | stricter volume on base breaks |
| Signal priority PB-L > BASE-BO > BO-L > PB-S > BO-S | which signal wins when several fire |
| Exit priority MeshBreak > SL > TP | |
| **Exits evaluated on CLOSE only** (default `exit_fill`) | intrabar High/Low only with `exit_fill: intraday` |
| `pct_from_high` window 253 | ML feature |

### `bot/signal_engine.py`
| Value | What it controls |
|---|---|
| score components, 0–7 scale | the score shown in alert emails |
| S/R zone ±1.5%, 200-bar lookback | `sr_test_count` |
| `pct_from_high` 252-bar | display |

### `core/ml/xgb_scorer.py`
`n_estimators` 300, `max_depth` 4, `learning_rate` 0.05, `subsample` 0.8,
`colsample_bytree` 0.8, `min_child_weight` 10, plus the 10 `FEATURE_COLS`.

---

## 3. Universe

| Input | Size | Source |
|---|---|---|
| Backtest universe | **869** tickers | `data.py` → `TICKERS` |
| Screener universe | 2,258 | `stocks_list.csv` |
| Liquidity filter | **none** | see below |

No survivorship-bias control: the list is current listings, so delisted
companies are absent and results are biased upward.

---

## 4. Where the leverage actually is

Ranked by likely impact on results, most to least:

1. **Liquidity filter (currently absent).** Restricting to ≥ ₹25 cr/day median
   turnover changed CAGR from 23.0% to 15.0% but improved Sharpe to 1.11 and cut
   max drawdown from −30.6% to −21.2%. This is the single biggest lever and it
   isn't a parameter yet.
2. **`highest_high_12`** — BO-L is 74% of all trades and this one hardcoded
   number defines it. Never tested at 10, 15, 20.
3. **ATR window 14** — sets stop distance, target distance *and* position size
   simultaneously. Three behaviours, one untested constant.
4. **`sl_mult` / `tp_mult_long`** — tuned, but as fixed multiples for every
   stock in every regime.
5. **EMA 21/50/200** — the whole trend definition rests on three numbers copied
   from convention.
6. **Short-side parameters** — 8 tunable params governing 0.3% of trades. Dead
   weight; either fix the entry conditions or delete the side.

---

## 5. Known issues

- The per-ticker backtester has no portfolio constraint; use `core/portfolio.py`
  for any figure that is meant to describe a real account.
- Trade-based Sharpe in `analysis.py` treats overlapping positions as sequential
  and independent, which overstates it by roughly √(concurrent positions).
- `PB50-L` is referenced in `analysis.py`, both signal encodings and
  `pipeline.py:225` (which prints `rsi_pb50_*` params that `test_config.py`
  asserts must not exist), but **no entry logic generates it**. Dead code.
- `results/trades_OOS_best.csv` is the optimiser's aggregate under a *different*
  parameter set; ~56% of its rows duplicate the per-ticker CSVs. Never glob it in
  with `trades_*.csv`.
