"""
tools/run_portfolio.py

Replay every trade in results/ against ONE account with a real capital limit.

    python tools/run_portfolio.py

Compares position caps and the rule used to pick which signals get funded when
more fire than the account can afford.
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core.config import load_config
from core.portfolio import simulate_portfolio

RESULTS = Path(__file__).resolve().parent.parent / "results"


def load_all_trades() -> pd.DataFrame:
    frames = []
    for f in glob.glob(str(RESULTS / "trades_*.csv")):
        if "OOS" in Path(f).name:
            continue
        try:
            d = pd.read_csv(f)
            if not d.empty and "pnl_pct" in d.columns:
                frames.append(d)
        except Exception as e:
            print(f"  [WARN] {Path(f).name}: {e}")
    if not frames:
        raise FileNotFoundError("No trade CSVs in results/ — run main.py first.")
    return pd.concat(frames, ignore_index=True)


def add_ml_scores(t: pd.DataFrame) -> pd.DataFrame:
    """
    Attach P(win) so it can rank candidates competing for capital.

    The trade CSVs do not store RSI/ADX/volume at entry, so we rebuild the full
    10-feature matrix (which re-reads the indicator values AT the entry bar) and
    merge scores back on (ticker, entry_date). Scoring off the CSV columns alone
    would leave 7 of 10 features at their defaults and produce a near-constant
    score — a useless ranking.
    """
    try:
        from core.ml.feature_builder import build_features
        from core.ml.xgb_scorer import walk_forward_scores

        feats = build_features()
        # WALK-FORWARD scores, not the production model's. Ranking trades by a
        # model trained on those same trades is lookahead: it would pick winners
        # it had already been shown, and the equity curve becomes fiction.
        feats["ml_score"] = walk_forward_scores(feats, n_folds=10)
        feats = feats.dropna(subset=["ml_score"])
        feats["entry_date"] = pd.to_datetime(feats["entry_date"])

        key = ["ticker", "entry_date"]
        lut = feats.drop_duplicates(subset=key)[key + ["ml_score"]]
        t = t.merge(lut, on=key, how="left")
        n_missing = int(t.ml_score.isna().sum())
        t["ml_score"] = t["ml_score"].fillna(0.5)
        print(f"  ML scores attached: {len(t) - n_missing:,}/{len(t):,} "
              f"(spread {t.ml_score.min():.3f}-{t.ml_score.max():.3f}, "
              f"sd {t.ml_score.std():.3f})")
    except Exception as e:
        print(f"  [WARN] ML scoring unavailable ({e}) — ranking by ticker instead.")
        t["ml_score"] = 0.5
    return t


def main() -> None:
    cfg = load_config()
    t = load_all_trades()
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["exit_date"] = pd.to_datetime(t["exit_date"])

    print("=" * 78)
    print("  PORTFOLIO REPLAY — one account, real capital limit")
    print("=" * 78)
    print(f"  Trades available : {len(t):,} across {t.ticker.nunique()} tickers")
    print(f"  Period           : {t.entry_date.min().date()} -> {t.exit_date.max().date()}")
    print(f"  Starting capital : Rs {cfg.starting_capital:,.0f}")
    print(f"  Max position     : {cfg.max_position_pct}% of equity")

    t = add_ml_scores(t)

    # Random-order controls: quantify how much of the result is just luck in
    # which of the oversubscribed signals happened to get funded.
    rng = np.random.default_rng(42)
    for s in range(3):
        t[f"rand{s}"] = rng.random(len(t))

    print(f"\n  {'Config':<36} {'Taken':>6} {'Fill%':>6} {'CAGR%':>7} "
          f"{'Sharpe':>7} {'MaxDD%':>8} {'TotRet%':>9}")
    print("  " + "-" * 78)

    # Position size is matched to the cap so the cap actually binds — at the
    # default 20% max only ~5 positions fit in 100% of equity.
    runs = [
        ("unconstrained (999 pos, 20%)", 999, 20.0, None),
        ("10 pos / 10% ea, rank=alpha",   10, 10.0, None),
        ("10 pos / 10% ea, rank=random0", 10, 10.0, "rand0"),
        ("10 pos / 10% ea, rank=ML(WF)",  10, 10.0, "ml_score"),
        ("15 pos / 6.5% ea, rank=alpha",  15,  6.5, None),
        ("15 pos / 6.5% ea, rank=random0",15,  6.5, "rand0"),
        ("15 pos / 6.5% ea, rank=random1",15,  6.5, "rand1"),
        ("15 pos / 6.5% ea, rank=random2",15,  6.5, "rand2"),
        ("15 pos / 6.5% ea, rank=ML(WF)", 15,  6.5, "ml_score"),
    ]

    out = {}
    for label, cap, possz, rank in runs:
        res = simulate_portfolio(t, max_positions=cap, max_position_pct=possz,
                                 rank_col=rank)
        m = res.metrics
        out[label] = res
        print(f"  {label:<36} {m['n_taken']:>6} {m['fill_rate']:>6.1f} "
              f"{m['cagr']:>7.2f} {m['sharpe']:>7.2f} {m['max_dd']:>8.2f} "
              f"{m['total_return']:>9.1f}")

    rnd = [out[f"15 pos / 6.5% ea, rank=random{s}"].metrics["cagr"] for s in range(3)]
    print(f"\n  Random-order CAGR spread (15 pos): "
          f"{min(rnd):.1f}% - {max(rnd):.1f}%  (mean {np.mean(rnd):.1f}%)")
    print(f"  ML(WF) CAGR: {out['15 pos / 6.5% ea, rank=ML(WF)'].metrics['cagr']:.1f}% "
          f"-- only meaningful if it clears that band")

    ref = out["15 pos / 6.5% ea, rank=ML(WF)"]
    print(f"\n  Book utilisation (15 pos / 6.5% each):")
    print(f"    open positions  mean {ref.daily_positions.mean():.1f}  "
          f"max {ref.daily_positions.max():.0f}")
    print(f"    deployed %      mean {ref.daily_deployed_pct.mean():.0f}%  "
          f"max {ref.daily_deployed_pct.max():.0f}%")

    eq = ref.equity
    yr = eq.resample("YE").last()
    yr_ret = (yr / yr.shift(1).fillna(eq.iloc[0]) - 1) * 100
    print(f"\n  Yearly return, 15 pos / 6.5% ea, ML(WF)-ranked:")
    for d, v in yr_ret.items():
        print(f"    {d.year}  {v:+7.1f}%")

    ref.equity.to_csv(RESULTS / "portfolio_equity.csv", header=["equity"])
    print(f"\n  Wrote {RESULTS / 'portfolio_equity.csv'}")


if __name__ == "__main__":
    main()
