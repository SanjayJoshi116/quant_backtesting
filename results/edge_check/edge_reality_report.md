# Edge Reality Check

Generated 2026-09-30 10:00 · config_version 1.6 · 855 tickers · period 2016-10-26 → 2026-04-29

## Verdict: **FAILS**

Basis: realistic scenario (next-open entry, intraday gap-aware exits) at 0.15% slippage per side, one account, 15 positions max, 20% max per position. Criteria are the pre-registered `edge_check` values in `config/strategy.yaml`.

| criterion | kind | measured | threshold | result |
|---|---|---|---|---|
| Sharpe (daily, realistic) | survive | -0.654 | >= 0.5 | FAIL |
| Break-even slippage per side | survive | 0.000% | >= 0.25% | FAIL |
| CAGR vs Nifty 50 price CAGR | survive | -17.78 | > 11.47 | FAIL |
| Full-period CAGR | fail | -17.78 | > 0 | FAIL |
| CAGR 2016-2020 | fail | -12.27 | > 0 | FAIL |
| CAGR 2021+ | fail | -21.86 | > 0 | FAIL |

## 1. Fill scenarios (configured costs)

Configured cost: 0.05% commission + 0.05% slippage per side. Scenarios differ only in fill mode.

| label | trades_generated | unfilled_signals | trades_taken | trades_skipped | cagr | sharpe | max_dd | total_return | win_rate | avg_loss | cagr_2016-2020 | sharpe_2016-2020 | cagr_2021+ | sharpe_2021+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 15189 | 0 | 642 | 14547 | 21.97 | 1.013 | -34.9 | 560.91 | 38.94 | -6.781 | 15.27 | 0.815 | 27.51 | 1.151 |
| next_open | 15396 | 7 | 708 | 14688 | 16.35 | 0.786 | -32.46 | 321.74 | 37.99 | -6.608 | 13.11 | 0.704 | 18.95 | 0.846 |
| gap_exit | 16832 | 0 | 957 | 15875 | 13.21 | 0.665 | -53.02 | 225.23 | 35.42 | -6.918 | -1.81 | 0.018 | 26.6 | 1.11 |
| realistic | 17025 | 6 | 1108 | 15917 | -14.1 | -0.488 | -84.02 | -76.43 | 28.79 | -6.79 | -6.67 | -0.195 | -19.52 | -0.685 |

Verdict row (realistic @ 0.15% slippage per side):

| label | trades_generated | unfilled_signals | trades_taken | trades_skipped | cagr | sharpe | max_dd | total_return | win_rate | avg_loss | cagr_2016-2020 | sharpe_2016-2020 | cagr_2021+ | sharpe_2021+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| realistic @ 0.15% slippage per side | 17025 | 6 | 1084 | 15941 | -17.78 | -0.654 | -89.17 | -84.44 | 28.69 | -7.005 | -12.27 | -0.46 | -21.86 | -0.787 |

## 2. Slippage sweep and cost headroom

| label | trades_taken | cagr | sharpe | max_dd |
|---|---|---|---|---|
| baseline @ 0.05% | 642 | 21.97 | 1.013 | -34.9 |
| baseline @ 0.10% | 647 | 23.74 | 1.065 | -32.6 |
| baseline @ 0.15% | 618 | 19.89 | 0.954 | -32.93 |
| baseline @ 0.25% | 612 | 16.65 | 0.825 | -35.13 |
| baseline @ 0.50% | 627 | 5.51 | 0.357 | -42.84 |
| realistic @ 0.05% | 1108 | -14.1 | -0.488 | -84.02 |
| realistic @ 0.10% | 1098 | -15.16 | -0.536 | -85.86 |
| realistic @ 0.15% | 1084 | -17.78 | -0.654 | -89.17 |
| realistic @ 0.25% | 1100 | -22.88 | -0.902 | -92.32 |
| realistic @ 0.50% | 1116 | -27.6 | -1.121 | -95.82 |

Benchmark (Nifty 50 price index, same period): CAGR 11.47%

- **baseline**: CAGR reaches zero at above 0.50% per side (the whole sweep); falls to the benchmark at 0.366% per side.
- **realistic**: CAGR reaches zero at below 0.05% per side (the lowest swept level); falls to the benchmark at below 0.05% per side (the lowest swept level).

## 3. Survivorship proxies (realistic scenario)

Seasoned = first cached bar on or before 2016-01-31 (836 tickers); later-listed = the rest (19). Causal liquidity keeps a trade only if the 60-bar trailing median turnover on the signal bar is at least Rs 25 cr/day.

