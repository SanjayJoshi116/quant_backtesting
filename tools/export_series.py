"""
tools/export_series.py

Export a short daily price series with indicators for a handful of well-known
tickers, so the education pages can show ANNOTATED REAL CHARTS rather than
abstract distributions.

A histogram of RSI values only means something to someone who already knows what
RSI is. A beginner needs to see a price line, the indicator underneath it, and a
marker saying "this is the moment being described". That requires the actual
series, not a summary statistic.

Output: public/data/series.json
    { generated_at, tickers: { TCS: { dates[], close[], ema21[], ema50[],
                                      ema200[], rsi[], adx[], vol_ratio[] } } }

Usage:
    python tools/export_series.py --days 180
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from indicators import prepare_indicators

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "data" / "series.json"

# Large, liquid, widely recognised names. Chosen for recognisability, not for
# how flattering their charts look -- whatever the data shows is what ships.
TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS",
           "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "ITC.NS"]

CACHE_DIRS = (ROOT / "data" / "screener", ROOT / "data" / "raw")


def _safe(t: str) -> str:
    return t.replace("^", "IDX_").replace(".", "_")


def load(ticker: str, no_fetch: bool) -> pd.DataFrame | None:
    if not no_fetch:
        from core.data import fetch_or_load
        try:
            return fetch_or_load(ticker)
        except Exception as e:
            warnings.warn(f"{ticker}: fetch failed: {e}")
    for d in CACHE_DIRS:
        p = d / f"{_safe(ticker)}.csv"
        if p.exists():
            try:
                return pd.read_csv(p, index_col=0, parse_dates=True)
            except Exception as e:
                warnings.warn(f"{ticker}: cache read failed: {e}")
    return None


def r(series, nd=2):
    """Round, emitting null for anything not finite. Never fabricates a value."""
    out = []
    for v in series:
        try:
            f = float(v)
            out.append(round(f, nd) if np.isfinite(f) else None)
        except (TypeError, ValueError):
            out.append(None)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    payload = {}
    for tk in TICKERS:
        raw = load(tk, args.no_fetch)
        if raw is None or len(raw) < 300:
            print(f"  skip {tk}: insufficient data")
            continue
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        ind = prepare_indicators(raw).tail(args.days)
        payload[tk.replace(".NS", "")] = {
            "dates":     [str(d.date()) for d in ind.index],
            "close":     r(ind["Close"]),
            "ema21":     r(ind["EMA21"]),
            "ema50":     r(ind["EMA50"]),
            "ema200":    r(ind["EMA200"]),
            "rsi":       r(ind["RSI"], 1),
            "adx":       r(ind["ADX"], 1),
            "vol_ratio": r(ind["Volume"] / ind["VOL_SMA20"]),
        }
        print(f"  {tk:14} {len(ind)} bars  {ind.index[0].date()} -> {ind.index[-1].date()}")

    if not payload:
        print("Nothing exported.")
        return

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "days": args.days, "tickers": payload},
                  fh, separators=(",", ":"))
    print(f"\n  wrote {out}  ({out.stat().st_size/1024:.0f} KB, {len(payload)} tickers)")


if __name__ == "__main__":
    main()
