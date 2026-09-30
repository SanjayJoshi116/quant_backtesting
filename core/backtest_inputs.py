"""
core/backtest_inputs.py

Input preparation shared by main.py and research tools, so that every per-ticker
backtest is fed identical frames: the cached CSV exactly as data.load_data reads
it, indicators from prepare_indicators, and the Nifty regime series built the
way main.py builds it (None when regime_enabled is false).

Cache only — nothing here touches the network.
"""

from __future__ import annotations

import warnings

import pandas as pd

from core.config import load_config


def load_prepared(ticker: str) -> pd.DataFrame | None:
    """Cached OHLCV for `ticker` with indicators. None if uncached or unpreparable."""
    from data import load_data
    from indicators import prepare_indicators

    raw = load_data(ticker)
    if raw is None or raw.empty:
        return None
    try:
        return prepare_indicators(raw)
    except Exception as e:
        warnings.warn(f"{ticker}: indicator error — {e}")
        return None


def build_regime(nifty_raw: pd.DataFrame | None
                 ) -> tuple[pd.DataFrame | None, pd.Series | None]:
    """
    (nifty_ind, regime) from raw Nifty OHLCV.

    regime is the bull flag (Close > EMA200) when `regime_enabled` is set in
    config, else None — the same series main.py passes to run_backtest.
    """
    if nifty_raw is None:
        return None, None
    try:
        from indicators import prepare_indicators
        nifty_ind = prepare_indicators(nifty_raw)
    except Exception as e:
        warnings.warn(f"Nifty indicator error — regime filter unavailable: {e}")
        return None, None
    if not load_config().regime_enabled:
        return nifty_ind, None
    return nifty_ind, nifty_ind["Close"] > nifty_ind["EMA200"]
