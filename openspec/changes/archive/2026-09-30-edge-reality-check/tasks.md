## 1. Config

- [x] 1.1 Add an `execution:` section to `config/strategy.yaml` with `entry_fill: signal_close` and `exit_fill: close_at_level`, with a comment listing the allowed values
- [x] 1.2 Add an `edge_check:` section to `config/strategy.yaml` with the proposed criteria from design D7, marked "pre-registered — confirm before first run"
- [x] 1.3 Add the matching fields to `StrategyConfig` in `core/config.py`, using `Literal` types so unknown modes are rejected; register both sections in the section list; expose the execution fields through `to_params_dict()`
- [x] 1.4 Bump `config_version` to `"1.6"` and document the new sections in `docs/PARAMETERS.md`
- [x] 1.5 Extend `tests/test_config.py`: defaults load, an invalid mode raises with the allowed values in the message, and a params override takes precedence

## 2. Backtester fill model

- [x] 2.1 Before changing `backtester.py`, capture a baseline fixture: default-mode trades for a fixed set of about 10 cached tickers covering longs, shorts, SL, TP, MeshBreak and DATA_GAP
- [x] 2.2 Read the `entry_fill` / `exit_fill` params in `run_backtest` and validate them; extract `Open` / `High` / `Low` arrays alongside `Close`
- [x] 2.3 Implement the `next_open` pending-entry state (design D2): fill at the next open with ATR[t]; cancel and count as unfilled on a final bar, a bad bar or a NaN open; no new signal while pending
- [x] 2.4 Implement the `close_at_close` and `intraday` exit modes (design D3), SL-first on ties, for longs and shorts; keep MeshBreak and DATA_GAP close-based
- [x] 2.5 Add `entry_fill` and `exit_fill` to every trade record, DATA_GAP included; return the unfilled-signal count in a way that doesn't break existing callers
- [x] 2.6 Add a regression test: default modes reproduce the 2.1 baseline (dates and reasons exact, prices and P&L within 1e-9)
- [x] 2.7 Add synthetic-frame unit tests for every scenario in `specs/backtest-execution-model/spec.md`: next-open fill and SL level, final-bar signal, gap-bar signal, close gap-through, open gap below the SL, intraday touch without a gap, SL+TP in the same bar, short gap above the SL, identical costs across modes
- [x] 2.8 Add a no-lookahead test: mutating bar t+1 must not change whether bar t signals
- [x] 2.9 Run `python main.py` in default modes and confirm the output trades match the pre-change files (the config hash will differ, the trades must not)

## 3. Edge reality check tool

- [x] 3.1 Factor the `main.py` data-load, indicator and regime preparation into a reusable helper, or reuse it directly, so the tool and `main.py` prepare identical inputs
- [x] 3.2 Create `tools/edge_reality_check.py`: run the 4 fill scenarios across the universe with a process pool, cached data only; write trades to `results/edge_check/<scenario>/trades_<ticker>.csv`
- [x] 3.3 Assert at startup and at the end that no top-level `results/trades_*.csv` file was created or modified (compare mtimes and hashes)
- [x] 3.4 Portfolio replay per scenario through `simulate_portfolio` with the configured position limits; collect the metrics listed in the spec (win rate excludes breakevens, `pnl_pct == 0`)
- [x] 3.5 Run the slippage sweep (0.05, 0.10, 0.15, 0.25, 0.50 % per side) for the baseline and realistic scenarios via `round_trip_cost`; interpolate break-even slippage against zero CAGR and against the benchmark CAGR; handle out-of-range results
- [x] 3.6 Compute the benchmark CAGR from the cached `^NSEI` series over the same period, noting it is price-only
- [x] 3.7 Build the survivorship proxies: seasoned versus later-listed cohorts (first bar ≤ START_DATE + 30d), and the causal-liquidity variant via `attach_turnover()`
- [x] 3.8 Split each scenario into 2016–2020, 2021 onwards, and a per-calendar-year return table
- [x] 3.9 Count trades whose exit bar looks forward-filled (volume identical to the prior bar) per scenario, for the risk disclosure
- [x] 3.10 Implement the verdict function from the `edge_check` config: SURVIVES / MARGINAL / FAILS with a per-criterion PASS/FAIL table; unit-test it on hand-made metric dicts
- [x] 3.11 Write `results/edge_check/edge_reality_report.md` and a `summary.csv`, including the fixed disclosures: delisted stocks unmeasured, tuning-contaminated OOS, data-path caveat, breadth gate off, price-only benchmark
- [x] 3.12 Append one `log_backtest_run` audit row per scenario, with its fill modes recorded; never rewrite logs
- [x] 3.13 (Optional) Add a breadth-on realistic row if the breadth series from `analysis.py` can be reused without new data fetching

## 4. Run and decide

- [x] 4.1 **Gate:** the user confirms or edits the `edge_check` thresholds in `strategy.yaml` and commits them before the first full run
- [x] 4.2 Run the tool end-to-end; confirm a second run on the same cache gives the same metrics and verdict
- [x] 4.3 Run `pytest tests/` and `ruff check .`; both clean
- [x] 4.4 Add the verdict and headline numbers to CLAUDE.md "Known measurement traps" (fill-model bias and cost headroom), and link the report
- [x] 4.5 Record the recommended next step from the verdict: SURVIVES → the parity / single-source-of-truth change; MARGINAL → strategy research under the realistic fill model; FAILS → pause the live signals and paper ledger work

## Outcome (2026-09-30)

- Verdict: **FAILS** (config 1.6). Realistic @ 0.15%/side: CAGR -17.78%, Sharpe -0.654, max DD -89.17%; 2016-20 CAGR -12.27%, 2021+ -21.86%; Nifty price CAGR 11.47%.
- Two full runs gave a byte-identical summary.csv.
- Trade-level check (no capital limit): mean P&L/trade baseline +1.64%, next_open +0.97%, gap_exit +1.15%, realistic +0.30%; fill effects roughly additive, so no interaction bug.
- Next step: pause live-signal and paper-ledger work; strategy research under the realistic fill model. Operational pause (CI ledger cron) awaits user decision.
- 4.3 needed `ruff.toml` (exclude vendor/, .claude/) and lint fixes in core/ml/kronos_features.py, tools/alpha_beta.py, tools/liquidity_screen.py, tools/run_portfolio.py.
