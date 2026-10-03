"""
Baseline fixture for the fill-model regression test (edge-reality-check 2.1).

The fixture is the v1.5 backtester's output (tests/legacy/backtester_v1_5.py,
byte-identical to backtester.py before the fill-model change) on a fixed set
of cached tickers. Together they cover longs, shorts, SL, TP and MeshBreak.
No cached ticker hits DATA_GAP naturally, so one extra case injects a NaN ATR
bar mid-trade.

Regenerate (only if the baseline itself must change):
    python -m tests.legacy.fill_baseline
"""

import os
import sys
import warnings

import numpy as np
import pandas as pd

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_PATH = os.path.join(BASE_DIR, "tests", "fixtures", "baseline_v1_5_trades.csv")

TICKERS = [
    "SUNPHARMA.NS", "KKCL.NS", "PNCINFRA.NS", "MUKANDLTD.NS", "ESCORTS.NS",
    "BALRAMCHIN.NS", "KOTAKBANK.NS", "PRAKASH.NS", "JYOTHYLAB.NS", "TBZ.NS",
]

# (case label, ticker, date whose ATR is set to NaN) — lands inside the
# 2018-02-01 → 2018-03-19 ESCORTS long, forcing a DATA_GAP exit.
GAP_CASES = [("ESCORTS.NS#gap", "ESCORTS.NS", "2018-02-15")]


def cases_available() -> bool:
    """True when every fixture ticker plus Nifty is in the local cache."""
    from data import RAW_DIR, NIFTY_TICKER, _safe_name
    return all(os.path.exists(os.path.join(RAW_DIR, f"{_safe_name(t)}.csv"))
               for t in TICKERS + [NIFTY_TICKER])


def prepare_cases() -> tuple[dict[str, pd.DataFrame], "pd.Series | None"]:
    """Indicator frames per case label, and the Nifty regime series as main.py builds it."""
    from data import load_data, NIFTY_TICKER
    from indicators import prepare_indicators

    frames = {t: prepare_indicators(load_data(t)) for t in TICKERS}
    for label, ticker, date in GAP_CASES:
        df = frames[ticker].copy()
        df.loc[pd.Timestamp(date), "ATR"] = np.nan
        frames[label] = df

    nifty  = prepare_indicators(load_data(NIFTY_TICKER))
    regime = nifty["Close"] > nifty["EMA200"]
    return frames, regime


def run_cases(run_backtest, **kwargs) -> pd.DataFrame:
    """Run `run_backtest` over every case; one trade frame with a `case` column."""
    frames, regime = prepare_cases()
    parts = []
    for label, df in frames.items():
        ticker = label.split("#")[0]
        tr = pd.DataFrame(run_backtest(df, ticker=ticker, market_regime=regime, **kwargs))
        tr.insert(0, "case", label)
        parts.append(tr)
    return pd.concat(parts, ignore_index=True)


if __name__ == "__main__":
    sys.path.insert(0, BASE_DIR)
    warnings.filterwarnings("ignore")
    from tests.legacy.backtester_v1_5 import run_backtest as run_v1_5

    out = run_cases(run_v1_5)
    os.makedirs(os.path.dirname(FIXTURE_PATH), exist_ok=True)
    out.to_csv(FIXTURE_PATH, index=False)
    print(f"{len(out)} trades -> {FIXTURE_PATH}")
    print(out.groupby(["direction", "exit_reason"]).size().to_string())
