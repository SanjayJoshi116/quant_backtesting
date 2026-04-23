"""
screener.py — Scan the watchlist for strategy signals and return alerts.

Data is loaded via core.data.fetch_or_load — shared cache with the backtester.
No direct yfinance calls here.
"""

import sys
import os
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bot.universe import WATCHLIST, NEGATIVE_EDGE, get_sector
from bot.signal_engine import detect
from core.data import fetch_or_load
from core.logging import log_signal


def run_scan(watchlist: list[str] = None, verbose: bool = True) -> list[dict]:
    """
    Scan every ticker in watchlist.

    Parameters
    ----------
    watchlist : list of tickers (defaults to universe.WATCHLIST)
    verbose   : print progress bar

    Returns
    -------
    List of signal dicts sorted by signal score descending.
    Each dict also carries a 'negative_edge' bool flag.
    """
    if watchlist is None:
        watchlist = WATCHLIST

    alerts: list[dict] = []
    failed: list[str]  = []

    iterator = tqdm(watchlist, desc="Scanning", ncols=72) if verbose else watchlist

    for ticker in iterator:
        df = fetch_or_load(ticker)
        if df is None:
            failed.append(ticker)
            continue

        try:
            signals = detect(df, ticker)
        except Exception as e:
            print(f"  [ERR]   {ticker}: signal engine failed — {e}")
            failed.append(ticker)
            continue

        for sig in signals:
            sig["negative_edge"] = (ticker in NEGATIVE_EDGE)
            sig["sector"] = get_sector(ticker)
            sig["signal_id"] = log_signal(sig)
            alerts.append(sig)

    if failed and verbose:
        print(f"\n  Could not process: {', '.join(failed)}")

    # Sort: high score first; within same score, longs before shorts
    alerts.sort(key=lambda s: (-s["score"], s["direction"]))
    return alerts
