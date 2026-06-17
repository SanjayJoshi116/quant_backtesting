"""
core/scorecard.py — Per-stock per-signal historical performance scorecard.

Reads all results/trades_*.csv files built by the backtester and returns a
lookup table keyed by (ticker, signal_type).

Usage:
    from core.scorecard import load_scorecard
    sc = load_scorecard()
    row = sc.get(("WIPRO.NS", "PB-L"))   # {'n': 16, 'wr': 81.2, 'avg_pnl': +3.2, 'label': '...'}
"""

from __future__ import annotations

import glob
from pathlib import Path
from functools import lru_cache

import pandas as pd

_RESULTS = Path(__file__).parent.parent / "results"


def _confidence(n: int) -> str:
    """Human label for sample-size reliability."""
    if n >= 20:
        return "High confidence"
    if n >= 10:
        return "Moderate confidence"
    return "Small sample"


@lru_cache(maxsize=1)
def load_scorecard(results_dir: str | None = None) -> dict:
    """
    Build and cache the historical scorecard from all trade CSVs.

    Returns
    -------
    dict keyed by (ticker, signal_type) →
        {n, wr, avg_pnl, avg_win, avg_loss, profit_factor, confidence_label}
    """
    base = Path(results_dir) if results_dir else _RESULTS
    scorecard: dict = {}

    for csv_path in glob.glob(str(base / "trades_*.csv")):
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if df.empty or "signal_type" not in df.columns or "pnl_pct" not in df.columns:
            continue

        for (ticker, sig_type), grp in df.groupby(["ticker", "signal_type"]):
            pnl  = grp["pnl_pct"].values
            n    = len(pnl)
            wins = pnl[pnl > 0]
            loss = pnl[pnl <= 0]

            wr         = round(len(wins) / n * 100, 1) if n > 0 else 0.0
            avg_pnl    = round(float(pnl.mean()), 2)
            avg_win    = round(float(wins.mean()), 2) if len(wins) > 0 else 0.0
            avg_loss   = round(float(loss.mean()), 2) if len(loss) > 0 else 0.0
            gross_p    = wins.sum()
            gross_l    = abs(loss.sum())
            pf         = round(gross_p / gross_l, 2) if gross_l > 0 else 99.0

            scorecard[(ticker, sig_type)] = {
                "n":                n,
                "wr":               wr,
                "avg_pnl":          avg_pnl,
                "avg_win":          avg_win,
                "avg_loss":         avg_loss,
                "profit_factor":    pf,
                "confidence_label": _confidence(n),
            }

    return scorecard


def get_signal_stats(ticker: str, signal_type: str,
                     results_dir: str | None = None) -> dict | None:
    """Convenience wrapper — returns stats dict or None if no history."""
    return load_scorecard(results_dir).get((ticker, signal_type))
