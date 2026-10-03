"""
tools/edge_reality_check.py

Does a tradable edge survive realistic execution? Re-runs the per-ticker
backtest under four fill scenarios on the same cached data, replays each through
ONE capital-limited account (core/portfolio.py), and ends in the verdict
pre-registered in the `edge_check:` section of config/strategy.yaml.

    python tools/edge_reality_check.py              # full universe
    python tools/edge_reality_check.py --limit 40   # smoke test (separate dir, no audit rows)

Outputs (never the top-level results/trades_*.csv the scorecard and ML read):
    results/edge_check/<scenario>/trades_<ticker>.csv
    results/edge_check/edge_reality_report.md
    results/edge_check/summary.csv

See openspec/changes/edge-reality-check for the design.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core.config import load_config

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS  = BASE_DIR / "results"
CR       = 1e7                       # 1 crore

# Scenarios differ ONLY in fill mode.
SCENARIOS: dict[str, tuple[str, str]] = {
    "baseline":  ("signal_close", "close_at_level"),
    "next_open": ("next_open",    "close_at_level"),
    "gap_exit":  ("signal_close", "intraday"),
    "realistic": ("next_open",    "intraday"),
}
SWEEP_SLIPPAGE = (0.0005, 0.0010, 0.0015, 0.0025, 0.0050)   # per side
SWEEP_SCENARIOS = ("baseline", "realistic")
IS_END      = pd.Timestamp("2020-12-31")
OOS_START   = pd.Timestamp("2021-01-01")
SEASON_DAYS = 30


# ── Output guard ──────────────────────────────────────────────────────────────

def snapshot_top_level_trades() -> dict[str, tuple[int, str]]:
    """name -> (mtime_ns, sha256) for every top-level results/trades_*.csv."""
    snap = {}
    for p in sorted(RESULTS.glob("trades_*.csv")):
        with open(p, "rb") as fh:
            snap[p.name] = (p.stat().st_mtime_ns, hashlib.sha256(fh.read()).hexdigest())
    return snap


def assert_untouched(before: dict[str, tuple[int, str]]) -> None:
    after = snapshot_top_level_trades()
    if after != before:
        changed = sorted(set(before) ^ set(after) |
                         {k for k in before.keys() & after.keys() if before[k] != after[k]})
        raise RuntimeError(f"top-level results/trades_*.csv changed during the run: {changed[:10]}")


# ── Per-ticker backtests (process pool) ───────────────────────────────────────

_W_REGIME = None
_W_BREADTH = None


def _init_worker(regime, breadth) -> None:
    global _W_REGIME, _W_BREADTH
    warnings.filterwarnings("ignore")
    _W_REGIME, _W_BREADTH = regime, breadth


def _annotate(trades: list[dict], df: pd.DataFrame, entry_fill: str) -> pd.DataFrame:
    """Add signal_date (bar the decision was made on) and exit_bar_ffill."""
    t = pd.DataFrame(trades)
    if t.empty:
        return t
    pos = df.index.get_indexer(pd.to_datetime(t["entry_date"]))
    sig = pos - 1 if entry_fill == "next_open" else pos
    t["signal_date"] = df.index[sig]
    # A forward-filled (fabricated) bar repeats the prior bar's volume exactly.
    vol = df["Volume"].to_numpy(dtype=np.float64)
    xi = df.index.get_indexer(pd.to_datetime(t["exit_date"]))
    t["exit_bar_ffill"] = [bool(i > 0 and vol[i] == vol[i - 1]) for i in xi]
    return t


def _run_ticker(ticker: str) -> dict | None:
    from backtester import run_backtest
    from core.backtest_inputs import load_prepared

    df = load_prepared(ticker)
    if df is None:
        return None
    out = {"ticker": ticker, "first_bar": df.index[0], "scenarios": {},
           "bull_trend": df["bull_trend"].astype(float)}
    for name, (ef, xf) in SCENARIOS.items():
        stats: dict = {}
        trades = run_backtest(df, params={"entry_fill": ef, "exit_fill": xf},
                              ticker=ticker, market_regime=_W_REGIME, stats=stats)
        out["scenarios"][name] = (_annotate(trades, df, ef), stats.get("unfilled", 0))
    return out


def _run_ticker_breadth(ticker: str) -> tuple[pd.DataFrame, int] | None:
    """Realistic scenario with the breadth gate active (optional row, task 3.13)."""
    from backtester import run_backtest
    from core.backtest_inputs import load_prepared

    df = load_prepared(ticker)
    if df is None:
        return None
    ef, xf = SCENARIOS["realistic"]
    stats: dict = {}
    trades = run_backtest(df, params={"entry_fill": ef, "exit_fill": xf}, ticker=ticker,
                          market_regime=_W_REGIME, breadth=_W_BREADTH, stats=stats)
    return _annotate(trades, df, ef), stats.get("unfilled", 0)


# ── Portfolio metrics ─────────────────────────────────────────────────────────

def _trade_returns(taken: pd.DataFrame, rtc: float) -> pd.Series:
    """Per-trade return % net of `rtc`, the same convention simulate_portfolio books."""
    if taken.empty:
        return pd.Series(dtype=float)
    long = taken["direction"] == "long"
    raw = np.where(long, taken["exit_price"] / taken["entry_price"] - 1.0,
                   taken["entry_price"] / taken["exit_price"] - 1.0)
    return pd.Series((raw - rtc) * 100.0, index=taken.index)


def equity_metrics(eq: pd.Series) -> dict:
    from core.portfolio import _metrics_from_equity
    m = _metrics_from_equity(eq, 0, 0)
    return {k: m[k] for k in ("cagr", "sharpe", "max_dd", "total_return")}


def period_slices(eq: pd.Series) -> dict[str, pd.Series]:
    """IS and OOS slices of ONE equity curve; OOS starts from the last IS value."""
    is_eq = eq[eq.index <= IS_END]
    oos_eq = eq[eq.index >= OOS_START]
    if len(is_eq) and len(oos_eq):
        oos_eq = pd.concat([is_eq.iloc[-1:], oos_eq])
    return {"2016-2020": is_eq, "2021+": oos_eq}


def yearly_returns(eq: pd.Series) -> pd.Series:
    if eq.empty:
        return pd.Series(dtype=float)
    yr = eq.resample("YE").last()
    prev = yr.shift(1)
    prev.iloc[0] = eq.iloc[0]
    out = (yr / prev - 1.0) * 100.0
    out.index = out.index.year
    return out.round(2)


def replay(trades: pd.DataFrame, rtc: float, unfilled: int = 0) -> dict:
    """One-account replay with the configured position limits, plus trade stats."""
    from core.portfolio import simulate_portfolio

    if trades.empty:
        empty = {k: 0 for k in METRIC_COLS}
        empty.update(trades_generated=0, unfilled_signals=unfilled, profit_factor=0.0,
                     start=None, end=None)
        return {"metrics": empty, "equity": pd.Series(dtype=float), "taken": trades}
    res = simulate_portfolio(trades, round_trip_cost=rtc)
    r = _trade_returns(res.taken, rtc)
    wins, losses = r[r > 0], r[r < 0]          # breakevens (== 0) are neither
    gross_loss = -losses.sum()
    m = {
        "trades_generated": len(trades),
        "unfilled_signals": unfilled,
        "trades_taken":     res.metrics["n_taken"],
        "trades_skipped":   res.metrics["n_skipped"],
        **equity_metrics(res.equity),
        "win_rate":         round(len(wins) / max(len(wins) + len(losses), 1) * 100.0, 2),
        "avg_loss":         round(float(losses.mean()), 3) if len(losses) else 0.0,
        "profit_factor":    round(float(wins.sum() / gross_loss), 3) if gross_loss > 0 else 0.0,
        "start":            res.equity.index[0].date() if len(res.equity) else None,
        "end":              res.equity.index[-1].date() if len(res.equity) else None,
    }
    for label, sl in period_slices(res.equity).items():
        pm = equity_metrics(sl)
        m[f"cagr_{label}"], m[f"sharpe_{label}"] = pm["cagr"], pm["sharpe"]
    return {"metrics": m, "equity": res.equity, "taken": res.taken}


def benchmark_cagr(start, end) -> float | None:
    """Nifty 50 price-index CAGR (no dividends) over [start, end], cached data."""
    from core.portfolio import load_close_series
    from data import NIFTY_TICKER

    s = load_close_series(NIFTY_TICKER)
    if s is None:
        return None
    s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))].dropna()
    return equity_metrics(s)["cagr"] if len(s) >= 3 else None


def breakeven_slippage(points: list[tuple[float, float]], target: float) -> tuple[str, float | None]:
    """
    Per-side slippage at which CAGR falls to `target`, by linear interpolation.

    Returns ("interpolated", x), ("above_range", None) when CAGR stays above
    target at every swept level, or ("below_range", None) when it is already at
    or below target at the lowest level.
    """
    pts = sorted(points)
    if pts[0][1] <= target:
        return "below_range", None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if y0 > target >= y1:
            return "interpolated", x0 + (y0 - target) * (x1 - x0) / (y0 - y1)
    return "above_range", None


def breakeven_value(result: tuple[str, float | None]) -> float:
    """Numeric stand-in for the verdict: +inf above range, 0 below range."""
    kind, x = result
    return {"above_range": math.inf, "below_range": 0.0}.get(kind, x)


# ── Verdict ───────────────────────────────────────────────────────────────────

def compute_verdict(m: dict, cfg) -> tuple[str, list[dict]]:
    """
    SURVIVES / MARGINAL / FAILS from the pre-registered `edge_check` criteria.

    `m` keys: cagr, sharpe, benchmark_cagr, breakeven_slippage (per side, as a
    fraction; inf if above the swept range), cagr_2016-2020, cagr_2021+.
    """
    rows = []

    def add(name, value, threshold, ok, kind):
        rows.append({"criterion": name, "kind": kind, "measured": value,
                     "threshold": threshold, "result": "PASS" if ok else "FAIL"})
        return ok

    survive = [
        add("Sharpe (daily, realistic)", m["sharpe"], f">= {cfg.survive_min_sharpe}",
            m["sharpe"] >= cfg.survive_min_sharpe, "survive"),
        add("Break-even slippage per side", m["breakeven_slippage"],
            f">= {cfg.survive_min_breakeven_slippage_pct}",
            m["breakeven_slippage"] >= cfg.survive_min_breakeven_slippage_pct, "survive"),
    ]
    if cfg.survive_beat_benchmark:
        bench = m.get("benchmark_cagr")
        survive.append(add("CAGR vs Nifty 50 price CAGR", m["cagr"],
                           f"> {bench}" if bench is not None else "> n/a",
                           bench is not None and m["cagr"] > bench, "survive"))

    fail = [not add("Full-period CAGR", m["cagr"], "> 0", m["cagr"] > 0, "fail")]
    if cfg.fail_if_any_period_negative:
        for p in ("2016-2020", "2021+"):
            fail.append(not add(f"CAGR {p}", m[f"cagr_{p}"], "> 0",
                                m[f"cagr_{p}"] > 0, "fail"))

    if any(fail):
        return "FAILS", rows
    if all(survive):
        return "SURVIVES", rows
    return "MARGINAL", rows


# ── Report ────────────────────────────────────────────────────────────────────

METRIC_COLS = ["trades_generated", "unfilled_signals", "trades_taken", "trades_skipped",
               "cagr", "sharpe", "max_dd", "total_return", "win_rate", "avg_loss",
               "cagr_2016-2020", "sharpe_2016-2020", "cagr_2021+", "sharpe_2021+"]


def _md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    return "\n".join(lines)


def _fmt_be(res: tuple[str, float | None], lo: float, hi: float) -> str:
    kind, x = res
    if kind == "interpolated":
        return f"{x * 100:.3f}% per side"
    if kind == "above_range":
        return f"above {hi * 100:.2f}% per side (the whole sweep)"
    return f"below {lo * 100:.2f}% per side (the lowest swept level)"


def _fmt_criteria(criteria: list[dict]) -> pd.DataFrame:
    """Slippage criteria are stored as fractions; show them as % per side."""
    df = pd.DataFrame(criteria).astype({"measured": object})
    for i, r in df.iterrows():
        if "slippage" in r["criterion"]:
            v = r["measured"]
            df.at[i, "measured"] = ("above sweep" if v == math.inf else f"{v * 100:.3f}%")
            df.at[i, "threshold"] = ">= " + f"{float(r['threshold'].split()[-1]) * 100:.2f}%"
    return df


def write_report(out_dir: Path, ctx: dict) -> None:
    cfg = ctx["cfg"]
    rows = ctx["rows"]
    summary = pd.DataFrame(rows)
    summary.to_csv(out_dir / "summary.csv", index=False)

    real_cost = ctx["real_cost_label"]
    L = [
        "# Edge Reality Check",
        "",
        f"Generated {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} · config_version "
        f"{cfg.config_version} · {ctx['n_tickers']} tickers · period {ctx['start']} → {ctx['end']}",
        "",
        f"## Verdict: **{ctx['verdict']}**",
        "",
        f"Basis: realistic scenario (next-open entry, intraday gap-aware exits) at "
        f"{real_cost}, one account, {cfg.max_positions} positions max, "
        f"{cfg.max_position_pct:g}% max per position. Criteria are the pre-registered "
        "`edge_check` values in `config/strategy.yaml`.",
        "",
        _md_table(_fmt_criteria(ctx["criteria"])),
        "",
        "## 1. Fill scenarios (configured costs)",
        "",
        f"Configured cost: {cfg.commission_pct * 100:.2f}% commission + "
        f"{cfg.slippage_pct * 100:.2f}% slippage per side. Scenarios differ only in fill mode.",
        "",
        _md_table(summary[summary.group == "scenario"][["label"] + METRIC_COLS]),
        "",
        f"Verdict row (realistic @ {real_cost}):",
        "",
        _md_table(summary[summary.group == "verdict"][["label"] + METRIC_COLS]),
        "",
        "## 2. Slippage sweep and cost headroom",
        "",
        _md_table(summary[summary.group == "sweep"][["label", "trades_taken", "cagr",
                                                    "sharpe", "max_dd"]]),
        "",
        f"Benchmark (Nifty 50 price index, same period): CAGR {ctx['bench']}%",
        "",
    ]
    lo, hi = SWEEP_SLIPPAGE[0], SWEEP_SLIPPAGE[-1]
    for sc in SWEEP_SCENARIOS:
        be0, beb = ctx["breakeven"][sc]
        L += [f"- **{sc}**: CAGR reaches zero at {_fmt_be(be0, lo, hi)}; "
              f"falls to the benchmark at {_fmt_be(beb, lo, hi)}."]
    L += [
        "",
        "## 3. Survivorship proxies (realistic scenario)",
        "",
        f"Seasoned = first cached bar on or before {ctx['season_cut']} "
        f"({ctx['n_seasoned']} tickers); later-listed = the rest ({ctx['n_later']}). "
        f"Causal liquidity keeps a trade only if the 60-bar trailing median turnover on "
        f"the signal bar is at least Rs {cfg.causal_min_turnover_cr:g} cr/day.",
        "",
        _md_table(summary[summary.group.isin(["verdict", "survivorship"])][["label"] + METRIC_COLS]),
        "",
        "**Stocks that were delisted, merged or suspended before today are absent from the "
        "data, and their effect is not measured. Survivorship bias from them is not sized "
        "here, so every figure in this report remains an upper bound in that respect.**",
        "",
        "## 4. Periods",
        "",
        "2016–2020 is in-sample. 2021 onwards was consulted while tuning `bo_close_frac` "
        "and the breadth gate, so it is **not a clean holdout**. Period figures are slices "
        "of the one full-period account; the 2021+ slice starts from the 2020 year-end equity.",
        "",
        "Calendar-year returns (%):",
        "",
        _md_table(ctx["yearly"].reset_index().rename(columns={"index": "row"})),
        "",
        "## 5. Data quality",
        "",
        "Trades whose exit bar repeats the prior bar's volume exactly (a forward-filled, "
        "fabricated bar — intraday fills there use stale prices):",
        "",
        _md_table(pd.DataFrame(ctx["ffill"])),
        "",
    ]
    if ctx.get("breadth_note"):
        L += ["## 6. Breadth gate", "", ctx["breadth_note"], ""]
    L += [
        "## Disclosures",
        "",
        "- **Delisted stocks unmeasured.** The universe is today's surviving stocks. "
        "Names delisted, merged or suspended earlier are absent; results are an upper bound.",
        "- **Tuning-contaminated out-of-sample.** 2021 onwards informed parameter choices.",
        "- **Data path.** The backtest uses the cached `data.py` series (adjusted prices); the "
        "live screener uses a different, unadjusted path. The verdict applies to the backtest "
        "data path only.",
        "- **Breadth gate off.** Mirrors `main.py`, which passes no breadth series, although "
        "the parameters were tuned with the gate on.",
        "- **Price-only benchmark.** The Nifty 50 series excludes dividends (~1–1.5%/yr), "
        "which flatters the strategy in the benchmark comparison.",
        "- **Candidate ranking.** When more signals fire than the account can fund, "
        "`simulate_portfolio` picks alphabetically by ticker (no score), deterministically.",
        "- **Same-bar SL/TP.** In intraday mode a bar spanning both levels is booked as SL.",
    ]
    with open(out_dir / "edge_reality_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(limit: int | None = None, workers: int | None = None, breadth_row: bool = True) -> str:
    from analysis import compute_universe_breadth
    from core.backtest_inputs import build_regime
    from core.logging import log_backtest_run
    from core.portfolio import attach_turnover
    from data import TICKERS, NIFTY_TICKER, START_DATE, load_data

    cfg = load_config()
    before = snapshot_top_level_trades()          # 3.3: startup snapshot

    smoke = limit is not None
    out_dir = RESULTS / ("edge_check_smoke" if smoke else "edge_check")
    if out_dir.resolve() == RESULTS.resolve():
        raise RuntimeError("edge check output must be a subdirectory of results/")
    out_dir.mkdir(parents=True, exist_ok=True)

    tickers = TICKERS[:limit] if smoke else list(TICKERS)
    _, regime = build_regime(load_data(NIFTY_TICKER))

    print(f"  Backtesting {len(tickers)} tickers x {len(SCENARIOS)} scenarios ...")
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(regime, None)) as ex:
        results = [r for r in ex.map(_run_ticker, tickers, chunksize=8) if r is not None]
    results.sort(key=lambda r: r["ticker"])

    # Per-scenario trade frames, written under the scenario subdirectory.
    scen_trades: dict[str, pd.DataFrame] = {}
    scen_unfilled: dict[str, int] = {}
    for name in SCENARIOS:
        d = out_dir / name
        d.mkdir(exist_ok=True)
        parts, unf = [], 0
        for r in results:
            t, u = r["scenarios"][name]
            unf += u
            t.to_csv(d / f"trades_{r['ticker'].replace('.', '_')}.csv", index=False)
            if not t.empty:
                parts.append(t)
        scen_trades[name] = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        scen_unfilled[name] = unf

    base_rtc = (cfg.commission_pct + cfg.slippage_pct) * 2
    real_rtc = (cfg.commission_pct + cfg.realistic_slippage_pct) * 2
    real_cost_label = f"{cfg.realistic_slippage_pct * 100:.2f}% slippage per side"

    rows: list[dict] = []
    equities: dict[str, pd.Series] = {}

    def add_row(group: str, label: str, rep: dict, **extra) -> None:
        rows.append({"group": group, "label": label, **extra, **rep["metrics"]})

    print("  Portfolio replays ...")
    for name, (ef, xf) in SCENARIOS.items():
        rep = replay(scen_trades[name], base_rtc, scen_unfilled[name])
        add_row("scenario", name, rep, entry_fill=ef, exit_fill=xf, slippage_pct=cfg.slippage_pct)
        equities[name] = rep["equity"]

        # 3.12: one audit row per scenario; the fill modes enter the params hash.
        if not smoke:
            m = rep["metrics"]
            log_backtest_run(
                n_trades=m["trades_taken"], sharpe=m["sharpe"], win_rate=m["win_rate"],
                profit_factor=m["profit_factor"], max_dd=m["max_dd"],
                start_date=str(m["start"]), end_date=str(m["end"]),
                results_path=f"results/edge_check/{name} (entry_fill={ef}, exit_fill={xf})",
                cfg=cfg.model_copy(update={"entry_fill": ef, "exit_fill": xf}),
            )

    real = scen_trades["realistic"]
    verdict_rep = replay(real, real_rtc, scen_unfilled["realistic"])
    add_row("verdict", f"realistic @ {real_cost_label}", verdict_rep,
            entry_fill="next_open", exit_fill="intraday", slippage_pct=cfg.realistic_slippage_pct)
    equities["realistic (verdict)"] = verdict_rep["equity"]
    vm = verdict_rep["metrics"]

    bench = benchmark_cagr(vm["start"], vm["end"])

    # 3.5 slippage sweep
    breakeven: dict[str, tuple] = {}
    for sc in SWEEP_SCENARIOS:
        pts = []
        for s in SWEEP_SLIPPAGE:
            rep = replay(scen_trades[sc], (cfg.commission_pct + s) * 2, scen_unfilled[sc])
            add_row("sweep", f"{sc} @ {s * 100:.2f}%", rep, slippage_pct=s)
            pts.append((s, rep["metrics"]["cagr"]))
        breakeven[sc] = (breakeven_slippage(pts, 0.0),
                         breakeven_slippage(pts, bench) if bench is not None
                         else ("below_range", None))

    # 3.7 survivorship proxies
    season_cut = pd.Timestamp(START_DATE) + pd.Timedelta(days=SEASON_DAYS)
    seasoned = {r["ticker"] for r in results if r["first_bar"] <= season_cut}
    for label, mask in (("seasoned cohort", real.ticker.isin(seasoned)),
                        ("later-listed cohort", ~real.ticker.isin(seasoned))):
        add_row("survivorship", label, replay(real[mask], real_rtc), slippage_pct=cfg.realistic_slippage_pct)
    # Turnover as of the SIGNAL bar: next-open entries were decided the day before.
    tv = attach_turnover(real.assign(entry_date=real["signal_date"]), window=60)
    liquid = real[(tv["turnover"] >= cfg.causal_min_turnover_cr * CR).to_numpy()]
    add_row("survivorship", f"causal liquidity >= Rs {cfg.causal_min_turnover_cr:g} cr",
            replay(liquid, real_rtc), slippage_pct=cfg.realistic_slippage_pct)

    # 3.13 optional breadth-on realistic row (cached data only; one extra pass)
    breadth_note = None
    if breadth_row:
        breadth = compute_universe_breadth({r["ticker"]: r["bull_trend"].to_frame("bull_trend")
                                            for r in results})
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                                 initargs=(regime, breadth)) as ex:
            br = [r for r in ex.map(_run_ticker_breadth, [r["ticker"] for r in results],
                                    chunksize=8) if r is not None]
        bt = pd.concat([t for t, _ in br if not t.empty], ignore_index=True)
        brep = replay(bt, real_rtc, sum(u for _, u in br))
        add_row("breadth", f"realistic + breadth gate @ {real_cost_label}", brep,
                slippage_pct=cfg.realistic_slippage_pct)
        equities["realistic + breadth"] = brep["equity"]
        bm = brep["metrics"]
        breadth_note = (f"Informational only, not the verdict basis. With the breadth gate "
                        f"on (breadth from `analysis.compute_universe_breadth` over this "
                        f"universe), the realistic scenario at {real_cost_label} gives CAGR "
                        f"{bm['cagr']}%, Sharpe {bm['sharpe']}, max DD {bm['max_dd']}% "
                        f"(2016–2020 CAGR {bm['cagr_2016-2020']}%, 2021+ {bm['cagr_2021+']}%).")

    # 3.10 verdict
    verdict, criteria = compute_verdict({
        "cagr": vm["cagr"], "sharpe": vm["sharpe"], "benchmark_cagr": bench,
        "breakeven_slippage": breakeven_value(breakeven["realistic"][0]),
        "cagr_2016-2020": vm["cagr_2016-2020"], "cagr_2021+": vm["cagr_2021+"],
    }, cfg)

    ffill = [{"scenario": n, "trades": len(t),
              "exit_on_ffill_bar": int(t["exit_bar_ffill"].sum()) if not t.empty else 0}
             for n, t in scen_trades.items()]

    yearly = pd.DataFrame({k: yearly_returns(v) for k, v in equities.items()}).T

    write_report(out_dir, {
        "cfg": cfg, "rows": rows, "verdict": verdict, "criteria": criteria,
        "n_tickers": len(results), "start": vm["start"], "end": vm["end"],
        "bench": bench, "breakeven": breakeven, "real_cost_label": real_cost_label,
        "season_cut": season_cut.date(), "n_seasoned": len(seasoned),
        "n_later": len(results) - len(seasoned), "yearly": yearly, "ffill": ffill,
        "breadth_note": breadth_note,
    })

    assert_untouched(before)                      # 3.3: end-of-run check
    print(f"\n  VERDICT: {verdict}")
    print(f"  Report  : {out_dir / 'edge_reality_report.md'}")
    if smoke:
        print("  (smoke run: subset of tickers, no audit rows written)")
    return verdict


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke test on the first N tickers (writes results/edge_check_smoke/)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-breadth-row", action="store_true",
                    help="skip the optional breadth-on realistic row (one fewer pass)")
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    main(limit=a.limit, workers=a.workers, breadth_row=not a.no_breadth_row)
