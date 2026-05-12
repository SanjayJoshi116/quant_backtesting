"""
core/data.py — Unified data fetch and cache layer.

    fetch_or_load(ticker, force=False) -> pd.DataFrame | None

- Returns cached CSV if it exists and is younger than cache_ttl_hours
- Otherwise fetches from yfinance and saves to data/raw/
- Every access (hit or miss) appended to logs/fetch_log.csv for audit trail
"""

from __future__ import annotations

import csv
import hashlib
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from core.config import load_config

warnings.filterwarnings("ignore")

_BASE   = Path(__file__).parent.parent
_RAW    = _BASE / "data" / "screener"   # screener-only cache — never overwrites backtest data
_LOGS   = _BASE / "logs"
_FLOG   = _LOGS / "fetch_log.csv"

_LOG_COLS = ["timestamp", "ticker", "source", "rows", "cache_hit", "data_hash"]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    _RAW.mkdir(parents=True, exist_ok=True)
    _LOGS.mkdir(parents=True, exist_ok=True)


def _safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace(".", "_")


def _csv_path(ticker: str) -> Path:
    return _RAW / f"{_safe_name(ticker)}.csv"


def _last_nse_close() -> datetime:
    """
    Return the datetime of the most recent completed NSE session (15:30 IST).
    Skips weekends — if today is Saturday/Sunday returns Friday's close.
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST)

    # Build today's close time in IST
    close_today = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)

    # If market hasn't closed yet today → last close was yesterday (or earlier)
    ref = close_today if now_ist >= close_today else close_today - timedelta(days=1)

    # Roll back past weekends (Saturday=5, Sunday=6)
    while ref.weekday() >= 5:
        ref -= timedelta(days=1)

    return ref


def _is_fresh(path: Path, ttl_hours: int) -> bool:
    """
    Market-aware freshness check.
    A cached file is stale if the last NSE session closed AFTER it was written.
    This guarantees re-fetch once per trading day after market close (15:30 IST).
    """
    if not path.exists():
        return False

    mtime = datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=timezone(timedelta(hours=5, minutes=30))   # compare in IST
    )
    last_close = _last_nse_close()

    # Stale if the file was written before the last completed session
    if mtime < last_close:
        return False

    # Within the same session: also apply TTL as a safety net
    age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
    return age_h < ttl_hours


def _hash(df: pd.DataFrame) -> str:
    return hashlib.md5(
        pd.util.hash_pandas_object(df, index=True).values
    ).hexdigest()[:8]


def _log(ticker: str, source: str, rows: int,
         cache_hit: bool, data_hash: str) -> None:
    _ensure_dirs()
    new_file = not _FLOG.exists()
    with open(_FLOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_LOG_COLS)
        if new_file:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "ticker":    ticker,
            "source":    source,
            "rows":      rows,
            "cache_hit": cache_hit,
            "data_hash": data_hash,
        })


def _clean(raw: pd.DataFrame, min_bars: int) -> pd.DataFrame | None:
    """Normalise a raw yfinance DataFrame. Returns None if unusable."""
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in raw.columns for c in needed):
        return None
    df = raw[needed].copy()
    df.ffill(inplace=True)
    df.dropna(inplace=True)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"
    df = df[~df.index.duplicated(keep="last")]   # drop duplicate dates
    df = df[df["Close"] > 0]
    if len(df) < min_bars:
        return None
    return df


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_or_load(ticker: str, force: bool = False) -> pd.DataFrame | None:
    """
    Return OHLCV DataFrame for ticker, using cache when fresh.

    Parameters
    ----------
    ticker : NSE ticker symbol (e.g. "RELIANCE.NS")
    force  : bypass cache and always re-fetch from yfinance

    Returns
    -------
    Cleaned DataFrame with DatetimeIndex, or None if data unavailable.
    """
    cfg  = load_config()
    path = _csv_path(ticker)
    _ensure_dirs()

    # ── Cache hit ─────────────────────────────────────────────────────────────
    if not force and _is_fresh(path, cfg.cache_ttl_hours):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        _log(ticker, "cache", len(df), cache_hit=True, data_hash=_hash(df))
        return df

    # ── Fetch from yfinance ───────────────────────────────────────────────────
    try:
        raw = yf.download(
            ticker,
            period=cfg.data_period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            actions=False,
        )
    except Exception as exc:
        print(f"  [ERROR] {ticker}: {exc}")
        _log(ticker, "yfinance", 0, cache_hit=False, data_hash="")
        return None

    df = _clean(raw, cfg.min_bars)
    if df is None:
        print(f"  [SKIP]  {ticker}: insufficient data after cleaning")
        _log(ticker, "yfinance", 0, cache_hit=False, data_hash="")
        return None

    df.to_csv(path)
    h = _hash(df)
    _log(ticker, "yfinance", len(df), cache_hit=False, data_hash=h)
    return df
