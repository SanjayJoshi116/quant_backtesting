"""
Shared fixtures for the quant_backtest test suite.
"""

import sys
import os
import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path regardless of how pytest is invoked
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Synthetic OHLCV ───────────────────────────────────────────────────────────

def make_ohlcv(n: int = 420, seed: int = 42,
               drift: float = 0.0003) -> pd.DataFrame:
    """
    Generate n bars of synthetic OHLCV with a slight upward drift.
    420 bars ≈ enough warmup for EMA200 + weekly EMA50 (needs ~52 weeks).
    """
    rng    = np.random.default_rng(seed)
    close  = 100.0 * np.cumprod(1.0 + rng.normal(drift, 0.015, n))
    noise  = rng.uniform(0.002, 0.018, n)
    high   = close * (1.0 + noise)
    low    = close * (1.0 - noise)
    open_  = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.integers(500_000, 5_000_000, n).astype(float)
    dates  = pd.date_range("2018-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low,
         "Close": close, "Volume": volume},
        index=dates,
    )


@pytest.fixture(scope="session")
def ohlcv_df():
    """420-bar synthetic OHLCV DataFrame (upward-trending)."""
    return make_ohlcv(n=420, drift=0.0004)


@pytest.fixture(scope="session")
def ohlcv_df_short():
    """100-bar synthetic OHLCV — too short for signal detection."""
    return make_ohlcv(n=100)


@pytest.fixture(scope="session")
def sample_config():
    """Valid StrategyConfig loaded from the project's strategy.yaml."""
    from core.config import load_config
    return load_config()


@pytest.fixture(scope="session")
def cached_ticker_df():
    """
    Real cached OHLCV for RELIANCE.NS if available, else synthetic.
    Used for integration-style signal tests.
    """
    from core.data import fetch_or_load
    df = fetch_or_load("RELIANCE.NS")
    if df is not None and len(df) >= 260:
        return df
    return make_ohlcv(n=420)
