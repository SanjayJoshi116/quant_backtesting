## Context

See proposal.md for the reasons behind this change. These facts about the current code shape the design:

- **Inputs.** `run_backtest(df, params, ticker, market_regime, breadth)` in `backtester.py` reads only `Close` plus indicator columns. It never reads `Open`, `High` or `Low`, even though the cached frames from `data.py` contain them.
- **Current exit behaviour.** The exit block (`backtester.py:233-255`) is close-triggered. SL and TP book the level; MeshBreak books the close. `DATA_GAP` force-closes at the close on a bad bar (`:207-231`).
- **Costs.** They are a single round-trip fraction `_rtc`, derived from `costs.commission_pct + costs.slippage_pct`.
- **Portfolio replay.** `core/portfolio.simulate_portfolio(trades, max_positions, max_position_pct, rank_col, round_trip_cost=...)` takes each trade's entry and exit prices as given. It recomputes P&L with its own `rtc`, so the slippage sweep does not need a backtest re-run.
- **How `main.py` runs.** It loads cached data, calls `prepare_indicators`, and optionally builds a Nifty regime series. It passes **no** `breadth` series, so the breadth gate is not active in `main.py` output even though the config enables it. It then writes `results/trades_<ticker>.csv`.
- **Consumers of trade files.** `core/scorecard.py` and `core/ml/feature_builder.py` glob `results/trades_*.csv`, non-recursively.
- **Config plumbing.** Config sections are flattened by `StrategyConfig` (`core/config.py`). The section list at `:177` controls which yaml sections are read.

## Goals / Non-Goals

**Goals:**
- Fill-mode switches whose default is bit-for-bit identical to the current output, proven by a regression test.
- A single command that produces the full comparison report and verdict from cached data, with no network access.
- Scenarios differ **only** in fill mode, so any difference between them can be attributed to fills.

**Non-Goals:**
- Changing the live screener, the paper trader or `main.py` defaults. The parity change will adopt the chosen fill model later.
- Fixing the separate data paths (`auto_adjust=True` versus `False`), the `ffill` bar fabrication or the breadth-gate inconsistency. They are recorded as risks below.
- Acquiring delisted-stock data. The survivorship effect is sized, not removed.
- Re-optimising parameters under the new fill model. That would be a follow-up if the verdict is MARGINAL.

## Decisions

### D1. Fill modes live inside `run_backtest`, selected by params
Two string params are added:
- `entry_fill`: `signal_close` | `next_open`
- `exit_fill`: `close_at_level` | `close_at_close` | `intraday`

They flow through `to_params_dict()` like every other strategy parameter, so the existing `params` override mechanism serves per-run scenario selection unchanged.

- *Alternative: post-process existing trade lists to re-price fills.* Rejected. Next-open entry shifts entry dates and can make a pending entry collide with a new signal or a gap bar. Intraday exits can also end a trade on a different bar. Only the bar loop knows this.
- *Alternative: a separate backtester module.* Rejected. Two copies of the signal logic is exactly the parity problem this project already suffers from.

### D2. Next-open entry uses a one-bar pending state
When a signal fires on bar t in `next_open` mode:
- The loop records a pending entry: direction, signal type and ATR from bar t. It does not open a position.
- At bar t+1, before the exit checks, the pending entry fills at `Open[t+1]`. SL and TP are computed from that fill price and ATR[t].
- If bar t+1 is a bad bar or has a NaN open, the pending entry is cancelled and counted as unfilled.
- Exit checks then run on bar t+1 itself, because the position is held through that bar's close and its intraday range.
- While a signal is pending, no new signal can be taken on the same ticker. This matches today's one-position-per-ticker rule.

### D3. Intraday exit semantics are conservative
In `intraday` mode, the order of checks on each bar is:
1. SL, if `Low <= sl` (long) or `High >= sl` (short). It fills at `min(Open, sl)` for a long, `max(Open, sl)` for a short.
2. TP, if the target is reached. It fills at `max(Open, tp)` for a long, `min(Open, tp)` for a short.
3. MeshBreak, at the close.

If a bar reaches both SL and TP, SL wins, because daily data cannot say which came first. MeshBreak stays close-based because it is an indicator condition evaluated on the close.

- *Alternative: SL/TP tie broken by distance from the open.* Rejected. It is a heuristic, and the goal here is a conservative bound.

### D4. The report tool reuses the `main.py` preparation path
A new `tools/edge_reality_check.py` loads data with `data.load_data`, prepares indicators and builds the regime series exactly as `main.py` does. That preparation will be factored into a shared helper if that is cleaner than duplicating it. The tool mirrors `main.py` in passing no breadth series, so its baseline row reproduces the existing trade files. It runs `run_backtest` once per ticker per fill scenario (4 passes), parallelised with `concurrent.futures.ProcessPoolExecutor`.

