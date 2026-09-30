## Purpose

Produces a reproducible, account-level comparison of the strategy under realistic execution, costs, universe composition and time periods, ending in a verdict fixed in advance on whether a tradable edge exists.

## ADDED Requirements

### Requirement: Scenario matrix at portfolio level
The report SHALL evaluate at least these fill scenarios:
- baseline: `signal_close` + `close_at_level`
- next-open entry only
- gap-aware exit only
- next-open entry with gap-aware exit, the **realistic** scenario

Every scenario SHALL be measured through the capital-limited portfolio replay using the configured position limits. It SHALL NOT be measured by pooling per-ticker results. For each scenario the report SHALL give:
- trades taken and trades unfilled
- CAGR
- daily-return Sharpe
- maximum drawdown
- total return
- win rate, with breakevens counted as neither win nor loss
- average loss

#### Scenario: All scenarios reported side by side
- **WHEN** the edge reality check runs to completion
- **THEN** the report contains one row per scenario with every listed metric, computed from the portfolio replay

#### Scenario: Same inputs across scenarios
- **WHEN** scenarios are compared
- **THEN** they use the same cached price data, the same universe, the same strategy parameters and the same portfolio limits, and differ only in fill mode

### Requirement: Slippage sensitivity and cost headroom
The report SHALL sweep per-side slippage over at least 0.05%, 0.10%, 0.15%, 0.25% and 0.50% for the baseline and realistic scenarios. It SHALL report the per-side slippage at which portfolio CAGR reaches zero and the slippage at which it falls to the benchmark CAGR. If the threshold lies outside the swept range, it SHALL say so.

#### Scenario: Break-even slippage found
- **WHEN** realistic-scenario CAGR is positive at 0.05% and negative at 0.25% per side
- **THEN** the report states an interpolated break-even slippage between those values

#### Scenario: Edge survives the whole sweep
- **WHEN** CAGR stays above zero at every swept slippage level
- **THEN** the report states break-even slippage is above the maximum swept value

### Requirement: Survivorship sizing
The report SHALL compare the realistic scenario across two cohorts:
- tickers whose price history starts at or before the sample start (seasoned)
- tickers that enter later

It SHALL also compare the full-period liquidity filter with a causal filter that admits a trade only if trailing turnover at entry, computed from data up to entry, meets the configured minimum. The report SHALL state in plain words that stocks delisted, merged or suspended before today are absent from the data and that their effect is not measured.

#### Scenario: Cohort comparison shown
- **WHEN** the report is produced
- **THEN** it shows portfolio metrics for the seasoned cohort, the later-listed cohort and the causal-liquidity variant, next to the realistic full-universe row

#### Scenario: Unmeasured bias disclosed
- **WHEN** the report is produced
- **THEN** it contains an explicit statement that delisted-stock survivorship bias is not measured and that results remain an upper bound in that respect

### Requirement: Period split and contamination disclosure
The report SHALL break every scenario into the in-sample period (2016–2020) and the tuning-contaminated out-of-sample period (2021 onwards), plus a per-calendar-year table. It SHALL state that the out-of-sample period was consulted during parameter tuning and so is not a clean holdout.

#### Scenario: Period breakdown present
- **WHEN** the report is produced
- **THEN** each scenario shows separate metrics for 2016–2020 and 2021 onwards, and a per-year return table

### Requirement: Pre-registered verdict
The report SHALL end with exactly one verdict: SURVIVES, MARGINAL or FAILS. The verdict SHALL be computed mechanically from criteria in the `edge_check` config section, which is fixed before the first run. The report SHALL print the criteria, the measured values and which criteria passed or failed. Changing the criteria SHALL require a `config_version` bump, so a changed verdict is traceable.

#### Scenario: Verdict computed from config criteria
- **WHEN** the realistic scenario meets every SURVIVES criterion in `edge_check`
- **THEN** the verdict is SURVIVES and each criterion is listed with its measured value and PASS

#### Scenario: Negative period forces FAILS
- **WHEN** realistic-scenario CAGR is at or below zero in either the in-sample or the out-of-sample period
- **THEN** the verdict is FAILS regardless of the full-period result

### Requirement: Outputs do not contaminate existing consumers
Scenario trade files and report outputs SHALL be written under a dedicated subdirectory of `results/`. The run SHALL NOT create, modify or overwrite any top-level `results/trades_*.csv` file read by the scorecard or the ML feature builder. The run SHALL append one audit row per scenario through the existing audit logging, never truncating existing logs.

#### Scenario: Baseline trade files untouched
- **WHEN** the edge reality check completes
- **THEN** every pre-existing top-level `results/trades_*.csv` file is byte-identical to before, and no new file matching that pattern exists at the top level

#### Scenario: Reproducible report
- **WHEN** the check is run twice on the same cached data and config
- **THEN** both runs produce the same metrics and the same verdict
