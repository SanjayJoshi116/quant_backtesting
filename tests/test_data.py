"""
Tests for core/data.py — cache hit/miss, fetch logging, staleness.
"""

import csv
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core.data import fetch_or_load, _is_fresh, _csv_path, _clean, _hash

_LOGS = Path(__file__).parent.parent / "logs"
_FLOG = _LOGS / "fetch_log.csv"


# ── _is_fresh ─────────────────────────────────────────────────────────────────

def test_is_fresh_missing_file(tmp_path):
    assert _is_fresh(tmp_path / "nonexistent.csv", ttl_hours=24) is False


def test_is_fresh_new_file(tmp_path):
    p = tmp_path / "test.csv"
    p.write_text("data")
    assert _is_fresh(p, ttl_hours=24) is True


def test_is_fresh_old_file(tmp_path):
    p = tmp_path / "test.csv"
    p.write_text("data")
    # Mock mtime to 48 hours ago
    old_mtime = time.time() - 48 * 3600
    import os
    os.utime(p, (old_mtime, old_mtime))
    assert _is_fresh(p, ttl_hours=24) is False


# ── _clean ────────────────────────────────────────────────────────────────────

def test_clean_returns_none_for_empty(ohlcv_df):
    assert _clean(pd.DataFrame(), min_bars=260) is None


def test_clean_returns_none_for_insufficient_bars(ohlcv_df_short):
    result = _clean(ohlcv_df_short.copy(), min_bars=300)
    assert result is None


def test_clean_valid_df_returns_dataframe(ohlcv_df):
    result = _clean(ohlcv_df.copy(), min_bars=100)
    assert result is not None
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_clean_drops_nonpositive_close(ohlcv_df):
    df = ohlcv_df.copy()
    df.iloc[5, df.columns.get_loc("Close")] = 0.0
    df.iloc[6, df.columns.get_loc("Close")] = -1.0
    result = _clean(df, min_bars=100)
    assert (result["Close"] > 0).all()


def test_clean_flattens_multiindex(ohlcv_df):
    df = ohlcv_df.copy()
    df.columns = pd.MultiIndex.from_tuples([(c, "TICKER") for c in df.columns])
    result = _clean(df, min_bars=100)
    assert result is not None
    assert isinstance(result.columns, pd.Index)


# ── _hash ─────────────────────────────────────────────────────────────────────

def test_hash_is_deterministic(ohlcv_df):
    assert _hash(ohlcv_df) == _hash(ohlcv_df)


def test_hash_differs_for_different_data(ohlcv_df):
    df2 = ohlcv_df.copy()
    df2.iloc[0, 0] += 999
    assert _hash(ohlcv_df) != _hash(df2)


def test_hash_length():
    import pandas as pd
    df = pd.DataFrame({"Close": [1.0, 2.0]})
    h = _hash(df)
    assert len(h) == 8


# ── fetch_or_load with cached ticker ─────────────────────────────────────────

def test_fetch_or_load_cached_ticker_returns_df(cached_ticker_df):
    """Real cached data (RELIANCE.NS or synthetic fallback) loads cleanly."""
    assert cached_ticker_df is not None
    assert len(cached_ticker_df) >= 260
    assert "Close" in cached_ticker_df.columns


def test_fetch_or_load_writes_fetch_log():
    """Every call to fetch_or_load must append a row to fetch_log.csv."""
    rows_before = 0
    if _FLOG.exists():
        with open(_FLOG) as f:
            rows_before = sum(1 for _ in f) - 1  # subtract header

    fetch_or_load("RELIANCE.NS")

    assert _FLOG.exists()
    with open(_FLOG) as f:
        rows_after = sum(1 for _ in f) - 1
    assert rows_after == rows_before + 1


def test_fetch_log_schema():
    """fetch_log.csv must have the correct column headers."""
    assert _FLOG.exists(), "fetch_log.csv must exist after fetch_or_load calls"
    with open(_FLOG) as f:
        reader = csv.DictReader(f)
        assert set(reader.fieldnames) == {
            "timestamp", "ticker", "source", "rows", "cache_hit", "data_hash"
        }


def test_fetch_or_load_returns_none_for_invalid_ticker():
    """A non-existent ticker should return None gracefully."""
    result = fetch_or_load("THISDOESNOTEXIST_XYZ.NS")
    assert result is None


def test_fetch_or_load_cache_hit_skips_yfinance(tmp_path, ohlcv_df):
    """When cache is fresh, yfinance must NOT be called."""
    ticker = "TEST.NS"
    cache_file = _csv_path(ticker)

    # Write fresh cache
    ohlcv_df.to_csv(cache_file)

    with patch("core.data.yf.download") as mock_dl:
        result = fetch_or_load(ticker)
        mock_dl.assert_not_called()

    assert result is not None
    # Clean up
    cache_file.unlink(missing_ok=True)
