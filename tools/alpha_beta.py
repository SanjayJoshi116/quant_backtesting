"""
tools/alpha_beta.py

How much of the strategy's return is skill, and how much is just owning the market?

Every profitable year for this strategy is a profitable year for the Nifty, which
is exactly what a long-only momentum system in a decade-long bull market looks
like. This regresses daily portfolio returns on the index:

    r_strategy(t) = alpha + beta * r_nifty(t) + e(t)

  beta   how much index exposure you are carrying (cash drag pulls this below 1)
  alpha  the daily return left over -- the part that is NOT market exposure
  R^2    fraction of your variance explained by the index alone

Also reported:
  - t-stat on alpha: is it distinguishable from zero at all?
  - Information ratio: alpha per unit of tracking error
  - Up/down capture: does it participate in rallies and sit out declines?

A large CAGR advantage with beta near 1 and alpha near 0 means you built a
leveraged index tracker. Positive, significant alpha means there is real edge.

    python tools/alpha_beta.py
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

from analysis import compute_universe_breadth
from backtester import run_backtest
from core.config import load_config
from core.portfolio import attach_turnover, load_close_series, simulate_portfolio
from data import TICKERS
from indicators import prepare_indicators

ROOT = Path(__file__).resolve().parent.parent
TRADING_DAYS = 252.0
MIN_TURNOVER, COST, CAP, MAXPOS, POSPCT = 25e7, 0.0020, 100_000.0, 15, 6.5


def ols(y: np.ndarray, x: np.ndarray) -> dict:
    """OLS y = a + b*x with standard errors and t-stats."""
    X = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n, k = len(y), X.shape[1]
    s2 = resid @ resid / (n - k)
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    t = coef / se
    p = 2 * (1 - stats.t.cdf(np.abs(t), n - k))
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - (resid @ resid) / ss_tot if ss_tot > 0 else 0.0
    return {"alpha": coef[0], "beta": coef[1], "alpha_se": se[0], "beta_se": se[1],
            "alpha_t": t[0], "beta_t": t[1], "alpha_p": p[0], "r2": r2,
            "resid": resid, "n": n}


def main() -> None:
    t0 = time.time()
    ind = {}
    for tk in TICKERS:
        f = ROOT / "data/raw" / f"{tk.replace('^','IDX_').replace('.','_')}.csv"
        if not f.exists():
            continue
        raw = pd.read_csv(f, index_col=0, parse_dates=True)
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        if len(raw) >= 300:
            ind[tk] = prepare_indicators(raw)
    br = compute_universe_breadth(ind)
    print(f"  {len(ind)} tickers ready [{time.time()-t0:.0f}s]", flush=True)

    # Recommended config: breadth gate on, liquid names only
    p = dict(load_config().to_params_dict(),
             breadth_gate_enabled=True, breadth_min_pct=20.0,
             breadth_gated_signals=["BO-L"])
    rows = []
    for tk, df in ind.items():
        rows.extend(run_backtest(df, params=p, ticker=tk, breadth=br))
    t = attach_turnover(pd.DataFrame(rows), window=60)
    res = simulate_portfolio(t[t.turnover >= MIN_TURNOVER], max_positions=MAXPOS,
                             max_position_pct=POSPCT, starting_capital=CAP,
                             round_trip_cost=COST)

    eq = res.equity
    nif = load_close_series("^NSEI")
    # NB: use df["eq"], not df.eq — the latter resolves to DataFrame.eq(), the
    # elementwise-comparison method, not the column.
    df = pd.DataFrame({"eq": eq, "nif": nif.reindex(eq.index).ffill()}).dropna()
    r_s = df["eq"].pct_change().dropna()
    r_m = df["nif"].pct_change().reindex(r_s.index).fillna(0.0)

    print("\n" + "=" * 78)
    print("  ALPHA / BETA DECOMPOSITION  (daily, 2016-2026)")
    print("=" * 78)
    m = ols(r_s.to_numpy(), r_m.to_numpy())
    ann_alpha = (1 + m["alpha"]) ** TRADING_DAYS - 1

    print(f"  observations          : {m['n']:,} trading days")
    print(f"  beta (index exposure) : {m['beta']:.3f}   (t={m['beta_t']:.1f})")
    print(f"  alpha, daily          : {m['alpha']*100:+.4f}%")
    print(f"  alpha, ANNUALISED     : {ann_alpha*100:+.2f}%   "
          f"(t={m['alpha_t']:.2f}, p={m['alpha_p']:.3f})")
    print(f"  R^2 (explained by index): {m['r2']*100:.1f}%")
    verdict = ("SIGNIFICANT at 5%" if m["alpha_p"] < 0.05 else
               "NOT significant — indistinguishable from zero")
    print(f"  => alpha is {verdict}")

    te = m["resid"].std(ddof=1) * np.sqrt(TRADING_DAYS)
    ir = ann_alpha / te if te > 0 else 0.0
    print(f"\n  tracking error (ann.) : {te*100:.2f}%")
    print(f"  information ratio     : {ir:.2f}   "
          f"(>0.5 decent, >1.0 strong)")

    up, dn = r_m > 0, r_m < 0
    uc = r_s[up].mean() / r_m[up].mean() if up.any() else np.nan
    dc = r_s[dn].mean() / r_m[dn].mean() if dn.any() else np.nan
    print(f"\n  up-capture   : {uc*100:6.1f}%   (of index gains on up days)")
    print(f"  down-capture : {dc*100:6.1f}%   (of index losses on down days)")
    print("     lower down-capture than up-capture = genuine downside protection")

    print("\n  Yearly decomposition:")
    print(f"  {'yr':<6}{'beta':>7}{'alpha_ann':>11}{'t':>7}{'strat%':>9}{'nifty%':>9}")
    for yr, g in r_s.groupby(r_s.index.year):
        gm = r_m.reindex(g.index).fillna(0.0)
        if len(g) < 30:
            continue
        k = ols(g.to_numpy(), gm.to_numpy())
        a = ((1 + k["alpha"]) ** TRADING_DAYS - 1) * 100
        print(f"  {yr:<6}{k['beta']:>7.2f}{a:>10.1f}%{k['alpha_t']:>7.2f}"
              f"{(np.prod(1+g)-1)*100:>8.1f}%{(np.prod(1+gm)-1)*100:>8.1f}%")

    # What a plain beta-matched index position would have earned
    total_s = (np.prod(1 + r_s) - 1) * 100
    total_m = (np.prod(1 + r_m) - 1) * 100
    print(f"\n  Total return  strategy {total_s:+.1f}%   nifty {total_m:+.1f}%   "
          f"beta-matched index {total_m*m['beta']:+.1f}%")
    print(f"  Excess over beta-matched exposure: {total_s - total_m*m['beta']:+.1f}%")
    print(f"\nTOTAL {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
