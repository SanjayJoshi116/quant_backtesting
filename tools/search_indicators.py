"""
tools/search_indicators.py

Step 2: search the parameters that were never searched.

The optimiser has only ever tuned sl_mult / tp_mult / RSI bands / ADX. The
constants that actually define the strategy live in indicators.py and have never
been tested at any other value:

    hh_window      12   -> governs BO-L, which is 74% of all trades
    bo_close_frac  0.96 -> gates every breakout candle
    atr_window     14   -> sets stop distance, target distance AND position size
    ema_fast/slow  21/50 -> the entire bull_trend definition

Scored on the portfolio objective (Rs 1,00,000, 15 positions, >= Rs 25 cr/day,
0.20% costs), with the multiple-testing noise floor reported.

    python tools/search_indicators.py            # cheap pass (hh x bo_close)
    python tools/search_indicators.py --full     # also ATR / EMA (slower)
"""

from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from data import TICKERS
from indicators import patch_indicators, prepare_indicators
from core.config import load_config
import optimization as O

ROOT = Path(__file__).resolve().parent.parent


def load_universe() -> dict:
    ind = {}
    for tk in TICKERS:
        f = ROOT / "data/raw" / f"{tk.replace('^','IDX_').replace('.','_')}.csv"
        if not f.exists():
            continue
        try:
            raw = pd.read_csv(f, index_col=0, parse_dates=True)
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
            if len(raw) >= 300:
                ind[tk] = raw
        except Exception:
            pass
    return ind


def score(ind_dfs: dict, label: str) -> dict:
    base = load_config().to_params_dict()
    r = O._run_combo(ind_dfs, base, "2016-01-01", "2026-12-31")
    print(f"  {label:<34} signals={r['n_trades']:6d} funded={r['n_taken']:5d}  "
          f"CAGR {r['cagr']:6.2f}%  Sharpe {r['sharpe']:5.2f}  "
          f"maxDD {r.get('max_dd', 0):6.1f}%", flush=True)
    return r


def main() -> None:
    full = "--full" in sys.argv
    t0 = time.time()
    raws = load_universe()
    print(f"{len(raws)} tickers loaded [{time.time()-t0:.0f}s]", flush=True)

    print("\n  Building baseline indicators (defaults)...", flush=True)
    base_ind = {tk: prepare_indicators(df) for tk, df in raws.items()}
    print(f"  done [{time.time()-t0:.0f}s]\n", flush=True)

    results = []

    # ── Pass 1: cheap params — patched, no full rebuild ──────────────────────
    print("  PASS 1  hh_window x bo_close_frac   (patched, ~2s per combo)")
    print("  " + "-" * 84)
    for hh, bo in itertools.product([8, 12, 16, 20], [0.93, 0.96, 0.99]):
        ind = {tk: patch_indicators(d, hh_window=hh, bo_close_frac=bo)
               for tk, d in base_ind.items()}
        r = score(ind, f"hh={hh:<3} bo_close={bo}")
        results.append((f"hh={hh},bo={bo}", r["sharpe"], r["cagr"]))
        del ind

    # ── Pass 2: expensive params — full rebuild per value ────────────────────
    if full:
        print("\n  PASS 2  atr_window   (full rebuild, ~60s per value)")
        print("  " + "-" * 84)
        for aw in (10, 14, 21):
            ind = {tk: prepare_indicators(df, atr_window=aw) for tk, df in raws.items()}
            r = score(ind, f"atr_window={aw}")
            results.append((f"atr={aw}", r["sharpe"], r["cagr"]))
            del ind

        print("\n  PASS 3  ema_fast/slow   (full rebuild, ~60s per pair)")
        print("  " + "-" * 84)
        for ef, es in ((13, 34), (21, 50), (20, 60)):
            ind = {tk: prepare_indicators(df, ema_fast=ef, ema_slow=es)
                   for tk, df in raws.items()}
            r = score(ind, f"ema {ef}/{es}")
            results.append((f"ema={ef}/{es}", r["sharpe"], r["cagr"]))
            del ind

    # ── Summary + noise floor ────────────────────────────────────────────────
    results.sort(key=lambda x: -x[1])
    sh = [r[1] for r in results if r[1] > -900]
    print("\n" + "=" * 86)
    print("  RANKED  (baseline is hh=12, bo_close=0.96 — anything below it is noise)")
    print("=" * 86)
    for name, s, c in results[:10]:
        print(f"    {name:<22} Sharpe {s:5.2f}   CAGR {c:6.2f}%")
    if len(sh) > 2:
        floor = O.expected_max_sharpe(len(sh), float(np.std(sh, ddof=1)))
        print(f"\n  {len(sh)} trials | best {max(sh):.3f} | "
              f"expected best if NO edge {floor:.3f}")
        print("  => " + ("CLEARS the noise bar" if max(sh) > floor
                         else "INDISTINGUISHABLE FROM NOISE — do not deploy"))
    print(f"\nTOTAL {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