Trades are written to `results/edge_check/<scenario>/trades_<ticker>.csv`. The subdirectory keeps them out of the non-recursive `results/trades_*.csv` globs.

### D5. Slippage is swept at the portfolio level only
The per-ticker backtest runs once per fill scenario at the configured cost. The sweep then calls `simulate_portfolio(..., round_trip_cost=2*(commission + slippage_i))` for each level. Break-even slippage is found by linear interpolation between the bracketing sweep points. This keeps compute at 4 backtest passes instead of 4 × 5.

### D6. Survivorship proxies are computed from data we have
- **Seasoned cohort.** A ticker is seasoned if its first valid bar falls on or before `START_DATE` plus a tolerance of 30 calendar days, to absorb holiday and first-bar noise.
- **Causal liquidity.** Trades are kept only if `attach_turnover()`, which is already trailing and causal, shows turnover at entry at or above the configured minimum turnover. This contrasts with the full-period `avg_vol` filter in `core/universe_builder.py`.

Neither proxy captures delisted names. The report says so verbatim, as the spec requires.

### D7. Verdict criteria are pre-registered in config
A new `edge_check:` section in `strategy.yaml` holds the criteria. The proposed values, for the user to confirm before the first run, are:

| Key | Proposed | Meaning |
|---|---|---|
| `realistic_slippage_pct` | 0.0015 | slippage per side in the realistic scenario (3× the current assumption) |
| `survive_min_sharpe` | 0.5 | minimum daily-return Sharpe, realistic scenario |
| `survive_beat_benchmark` | true | CAGR must exceed the Nifty 50 price-index CAGR over the same period |
| `survive_min_breakeven_slippage_pct` | 0.0025 | cost headroom: break-even slippage per side must be at least 0.25% |
| `fail_if_any_period_negative` | true | CAGR ≤ 0 in the in-sample or out-of-sample period ⇒ FAILS |

The verdict logic:
- **SURVIVES**: every survive criterion passes.
- **FAILS**: full-period CAGR ≤ 0, or the period rule trips.
- **MARGINAL**: everything else.

- **Benchmark.** It is the `^NSEI` price series already cached for the regime filter. It excludes dividends, which flatters the strategy by roughly 1–1.5% a year, and the report notes this.
- **Criteria are frozen.** Changing them requires a `config_version` bump (spec requirement), which makes after-the-fact goalpost moves visible in git and in the audit log.

### D8. Versioning and audit
- **Config.** `config_version` goes to `"1.6"`. The `execution` defaults (`signal_close`, `close_at_level`) keep `main.py` trades identical.
- **Audit log.** The tool calls `log_backtest_run` once per scenario. Each row carries the scenario's fill modes in its notes or params field. All rows are appended; the log is never rewritten.
- **Trade records.** Each trade gains `entry_fill` and `exit_fill` columns. These are additive, and existing CSV readers ignore unknown columns.

## Risks / Trade-offs

- **The regression test may be flaky on floating point.** → Compare with a tolerance of 1e-9 on prices and P&L, and exact on dates and reasons.
- **The data-path mismatch is not fixed here.** The backtest uses adjusted prices; live uses unadjusted ones. → The report states the verdict applies to the backtest data path. The parity change owns reconciling the two.
- **`ffill`-fabricated bars carry the previous day's O/H/L.** Intraday fills on those bars use stale prices. → Count trades whose exit bar has volume equal to the previous bar's (a fabricated-bar signature) and report the count. The fix is out of scope.
- **The breadth gate is off in the baseline**, but the parameters were optimised with it on. → Mirror `main.py`, so baseline = existing results. List as a known limitation. Optionally add a breadth-on realistic row if the breadth series builder in `analysis.py` can be reused cheaply (a task decides).
- **Compute time.** 4 × 869 backtests. → Process pool; cached data only; no network.
- **The verdict could still be gamed** by editing the yaml and bumping the version. → Accepted. Traceability is the defence, not prevention.
- **Next-open entry changes position sizing slightly** (the SL distance is relative to a different entry price). → Intended: this is what live would size against.

## Migration Plan

- **Additive and default-preserving.** No migration is needed for existing results.
- **Rollback.** Revert the commit. Defaults mean nothing downstream changes behaviour even without a rollback.
- **Adopting the realistic model later.** If the verdict justifies it, flipping `execution` defaults to the realistic modes is a separate, deliberate config change with its own version bump. It is not part of this change.

## Open Questions

- **Verdict thresholds (D7).** The proposed values need the user's sign-off before the first run. Pre-registration is meaningless if they are tuned after seeing results. The thresholds don't change what gets built.
