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
from core.config import load_config
from core.scorecard import get_signal_stats

_NIFTY = "^NSEI"


def _market_regime() -> bool:
    """
    Return True (bull) if Nifty50 is above its EMA200 on the latest bar.
    Returns True on any error so screener degrades gracefully.
    """
    try:
        cfg = load_config()
        if not cfg.regime_enabled:
            return True
        from indicators import prepare_indicators
        df = fetch_or_load(_NIFTY)
        if df is None or len(df) < cfg.nifty_ema_period + 10:
            return True
        ind = prepare_indicators(df)
        return bool(ind["Close"].iloc[-1] > ind["EMA200"].iloc[-1])
    except Exception:
        return True


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

    # Check market regime once before scanning the entire universe
    bull_regime = _market_regime()
    if verbose:
        status = "BULL ✓" if bull_regime else "BEAR ⚠ — long signals flagged"
        print(f"  Market regime (Nifty vs EMA200): {status}")

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
            sig["negative_edge"]       = (ticker in NEGATIVE_EDGE)
            sig["sector"]              = get_sector(ticker)
            sig["bear_regime_warning"] = (
                not bull_regime and sig["direction"] == "LONG"
            )
            # Historical scorecard for this ticker + signal type
            hist = get_signal_stats(ticker, sig["signal_type"])
            sig["hist"] = hist   # None if no history yet
            sig["signal_id"] = log_signal(sig)
            alerts.append(sig)

    if failed and verbose:
        print(f"\n  Could not process: {', '.join(failed)}")

    # Sort: high score first; within same score, longs before shorts
    alerts.sort(key=lambda s: (-s["score"], s["direction"]))
    return alerts
