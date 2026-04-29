"""
core/universe_builder.py — Expand the backtesting universe.

Downloads data for all NSE EQ-series stocks from stocks_list.csv,
filters for quality, and updates data.py TICKERS list.

Run:  python core/universe_builder.py
"""

import os
import sys
import warnings
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from tqdm import tqdm

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_DIR  = Path(__file__).parent.parent
RAW_DIR   = BASE_DIR / "data" / "raw"
CSV_LIST  = BASE_DIR / "stocks_list.csv"
DATA_PY   = BASE_DIR / "data.py"

START_DATE     = "2016-01-01"
END_DATE       = "2026-04-30"
MIN_BARS       = 500        # at least 500 trading days (~2 years)
MIN_AVG_VOL    = 50_000     # minimum avg daily volume (liquidity filter)
MAX_MISSING    = 0.05       # max 5% missing bars
LISTED_BEFORE  = "2021-01-01"


def _safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace(".", "_")


def get_candidate_symbols() -> list[str]:
    """
    Read stocks_list.csv, filter EQ series listed before cutoff.
    Returns list of ticker symbols with .NS suffix.
    """
    df = pd.read_csv(CSV_LIST)
    df.columns = [c.strip() for c in df.columns]
    df["list_date"] = pd.to_datetime(
        df["DATE OF LISTING"], dayfirst=True, errors="coerce")

    eq = df[df["SERIES"].str.strip() == "EQ"].copy()
    filtered = eq[eq["list_date"] < LISTED_BEFORE]

    symbols = []
    for sym in filtered["SYMBOL"].dropna():
        sym = str(sym).strip()
        if sym:
            symbols.append(sym + ".NS")

    print(f"  Candidate stocks (EQ, listed before {LISTED_BEFORE}): {len(symbols)}")
    return symbols


def download_and_filter(symbols: list[str],
                        batch_size: int = 50) -> list[str]:
    """
    Download OHLCV data for all candidates in batches.
    Returns list of tickers that passed quality filters.
    Saves CSVs to data/raw/.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    passed = []
    failed = []

    print(f"\n  Downloading {len(symbols)} stocks in batches of {batch_size}...")
    print(f"  Quality filters: ≥{MIN_BARS} bars, avg vol ≥{MIN_AVG_VOL:,}, "
          f"missing < {MAX_MISSING:.0%}")
    print()

    for i in tqdm(range(0, len(symbols), batch_size),
                  desc="  Batches", ncols=70):
        batch = symbols[i: i + batch_size]

        try:
            raw = yf.download(
                batch,
                start   = START_DATE,
                end     = END_DATE,
                interval     = "1d",
                auto_adjust  = True,
                progress     = False,
                actions      = False,
                group_by     = "ticker",
            )
        except Exception as e:
            failed.extend(batch)
            continue

        for ticker in batch:
            csv_path = RAW_DIR / f"{_safe_name(ticker)}.csv"

            # Extract this ticker's slice
            try:
                if len(batch) == 1:
                    df = raw.copy()
                else:
                    df = raw[ticker].copy() if ticker in raw.columns.get_level_values(0) \
                         else pd.DataFrame()

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                needed = ["Open", "High", "Low", "Close", "Volume"]
                if not all(c in df.columns for c in needed):
                    failed.append(ticker)
                    continue

                df = df[needed].copy()

                # Quality gate 1: minimum bars
                n_total = len(df)
                if n_total < MIN_BARS:
                    failed.append(ticker)
                    continue

                # Quality gate 2: missing data
                n_nan = df["Close"].isna().sum()
                if n_nan / n_total > MAX_MISSING:
                    failed.append(ticker)
                    continue

                # Quality gate 3: minimum average volume (liquidity)
                avg_vol = df["Volume"].dropna().mean()
                if avg_vol < MIN_AVG_VOL:
                    failed.append(ticker)
                    continue

                # Quality gate 4: price must be positive
                df.ffill(inplace=True)
                df.dropna(inplace=True)
                df = df[df["Close"] > 0]
                df.index = pd.to_datetime(df.index).tz_localize(None)
                df.index.name = "Date"

                if len(df) < MIN_BARS:
                    failed.append(ticker)
                    continue

                df.to_csv(csv_path)
                passed.append(ticker)

            except Exception:
                failed.append(ticker)
                continue

    print(f"\n  Results: {len(passed)} passed  |  {len(failed)} failed/filtered")
    return passed


def update_data_py(passed_tickers: list[str]) -> None:
    """
    Rewrite the TICKERS list in data.py with the expanded universe.
    Groups stocks by sector for readability.
    """
    # Read sector info from universe.py if available
    try:
        from bot.universe import get_sector
        sectors: dict[str, list[str]] = {}
        for t in sorted(passed_tickers):
            sec = get_sector(t) or "Other"
            sectors.setdefault(sec, []).append(t)
    except Exception:
        sectors = {"All": sorted(passed_tickers)}

    # Build the new TICKERS block
    lines = ['TICKERS = [']
    for sec, tickers in sorted(sectors.items()):
        lines.append(f'    # ── {sec} {"─"*(50-len(sec))}')
        # Format 3 per line
        for j in range(0, len(tickers), 3):
            chunk = tickers[j: j + 3]
            formatted = ",  ".join(f'"{t}"' for t in chunk)
            lines.append(f'    {formatted},')
    lines.append(']')

    tickers_block = "\n".join(lines)

    # Read current data.py
    content = DATA_PY.read_text(encoding="utf-8")

    # Replace the TICKERS = [...] block
    import re
    new_content = re.sub(
        r"TICKERS\s*=\s*\[.*?\]",
        tickers_block,
        content,
        flags=re.DOTALL,
    )

    if new_content == content:
        print("  ⚠️  Could not auto-update data.py — TICKERS block not found as expected")
        # Save to a separate file instead
        out = BASE_DIR / "tickers_expanded.txt"
        out.write_text(tickers_block, encoding="utf-8")
        print(f"  Saved expanded list to {out}")
    else:
        DATA_PY.write_text(new_content, encoding="utf-8")
        print(f"  ✅ data.py updated with {len(passed_tickers)} stocks")


if __name__ == "__main__":
    print("=" * 60)
    print("  NSE Universe Expansion")
    print("=" * 60)

    symbols   = get_candidate_symbols()
    passed    = download_and_filter(symbols)

    print(f"\n  Expanding backtesting universe:")
    print(f"  Before: 86 stocks")
    print(f"  After : {len(passed)} stocks ({len(passed)/86:.1f}× larger)")

    update_data_py(passed)

    print("\n  Next steps:")
    print("  1. python main.py --force-download   (reload full history for new stocks)")
    print("  2. python main.py --skip-optim        (re-run backtest on expanded universe)")
