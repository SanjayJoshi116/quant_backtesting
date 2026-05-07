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
from core.pattern_scanner import scan_patterns

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


def run_scan(watchlist: list[str] = None,
             verbose:   bool       = True,
             min_pattern_confidence: str  = "HIGH",
             max_patterns:           int  = 30) -> dict:
    """
    Scan every ticker in watchlist for both technical signals and chart patterns.

    Returns
    -------
    dict with keys:
      'signals'  : list of signal dicts (EMA/RSI/ADX triggered)
      'patterns' : list of pattern dicts (chart patterns forming)
    """
    if watchlist is None:
        watchlist = WATCHLIST

    # Market regime check
    bull_regime = _market_regime()
    if verbose:
        status = "BULL ✓" if bull_regime else "BEAR ⚠ — long signals flagged"
        print(f"  Market regime (Nifty vs EMA200): {status}")

    alerts:   list[dict] = []
    patterns: list[dict] = []
    failed:   list[str]  = []

    iterator = tqdm(watchlist, desc="Scanning", ncols=72) if verbose else watchlist

    for ticker in iterator:
        df = fetch_or_load(ticker)
        if df is None:
            failed.append(ticker)
            continue

        # ── Compute indicators once, reuse for both signals and patterns ─────
        try:
            from indicators import prepare_indicators
            ind = prepare_indicators(df)
        except Exception as e:
            print(f"  [ERR]   {ticker}: indicator error — {e}")
            failed.append(ticker)
            continue

        # ── Technical signals ─────────────────────────────────────────────────
        try:
            signals = detect(ind, ticker)   # detect() accepts pre-computed df
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
            hist = get_signal_stats(ticker, sig["signal_type"])
            sig["hist"]      = hist
            sig["signal_id"] = log_signal(sig)
            alerts.append(sig)

        # ── Chart patterns: scan ALL stocks, rank later ───────────────────────
        # DO NOT cap here — stopping early means stocks late in the list
        # are never checked. Collect everything, rank by quality, cap at end.
        try:
            found = scan_patterns(ind)
            for pat in found:
                if min_pattern_confidence == "HIGH" and pat["confidence"] != "HIGH":
                    continue
                pat["ticker"]       = ticker
                pat["sector"]       = get_sector(ticker)
                # Quality score for ranking: breakout > watch; more bars > fewer
                pat["_quality"] = (
                    3 if pat.get("breaking_out") else 1
                ) + (
                    2 if pat["confidence"] == "HIGH" else 0
                ) + min(pat.get("bars_forming", pat.get("pennant_bars",
                        pat.get("flag_bars", pat.get("cup_bars", 5)))) / 20, 2)
                patterns.append(pat)
        except Exception:
            pass

    if failed and verbose:
        print(f"\n  Could not process: {', '.join(failed)}")
        print(f"  Signals found: {len(alerts)}  |  Patterns found: {len(patterns)}")

    alerts.sort(key=lambda s: (-s["score"], s["direction"]))

    # Rank ALL collected patterns by quality score, then cap for email
    patterns.sort(key=lambda p: -p.get("_quality", 0))
    # Clean internal score before returning
    for p in patterns:
        p.pop("_quality", None)
    patterns = patterns[:max_patterns]

    if verbose:
        print(f"  Signals found: {len(alerts)}  |  Patterns found (top {max_patterns}): {len(patterns)}")

    return {"signals": alerts, "patterns": patterns}
