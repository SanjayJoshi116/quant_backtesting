"""
screener.py — Scan the watchlist for strategy signals and return alerts.

Data is loaded via core.data.fetch_or_load — shared cache with the backtester.
No direct yfinance calls here.
"""

import sys
import os
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bot.universe import WATCHLIST, NEGATIVE_EDGE, get_sector
from bot.signal_engine import detect
from core.data import fetch_or_load, _csv_path, _is_fresh
from core.logging import log_signal
from core.config import load_config
from core.scorecard import get_signal_stats
from core.pattern_scanner import scan_patterns
from core.fundamental_scorer import get_cached_quality

_NIFTY = "^NSEI"
_VIX   = "^INDIAVIX"

VIX_WARN = 16.0   # above this, flag signals as elevated cluster-risk


def _get_vix() -> float | None:
    """Return latest India VIX close, or None on failure."""
    try:
        df = fetch_or_load(_VIX)
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def _prefetch_parallel(tickers: list[str], verbose: bool = True) -> None:
    """Warm the disk cache for all stale tickers in parallel before scanning."""
    cfg = load_config()
    stale = [t for t in tickers if not _is_fresh(_csv_path(t), cfg.cache_ttl_hours)]
    if not stale:
        return
    n_workers = min(12, len(stale))
    if verbose:
        print(f"  Pre-fetching {len(stale)} tickers ({n_workers} parallel workers)...")
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        list(pool.map(fetch_or_load, stale))


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
             max_patterns:           int  = 30,
             progress_callback = None) -> dict:
    """
    progress_callback(current: int, total: int, ticker: str) -> None
    Called after each ticker is processed. Use for UI progress bars.
    """
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

    # Warm cache in parallel so the scan loop only hits disk
    _prefetch_parallel(watchlist, verbose=verbose)

    # Market regime check
    bull_regime = _market_regime()
    vix_level   = _get_vix()
    vix_warning = vix_level is not None and vix_level >= VIX_WARN
    if verbose:
        status = "BULL ✓" if bull_regime else "BEAR ⚠ — long signals flagged"
        print(f"  Market regime (Nifty vs EMA200): {status}")
        if vix_level is not None:
            vix_flag = " ⚠ ELEVATED — cluster-day risk" if vix_warning else " ✓ healthy"
            print(f"  India VIX: {vix_level:.1f}{vix_flag}")

    alerts:   list[dict] = []
    patterns: list[dict] = []
    failed:   list[str]  = []

    total    = len(watchlist)
    iterator = tqdm(watchlist, desc="Scanning", ncols=72) if verbose else watchlist

    for idx, ticker in enumerate(iterator):
        # Fire progress callback if provided (for dashboard progress bar)
        if progress_callback is not None:
            try:
                progress_callback(idx, total, ticker)
            except Exception:
                pass

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
            sig["vix_level"]   = vix_level
            sig["vix_warning"] = vix_warning
            hist = get_signal_stats(ticker, sig["signal_type"])
            sig["hist"]      = hist
            sig["signal_id"] = log_signal(sig)

            # ── Fundamental quality (from cache — no API call in hot path) ────
            qual = get_cached_quality(ticker)
            sig.update(qual)   # merges all qual_* keys into signal dict

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

    # Final callback to mark 100% complete
    if progress_callback is not None:
        try:
            progress_callback(total, total, "done")
        except Exception:
            pass

    # ── Fundamental auto-fetch for signaled tickers ───────────────────────────
    # After the hot-path scan, fetch fundamentals for any signaled ticker
    # that has no cache yet (UNKNOWN tier).  Only 5–20 stocks per day fire
    # signals, so this adds at most ~60 seconds — not felt by the user.
    # On subsequent runs the same stocks serve instantly from cache.
    try:
        from core.fundamental_scorer import get_quality, _is_fresh, _cache_path
        unknown_tickers = [
            s["ticker"] for s in alerts
            if s.get("qual_tier") == "UNKNOWN"
            or not _is_fresh(_cache_path(s["ticker"]))
        ]
        # Deduplicate
        seen = set()
        unique_unknown = [t for t in unknown_tickers
                          if not (t in seen or seen.add(t))]

        if unique_unknown:
            if verbose:
                print(f"  Fetching fundamentals for {len(unique_unknown)} new "
                      f"signal ticker(s): {', '.join(t.replace('.NS','') for t in unique_unknown)}")
            for ticker in unique_unknown:
                try:
                    q = get_quality(ticker, force=False)
                    # Update any alert dicts for this ticker with fresh data
                    for sig in alerts:
                        if sig["ticker"] == ticker:
                            sig.update(q)
                except Exception:
                    pass   # fundamental fetch failure never breaks the screener
    except Exception as e:
        if verbose:
            print(f"  [WARN] Fundamental auto-fetch: {e}")

    # ── Paper trading: auto-log new signals + update open positions ───────────
    paper_summary = {}
    try:
        from core.paper_trader import log_new_signals, update_open_positions
        new_count   = log_new_signals(alerts)
        paper_summary = update_open_positions()
        paper_summary["new_logged"] = new_count
        if verbose:
            print(f"  Paper trades: {new_count} new logged  |  "
                  f"{paper_summary.get('updated',0)} positions updated "
                  f"(TP:{paper_summary.get('tp_hit',0)} "
                  f"SL:{paper_summary.get('sl_hit',0)} "
                  f"EXP:{paper_summary.get('expired',0)}) "
                  f"| {paper_summary.get('still_open',0)} still open")
    except Exception as e:
        if verbose:
            print(f"  [WARN] Paper trader: {e}")

    if verbose:
        print(f"  Signals found: {len(alerts)}  |  Patterns found (top {max_patterns}): {len(patterns)}")

    return {"signals": alerts, "patterns": patterns, "paper": paper_summary}