| label | trades_generated | unfilled_signals | trades_taken | trades_skipped | cagr | sharpe | max_dd | total_return | win_rate | avg_loss | cagr_2016-2020 | sharpe_2016-2020 | cagr_2021+ | sharpe_2021+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| realistic @ 0.15% slippage per side | 17025 | 6 | 1084 | 15941 | -17.78 | -0.654 | -89.17 | -84.44 | 28.69 | -7.005 | -12.27 | -0.46 | -21.86 | -0.787 |
| seasoned cohort | 16706 | 0 | 1106 | 15600 | -11.41 | -0.37 | -76.28 | -68.39 | 30.2 | -6.917 | -9.79 | -0.338 | -12.66 | -0.393 |
| later-listed cohort | 319 | 0 | 300 | 19 | 5.04 | 0.358 | -29.5 | 54.51 | 33.33 | -7.158 | 10.81 | 0.573 | 0.69 | 0.12 |
| causal liquidity >= Rs 25 cr | 5214 | 0 | 866 | 4348 | 6.6 | 0.43 | -33.73 | 83.59 | 35.33 | -5.344 | 5.92 | 0.432 | 7.14 | 0.434 |

**Stocks that were delisted, merged or suspended before today are absent from the data, and their effect is not measured. Survivorship bias from them is not sized here, so every figure in this report remains an upper bound in that respect.**

## 4. Periods

2016–2020 is in-sample. 2021 onwards was consulted while tuning `bo_close_frac` and the breadth gate, so it is **not a clean holdout**. Period figures are slices of the one full-period account; the 2021+ slice starts from the 2020 year-end equity.

Calendar-year returns (%):

| row | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | -13.21 | 62.79 | -7.54 | -16.47 | 66.04 | 151.15 | -11.62 | 21.18 | 19.25 | 4.77 | 8.55 |
| next_open | -11.95 | 43.97 | 3.39 | 1.82 | 25.44 | 60.56 | 3.41 | 46.9 | -7.44 | 5.27 | 6.02 |
| gap_exit | -20.33 | 66.09 | -32.29 | -10.67 | 15.75 | 97.15 | 12.1 | 40.51 | 32.52 | -16.89 | 2.64 |
| realistic | -18.48 | 60.91 | -38.46 | -17.27 | 12.18 | 17.55 | -32.9 | -12.55 | -22.72 | -33.03 | -11.89 |
| realistic (verdict) | -19.36 | 54.5 | -41.03 | -24.88 | 4.81 | 6.6 | -35.36 | -15.91 | -27.62 | -36.43 | 0.86 |
| realistic + breadth | -31.15 | 49.7 | -21.07 | -3.46 | 8.78 | 12.16 | -30.14 | 18.76 | -22.18 | -40.51 | -6.97 |

## 5. Data quality

Trades whose exit bar repeats the prior bar's volume exactly (a forward-filled, fabricated bar — intraday fills there use stale prices):

| scenario | trades | exit_on_ffill_bar |
|---|---|---|
| baseline | 15189 | 1 |
| next_open | 15396 | 1 |
| gap_exit | 16832 | 0 |
| realistic | 17025 | 2 |

## 6. Breadth gate

Informational only, not the verdict basis. With the breadth gate on (breadth from `analysis.compute_universe_breadth` over this universe), the realistic scenario at 0.15% slippage per side gives CAGR -10.66%, Sharpe -0.352, max DD -72.74% (2016–2020 CAGR -3.7%, 2021+ -15.78%).

## Disclosures

- **Delisted stocks unmeasured.** The universe is today's surviving stocks. Names delisted, merged or suspended earlier are absent; results are an upper bound.
- **Tuning-contaminated out-of-sample.** 2021 onwards informed parameter choices.
- **Data path.** The backtest uses the cached `data.py` series (adjusted prices); the live screener uses a different, unadjusted path. The verdict applies to the backtest data path only.
- **Breadth gate off.** Mirrors `main.py`, which passes no breadth series, although the parameters were tuned with the gate on.
- **Price-only benchmark.** The Nifty 50 series excludes dividends (~1–1.5%/yr), which flatters the strategy in the benchmark comparison.
- **Candidate ranking.** When more signals fire than the account can fund, `simulate_portfolio` picks alphabetically by ticker (no score), deterministically.
- **Same-bar SL/TP.** In intraday mode a bar spanning both levels is booked as SL.
