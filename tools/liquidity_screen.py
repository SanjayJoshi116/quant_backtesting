"""
tools/liquidity_screen.py

Does the edge survive if you only trade liquid names?

The backtest assumes 0.05% slippage per side on every one of 886 tickers. That is
plausible for RELIANCE and fantasy for a smallcap that trades Rs 20 lakh a day.
This screens trades by trailing median rupee turnover at the entry bar and
re-runs the portfolio at a cost level appropriate to each liquidity tier.

    python tools/liquidity_screen.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core.portfolio import attach_turnover, simulate_portfolio

ROOT = Path(__file__).resolve().parent.parent
CR = 1e7  # 1 crore
CAP = 100_000.0


def load_trades() -> pd.DataFrame:
    frames = []
    for f in glob.glob(str(ROOT / "results/trades_*.csv")):
        if "OOS" in Path(f).name or "portfolio" in Path(f).name:
            continue
        d = pd.read_csv(f)
        if not d.empty and "pnl_pct" in d.columns:
            frames.append(d)
    if not frames:
        raise FileNotFoundError("No trade CSVs in results/.")
    t = pd.concat(frames, ignore_index=True)
    t["entry_date"] = pd.to_datetime(t.entry_date)
    t["exit_date"] = pd.to_datetime(t.exit_date)
    return t


def add_scores(t: pd.DataFrame) -> pd.DataFrame:
    try:
        from core.ml.feature_builder import build_features
        from core.ml.xgb_scorer import walk_forward_scores
        f = build_features()
        f["ml_score"] = walk_forward_scores(f, n_folds=10)
        f = f.dropna(subset=["ml_score"])
        f["entry_date"] = pd.to_datetime(f["entry_date"])
        t = t.merge(f.drop_duplicates(subset=["ticker", "entry_date"])[
            ["ticker", "entry_date", "ml_score"]],
            on=["ticker", "entry_date"], how="left")
    except Exception as e:
        print(f"  [WARN] ML scores unavailable ({e})")
        t["ml_score"] = 0.5
    t["ml_score"] = t["ml_score"].fillna(0.5)
    return t


def main() -> None:
    t = add_scores(load_trades())
    print("  Computing trailing 60-bar median turnover per entry bar...")
    t = attach_turnover(t, window=60)

    known = t.turnover.notna().sum()
    print(f"  turnover known for {known:,}/{len(t):,} trades")
    q = t.turnover.dropna().quantile([.1, .25, .5, .75, .9])
    print("  turnover distribution (Rs crore/day):")
    for k, v in q.items():
        print(f"    p{int(k*100):<3} {v/CR:>10.2f}")

    # Tier -> (min turnover, realistic round-trip cost)
    tiers = [
        ("no filter          @0.20%", 0.0,      0.0020),
        ("no filter          @0.50%", 0.0,      0.0050),
        (">= Rs 1 cr/day     @0.40%", 1 * CR,   0.0040),
        (">= Rs 5 cr/day     @0.30%", 5 * CR,   0.0030),
        (">= Rs 10 cr/day    @0.25%", 10 * CR,  0.0025),
        (">= Rs 25 cr/day    @0.20%", 25 * CR,  0.0020),
        (">= Rs 50 cr/day    @0.15%", 50 * CR,  0.0015),
    ]

    print(f"\n  {'Tier':<28} {'Elig':>6} {'Taken':>6} {'Final Rs':>11} "
          f"{'CAGR':>7} {'Sharpe':>7} {'MaxDD':>8}")
    print("  " + "-" * 80)

    out = {}
    for label, minto, cost in tiers:
        sub = t if minto <= 0 else t[t.turnover >= minto]
        if len(sub) < 50:
            print(f"  {label:<28} {len(sub):>6}  (too few trades)")
            continue
        r = simulate_portfolio(sub, max_positions=15, max_position_pct=6.5,
                               rank_col="ml_score", starting_capital=CAP,
                               round_trip_cost=cost)
        m = r.metrics
        out[label] = r
        print(f"  {label:<28} {len(sub):>6} {m['n_taken']:>6} "
              f"{float(r.equity.iloc[-1]):>11,.0f} {m['cagr']:>6.1f}% "
              f"{m['sharpe']:>7.2f} {m['max_dd']:>7.1f}%")

    print("\n  Nifty 50 buy & hold over the same window: Rs 276,299 "
          "(CAGR 11.3%, Sharpe 0.75)")

    # Recent-period check on the best liquid tier
    key = ">= Rs 5 cr/day     @0.30%"
    if key in out:
        eq = out[key].equity
        yr = eq.resample("YE").last()
        rets = (yr / yr.shift(1).fillna(eq.iloc[0]) - 1) * 100
        print(f"\n  Yearly return, {key.strip()}:")
        for d, v in rets.items():
            print(f"    {d.year}  {v:+7.1f}%")


if __name__ == "__main__":
    main()
