"""
tools/export_snapshot.py

Export a daily technical snapshot of the NSE universe as JSON, for a static site
to filter client-side.

WHAT THIS IS
------------
A factual scorecard: for each stock, the current value of a handful of standard,
publicly-defined indicators, plus which of a set of PUBLISHED conditions those
values satisfy. It is deliberately NOT the trading strategy's signal output --
there are no entry, stop-loss or target prices here, and no proprietary score.

WHY THE THRESHOLDS ARE NOT READ FROM strategy.yaml
--------------------------------------------------
CLAUDE.md says never to hardcode strategy parameters in Python. These are not
strategy parameters. They are PUBLICATION defaults for an educational tool, kept
deliberately separate from the tuned values in config/strategy.yaml so that:
  1. the tuned parameter set stays private, and
  2. the published conditions are round, standard, textbook values a reader can
     verify anywhere, rather than the output of an optimisation.
The site lets the visitor change every threshold client-side, so these are
starting values, not rules.

DATA INTEGRITY
--------------
Nothing is invented. A value that cannot be computed is emitted as null so the
site can render "Data unavailable". A condition whose inputs are unknown counts
as NOT met rather than being guessed. Every row carries the date of the last bar
used, so a stale ticker is visible instead of silently passing as current.

Usage
-----
    python tools/export_snapshot.py --top 200            # 200 most liquid
    python tools/export_snapshot.py --all                # whole universe
    python tools/export_snapshot.py --top 50 --no-fetch  # cache only, for dev
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

from bot.universe import WATCHLIST, get_sector
from core.config import load_config
from indicators import prepare_indicators

ROOT = Path(__file__).resolve().parent.parent
OUT_DEFAULT = ROOT / "public" / "data" / "snapshot.json"

# ── Published conditions ──────────────────────────────────────────────────────
# Standard textbook values, displayed on the site and editable by the visitor.
# Each carries the plain-English explanation the page renders beside it.
RSI_LO, RSI_HI = 35.0, 70.0
ADX_MIN        = 18.0
VOL_MULT       = 1.0
PCT_52WH       = -25.0

CONDITIONS = [
    {"key": "above_200dma",
     "label": "Trading above its 200-day moving average",
     "why": "A widely used long-term trend reference. Price above it is "
            "conventionally read as a longer-term uptrend."},
    {"key": "ema21_above_50",
     "label": "21-day EMA above 50-day EMA",
     "why": "A shorter average above a longer one indicates recent momentum is "
            "stronger than the medium-term average."},
    {"key": "rsi_in_band",
     "label": f"RSI(14) between {RSI_LO:.0f} and {RSI_HI:.0f}",
     "why": "RSI below 30-35 is conventionally described as oversold and above "
            "70 as overbought. This band excludes both extremes."},
    {"key": "adx_trending",
     "label": f"ADX(14) at or above {ADX_MIN:.0f}",
     "why": "ADX measures trend strength regardless of direction. Low readings "
            "describe a sideways market rather than a trending one."},
    {"key": "volume_above_avg",
     "label": "Volume at or above its 20-day average",
     "why": "Higher-than-average volume means more participation than usual in "
            "that session."},
    {"key": "near_52w_high",
     "label": f"Within {abs(PCT_52WH):.0f}% of its 52-week high",
     "why": "Distance from the yearly high is one way of describing where the "
            "current price sits within its recent range."},
]

FIELDS = ["ticker", "sector", "close", "chg_pct", "rsi", "adx",
          "ema21", "ema50", "ema200", "vol_ratio", "atr_pct",
          "pct_from_52wh", "turnover_cr", "met", "bar_date"]


def _num(v, nd=2):
    """Round for output, or None when not a finite number. Never invents a value."""
    try:
        x = float(v)
        return round(x, nd) if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace(".", "_")


# core/data.py caches to data/screener (and the CI workflow restores that path).
# data/raw is the separate backtest cache, present only on a dev machine.
CACHE_DIRS = (ROOT / "data" / "screener", ROOT / "data" / "raw")


def load_raw(ticker: str, no_fetch: bool) -> pd.DataFrame | None:
    """Cache-only read, or the sanctioned core.data path when fetching is allowed."""
    if no_fetch:
        for d in CACHE_DIRS:
            p = d / f"{_safe_name(ticker)}.csv"
            if p.exists():
                try:
                    return pd.read_csv(p, index_col=0, parse_dates=True)
                except Exception as e:
                    warnings.warn(f"{ticker}: cache read failed ({p.parent.name}): {e}")
        return None
    from core.data import fetch_or_load
    try:
        return fetch_or_load(ticker)
    except Exception as e:
        warnings.warn(f"{ticker}: fetch failed: {e}")
        return None


def build_row(ticker: str, raw: pd.DataFrame) -> dict | None:
    """Compute one stock's row, or None when history is too short to be meaningful."""
    if raw is None or len(raw) < 250:
        return None
    try:
        ind = prepare_indicators(raw)
    except Exception as e:
        warnings.warn(f"{ticker}: indicator computation failed: {e}")
        return None

    bar = ind.iloc[-1]
    close = _num(bar.get("Close"))
    if close is None:
        return None

    prev  = _num(ind["Close"].iloc[-2]) if len(ind) > 1 else None
    hi52  = _num(ind["High"].iloc[-252:].max())
    vol   = _num(bar.get("Volume"), 0)
    vsma  = _num(bar.get("VOL_SMA20"), 0)
    atr   = _num(bar.get("ATR"))
    turn  = _num((ind["Close"] * ind["Volume"]).iloc[-60:].median() / 1e7)

    row = {
        "ticker":        ticker.replace(".NS", ""),
        "sector":        get_sector(ticker),
        "close":         close,
        "chg_pct":       _num((close / prev - 1) * 100) if prev else None,
        "rsi":           _num(bar.get("RSI"), 1),
        "adx":           _num(bar.get("ADX"), 1),
        "ema21":         _num(bar.get("EMA21")),
        "ema50":         _num(bar.get("EMA50")),
        "ema200":        _num(bar.get("EMA200")),
        "vol_ratio":     _num(vol / vsma) if (vol and vsma) else None,
        "atr_pct":       _num(atr / close * 100) if atr else None,
        "pct_from_52wh": _num((close / hi52 - 1) * 100) if hi52 else None,
        "turnover_cr":   turn,
        "bar_date":      str(pd.Timestamp(ind.index[-1]).date()),
    }

    # An unknown input yields None, which is NOT counted as satisfied.
    e21, e50, e200 = row["ema21"], row["ema50"], row["ema200"]
    cond = {
        "above_200dma":    (close > e200) if e200 else None,
        "ema21_above_50":  (e21 > e50) if (e21 and e50) else None,
        "rsi_in_band":     (RSI_LO <= row["rsi"] <= RSI_HI)
                           if row["rsi"] is not None else None,
        "adx_trending":    (row["adx"] >= ADX_MIN)
                           if row["adx"] is not None else None,
        "volume_above_avg": (row["vol_ratio"] >= VOL_MULT)
                           if row["vol_ratio"] is not None else None,
        "near_52w_high":   (row["pct_from_52wh"] >= PCT_52WH)
                           if row["pct_from_52wh"] is not None else None,
    }
    row["conditions"] = cond
    row["met"] = sum(1 for v in cond.values() if v is True)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("--top", type=int, default=200,
                    help="publish the N most liquid stocks (60-day median turnover)")
    ap.add_argument("--all", action="store_true", help="publish the whole universe")
    ap.add_argument("--limit", type=int, default=0,
                    help="only scan the first N tickers (development)")
    ap.add_argument("--no-fetch", action="store_true",
                    help="use the local cache only, never hit the network")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()

    tickers = WATCHLIST[: args.limit] if args.limit else WATCHLIST
    mode = "cache only" if args.no_fetch else "cache + fetch"
    print(f"Scanning {len(tickers)} tickers ({mode})...", flush=True)

    rows = []
    skipped = {"no_data": 0, "short_history": 0}
    for i, tk in enumerate(tickers, 1):
        if i % 250 == 0:
            print(f"  {i}/{len(tickers)}   kept {len(rows)}", flush=True)
        raw = load_raw(tk, args.no_fetch)
        if raw is None or raw.empty:
            skipped["no_data"] += 1
            continue
        try:
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
        except Exception:
            skipped["no_data"] += 1
            continue
        row = build_row(tk, raw)
        if row is None:
            skipped["short_history"] += 1
            continue
        rows.append(row)

    if not rows:
        print("No rows produced — nothing written.")
        return

    rows.sort(key=lambda r: (r["turnover_cr"] or 0), reverse=True)
    kept = rows if args.all else rows[: args.top]

    cfg = load_config()
    payload = {
        "generated_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_scanned": len(tickers),
        "rows_computed":  len(rows),
        "rows_published": len(kept),
        "selection":      "entire universe" if args.all
                          else f"top {args.top} by 60-day median turnover",
        "indicator_config_version": cfg.config_version,
        "conditions":     CONDITIONS,
        "thresholds":     {"rsi_lo": RSI_LO, "rsi_hi": RSI_HI, "adx_min": ADX_MIN,
                           "vol_mult": VOL_MULT, "pct_from_52wh": PCT_52WH},
        "fields":         FIELDS,
        "stocks":         [{**{k: r[k] for k in FIELDS},
                            "conditions": r["conditions"]} for r in kept],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)

    dates = pd.Series([r["bar_date"] for r in kept])
    met   = pd.Series([r["met"] for r in kept])
    print(f"\n  wrote {out}   ({out.stat().st_size / 1024:.0f} KB raw)")
    print(f"  computed {len(rows)} / {len(tickers)}    published {len(kept)}")
    print(f"  skipped {skipped}")
    print(f"  bar dates {dates.min()} -> {dates.max()}   "
          f"(newest bar on {int((dates == dates.max()).sum())} of {len(kept)} rows)")
    print(f"  conditions met: {met.value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
