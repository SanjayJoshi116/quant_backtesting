## Why

Every reported number for this strategy comes from a backtester whose fill model is optimistic in ways the "Known measurement traps" in CLAUDE.md do not cover:

- **Entry fill.** Entries fill at the signal bar's own close (`backtester.py:357`). The live system can only act the next morning.
- **Stop fill.** The stop-loss triggers when the close is at or below the stop, but the exit is booked at the stop price even when the close gapped far through it (`backtester.py:242-253`).
- **Universe.** The universe is today's surviving stocks, filtered on liquidity averaged over the whole 10 years.
- **Out-of-sample window.** 2021–2026 was consulted while tuning `bo_close_frac` and the breadth gate.

All four biases push results in the same direction. CLAUDE.md already says the edge disappears near 1% round-trip, so the margin is thin enough that realistic fills alone could erase it.

Everything else on the roadmap depends on one answer. That includes live/paper parity, a single data path and ops alerting. **Does a tradable edge exist once execution is modelled realistically?** This change answers it with a pre-registered verdict, before more is invested in the rest of the system.

## What Changes

- **Configurable fill model in the backtester.** A new `execution:` section in `config/strategy.yaml` controls two things:
  - The entry fill: signal-bar close (current) or next bar's open.
  - The SL/TP fill: the current trigger-at-close, book-the-level behaviour; book-at-close; or intraday stop/limit orders with gap-aware fills at the open.

  Defaults reproduce today's behaviour exactly, so every existing result stays reproducible. `config_version` goes from 1.5 to 1.6.
- **New research tool.** It re-runs the per-ticker backtest under each fill scenario on the same cached data, then replays every scenario through `core/portfolio.py` at the account level.
- **Slippage sensitivity sweep** from 0.05% to 0.50% per side. It reports cost headroom: the per-side slippage at which CAGR reaches zero and at which it falls to the benchmark.
- **Survivorship sizing.** The tool compares the seasoned cohort (price data already present at the sample start) with later listings. It also compares the full-period liquidity filter with a causal, trailing-turnover filter. The report states explicitly that the effect of delisted stocks cannot be measured with the current data source.
- **Period split.** Every scenario is broken out into 2016–2020 (in-sample) and 2021–2026 (out-of-sample, contaminated by tuning). A per-year table sits alongside.
- **Pre-registered verdict.** The criteria are SURVIVES / MARGINAL / FAILS. They live in config and are fixed before the first run, so the goalposts can't move after the numbers are seen.
- **Output location.** Scenario trade files go to a subdirectory of `results/`. They never overwrite the baseline `results/trades_*.csv` files that the scorecard and ML feature builder read.

## Capabilities

### New Capabilities
- `backtest-execution-model`: How the backtester fills entries and SL/TP exits, how it treats gaps, and how the choice is configured. The default mode must be identical to the current behaviour.
- `edge-reality-report`: A reproducible account-level comparison of fill scenarios, slippage levels, universe cohorts and periods. It ends in a pre-registered verdict on whether the edge survives.

### Modified Capabilities
<!-- none: openspec/specs/ has no existing specs -->

## Impact

- **Code:**
  - `backtester.py`: fill logic, and it now reads Open/High/Low as well as Close.
  - `core/config.py`: new `execution` and `edge_check` fields; `to_params_dict`; section registration.
  - `config/strategy.yaml`: new sections, and the version goes to 1.6.
  - New `tools/edge_reality_check.py`.
  - New tests.
- **Unchanged:**
  - Live screener, paper trader, email, dashboard.
  - Existing `results/trades_*.csv` files.
  - Default `main.py` output. The config hash changes because the version bumps, but the trades must be identical.
- **Compute:** at least 4 full per-ticker backtest passes over 869 tickers. The portfolio replays are cheap by comparison.
- **Decision impact:** a FAILS or MARGINAL verdict should reprioritise the roadmap. It would pause the parity and ops work in favour of strategy research.
