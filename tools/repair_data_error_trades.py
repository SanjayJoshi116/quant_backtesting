"""
tools/repair_data_error_trades.py — one-off ledger repair.

Before this fix, any paper trade whose stored entry price drifted more than 30%
from the cached close on its signal date was permanently closed as DATA_ERROR
with no P&L. Two things were wrong with that:

  1. Most mismatches were transient. A single poisoned yfinance batch on
     2026-06-17 killed 38 live positions at once; the cache was correct again
     the next day, but the trades were already dead.
  2. Genuine corporate actions were treated as corruption. Yahoo back-adjusts
     history for splits and bonus issues, so a position opened before an
     ex-date is simply on a different scale — recoverable by rescaling.

This script re-validates every DATA_ERROR row against the current cache and
reopens the ones that are recoverable, so the normal
core.paper_trader.update_open_positions() replay can resolve them to a real
TP/SL/EXPIRED outcome:

  - price now matches      → false alarm, reopen as-is
  - a split explains it    → rescale entry/SL/TP, record split_adj, reopen
  - still unexplained      → left as DATA_ERROR

It also reopens any trade that resolved OUTSIDE its holding window. The replay
used to scan every bar since entry with no cap, so a skipped run let a position
keep running until it happened to touch SL or TP — a trade that should have
expired on day 30 could resolve on day 47 instead.

Nothing is deleted — the ledger stays append-only, statuses are only corrected.

    python tools/repair_data_error_trades.py [--apply]

Without --apply it reports what it would change and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import paper_trader as pt                    # noqa: E402
from core.data import fetch_or_load, fetch_splits      # noqa: E402


def _classify(row: pd.Series, today: pd.Timestamp) -> tuple[str, float | None]:
    """
    Return (verdict, split_factor) for one DATA_ERROR row.

    verdict is "clean" (price now agrees), "split" (a corporate action explains
    the gap, factor returned) or "stranded" (still unexplained).
    """
    ticker      = str(row["ticker"])
    signal_date = pd.Timestamp(row["signal_date"])
    entry       = float(row["entry_price"])

    ohlc = fetch_or_load(ticker)
    if ohlc is None or ohlc.empty:
        return "stranded", None

    bar = ohlc[ohlc.index.normalize() == signal_date.normalize()]
    if bar.empty:
        return "stranded", None
    actual_close = float(bar["Close"].iloc[-1])
    if actual_close <= 0:
        return "stranded", None

    ratio = entry / actual_close
    if pt.PRICE_TOL_LO < ratio < pt.PRICE_TOL_HI:
        return "clean", None

    splits = fetch_splits(ticker)
    if splits.empty:
        return "stranded", None
    window = splits[(splits.index > signal_date) & (splits.index <= today)]
    if window.empty:
        return "stranded", None

    factor = float(window.prod())
    if factor <= 0 or abs(ratio / factor - 1) >= pt.SPLIT_TOL:
        return "stranded", None
    return "split", factor


def _reopen(df: pd.DataFrame, idx) -> None:
    """Clear the exit fields so the position is tracked again."""
    df.at[idx, "status"]      = "OPEN"
    df.at[idx, "exit_price"]  = ""
    df.at[idx, "exit_date"]   = ""
    df.at[idx, "exit_reason"] = ""
    df.at[idx, "pnl_pct"]     = ""
    df.at[idx, "days_held"]   = ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the repaired ledger (default: dry run)")
    args = ap.parse_args()

    df = pt._load()
    targets = df.index[df["status"] == "DATA_ERROR"].tolist()
    if not targets:
        print("No DATA_ERROR rows to repair.")
        return 0

    today = pd.Timestamp.today().normalize()
    clean, split, stranded = [], [], []

    for idx in targets:
        row = df.loc[idx]
        try:
            verdict, factor = _classify(row, today)
        except Exception as exc:
            print(f"  [WARN] {row['ticker']}: {exc}")
            verdict, factor = "stranded", None

        ticker = str(row["ticker"])
        sig    = pd.Timestamp(row["signal_date"]).date()

        if verdict == "clean":
            _reopen(df, idx)
            clean.append((ticker, sig))
        elif verdict == "split":
            for col in ("entry_price", "sl", "tp"):
                df.at[idx, col] = round(float(row[col]) / factor, 4)
            df.at[idx, "split_adj"] = round(factor, 6)
            _reopen(df, idx)
            split.append((ticker, sig, factor))
        else:
            stranded.append((ticker, sig, str(row["exit_reason"])))

    # ── Trades that resolved outside their holding window ─────────────────────
    closed   = df["status"].isin(["TP_HIT", "SL_HIT", "EXPIRED"])
    held     = pd.to_numeric(df["days_held"], errors="coerce")
    late_idx = df.index[closed & (held > pt.MAX_DAYS)].tolist()
    for idx in late_idx:
        _reopen(df, idx)

    print(f"\nDATA_ERROR rows examined     : {len(targets)}")
    print(f"  false alarm (price now ok) : {len(clean)}")
    print(f"  corporate action (rescaled): {len(split)}")
    print(f"  still unexplained          : {len(stranded)}")

    if split:
        print("\n  rescaled for splits:")
        for t, d, f in split:
            print(f"    {t:<16} {d}   factor {f:g}")
    if stranded:
        print("\n  left as DATA_ERROR:")
        for t, d, why in stranded:
            print(f"    {t:<16} {d}   {why}")

    print(f"\nResolved outside the {pt.MAX_DAYS}-day window (reopened): "
          f"{len(late_idx)}")

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply to commit.")
        return 0

    pt._save(df)
    reopened = len(clean) + len(split) + len(late_idx)
    print(f"\nWrote {pt.PAPER_LOG} — {reopened} positions reopened.")
    print("Run core.paper_trader.update_open_positions() to replay them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
