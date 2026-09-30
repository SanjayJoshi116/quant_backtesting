# backtest-execution-model Specification

## Purpose

Defines how the historical backtester turns a signal into an entry fill and a stop-loss or take-profit trigger into an exit fill, including behaviour on price gaps, so that reported results reflect prices a trader could actually have obtained.

## Requirements

### Requirement: Fill model is configuration-driven
The backtester SHALL read its entry fill mode and its SL/TP exit fill mode from the `execution` section of `config/strategy.yaml`, loaded through the strategy config model. It SHALL also accept both modes as per-run parameter overrides. Fill modes SHALL NOT be hardcoded.

#### Scenario: Modes come from config
- **WHEN** `strategy.yaml` sets `execution.entry_fill: next_open` and no override is passed
- **THEN** the backtest uses next-open entry fills

#### Scenario: Per-run override wins
- **WHEN** config sets `entry_fill: signal_close` and a run passes an override of `entry_fill: next_open`
- **THEN** that run uses next-open entry fills and the config file is unchanged

#### Scenario: Unknown mode is rejected
- **WHEN** config or an override names a fill mode that does not exist
- **THEN** config loading or the run fails with an error naming the invalid value and the allowed values

### Requirement: Default mode reproduces current results exactly
With `entry_fill: signal_close` and `exit_fill: close_at_level`, the backtester SHALL produce trades identical to the pre-change backtester for the same input data and parameters, in every column except fields that record the config version or hash.

#### Scenario: Regression against baseline
- **WHEN** the backtest runs on a fixed set of tickers in default modes
- **THEN** every trade's entry and exit dates, prices, exit reason, `pnl_pct` and `pnl_on_equity` match the pre-change output

### Requirement: Next-open entry fill
In `next_open` mode, a signal detected on the close of bar t SHALL fill at the open of bar t+1. The entry date is bar t+1. SL and TP levels SHALL be computed from the fill price using the ATR known at bar t. A signal with no valid next bar SHALL NOT produce a trade and SHALL be counted as unfilled.

#### Scenario: Normal next-open fill
- **WHEN** a long signal fires on bar t, bar t+1 opens at 102, and ATR at t is 4 with `sl_mult` 1.5
- **THEN** the trade's entry date is bar t+1, its entry price is 102 and its stop is 96

#### Scenario: Signal on the final bar
- **WHEN** a signal fires on the last bar of the data
- **THEN** no trade is recorded and the unfilled count increases by one

#### Scenario: Next bar is a data gap
- **WHEN** a signal fires on bar t and bar t+1 has missing prices or indicators
- **THEN** no trade is recorded and the unfilled count increases by one

#### Scenario: No bar t+1 information used at signal time
- **WHEN** deciding whether bar t produces a signal
- **THEN** only data up to and including bar t is used

### Requirement: Gap-aware exit fills
The backtester SHALL support these SL/TP exit fill modes:
- `close_at_level`: trigger on the close and book the SL/TP level. This is the current behaviour.
- `close_at_close`: trigger on the close and book the close.
- `intraday`: the stop triggers when the bar's low reaches the SL (high for shorts) and fills at the worse of the SL and the bar's open. The target triggers when the bar's high reaches the TP (low for shorts) and fills at the better of the TP and the bar's open.

MeshBreak and DATA_GAP exits SHALL remain close-based in every mode.

#### Scenario: Close gaps through the stop in close_at_close mode
- **WHEN** a long position has SL 100 and the bar closes at 94
- **THEN** the exit is booked at 94 with reason SL

#### Scenario: Open gaps below the stop in intraday mode
- **WHEN** a long position has SL 100 and the next bar opens at 95 with low 93
- **THEN** the exit is booked at 95 with reason SL

#### Scenario: Stop touched intraday without a gap
- **WHEN** a long position has SL 100 and the bar opens at 103 with low 99
- **THEN** the exit is booked at 100 with reason SL

#### Scenario: Stop and target both reachable in one bar
- **WHEN** in intraday mode a single bar's range covers both the SL and the TP
- **THEN** the exit is booked as SL (conservative assumption)

#### Scenario: Short position gaps above the stop
- **WHEN** a short position has SL 100 and the bar opens at 106
- **THEN** in intraday mode the exit is booked at 106 with reason SL

### Requirement: Costs apply identically in every mode
Commission and slippage from the `costs` config SHALL be deducted the same way regardless of fill mode, so that differences between scenarios come only from fill prices.

#### Scenario: Same cost deduction
- **WHEN** two trades with identical entry and exit prices are produced under different fill modes
- **THEN** their `pnl_pct` values are identical

### Requirement: Fill mode is recorded
Each trade record SHALL include the entry fill mode and exit fill mode it was produced under. Audit log rows for a backtest run SHALL reflect the config version and hash in force.

#### Scenario: Trade carries its modes
- **WHEN** a trade is produced in `next_open` / `intraday` modes
- **THEN** its record contains those two mode names
