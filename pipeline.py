"""
pipeline.py — Unified CLI for the NSE swing trading system.

Usage
-----
  python pipeline.py backtest                        # full backtest
  python pipeline.py backtest --skip-optim           # skip walk-forward grid search
  python pipeline.py backtest --force-download       # re-fetch all market data

  python pipeline.py screen                          # scan + send email
  python pipeline.py screen --dry-run                # scan, print, no email
  python pipeline.py screen --tickers WIPRO.NS TCS.NS

  python pipeline.py both                            # backtest → screen (optim skipped)
  python pipeline.py both --with-optim               # include walk-forward optimisation
  python pipeline.py both --dry-run                  # backtest → scan, no email

  python pipeline.py config                          # show active strategy parameters
"""

import sys
import os
from typing import Optional, List

import typer

# Ensure project root is importable regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = typer.Typer(
    name="pipeline",
    help="NSE Swing Trading Pipeline — backtest, screen, or run both in sequence.",
    add_completion=False,
    no_args_is_help=True,
)


# ── backtest ──────────────────────────────────────────────────────────────────

@app.command()
def backtest(
    force_download: bool = typer.Option(
        False, "--force-download",
        help="Re-download all market data even if cache is fresh.",
    ),
    skip_optim: bool = typer.Option(
        False, "--skip-optim",
        help="Skip walk-forward grid search (saves ~5-10 min).",
    ),
) -> None:
    """Run the full backtest pipeline: data → indicators → backtest → analysis → charts."""
    from main import main as _backtest
    _backtest(force_download=force_download, skip_optim=skip_optim)


# ── screen ────────────────────────────────────────────────────────────────────

@app.command()
def screen(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Scan and print signals but do NOT send email.",
    ),
    tickers: Optional[List[str]] = typer.Option(
        None, "--tickers",
        help="Override watchlist (e.g. --tickers WIPRO.NS TCS.NS).",
    ),
) -> None:
    """Run the daily screener — sends one email with technical signals + chart patterns."""
    from bot.main import run as _screen
    _screen(watchlist=tickers or None, dry_run=dry_run)


# ── both ──────────────────────────────────────────────────────────────────────

@app.command()
def both(
    force_download: bool = typer.Option(
        False, "--force-download",
        help="Re-download all market data before backtesting.",
    ),
    with_optim: bool = typer.Option(
        False, "--with-optim",
        help="Include walk-forward optimisation (skipped by default).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="After backtesting, scan but do NOT send email.",
    ),
) -> None:
    """Run full backtest then immediately run the screener."""
    typer.echo("\n" + "=" * 70)
    typer.echo("  STEP 1 / 2 — Backtest pipeline")
    typer.echo("=" * 70)
    from main import main as _backtest
    _backtest(force_download=force_download, skip_optim=not with_optim)

    typer.echo("\n" + "=" * 70)
    typer.echo("  STEP 2 / 2 — Screener")
    typer.echo("=" * 70)
    from bot.main import run as _screen
    _screen(dry_run=dry_run)


# ── config ────────────────────────────────────────────────────────────────────

@app.command()
def patterns(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print results to terminal, do NOT send email.",
    ),
    min_confidence: str = typer.Option(
        "MODERATE", "--confidence",
        help="Minimum confidence to show: HIGH or MODERATE.",
    ),
    universe: str = typer.Option(
        "backtest", "--universe",
        help="Which stock list to scan: 'backtest' (default ~86), 'bot', or 'all'.",
    ),
) -> None:
    """Scan stocks for chart patterns forming — double bottom, bull flag, wedge, H&S, cup & handle."""
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from data import TICKERS, RAW_DIR, _safe_name
    from bot.universe import WATCHLIST
    from indicators import prepare_indicators
    from core.pattern_scanner import scan_patterns
    import pandas as pd
    from tqdm import tqdm
    from datetime import datetime

    # Build combined unique ticker list
    if universe == "backtest":
        scan_list = list(dict.fromkeys(TICKERS))
    elif universe == "bot":
        scan_list = list(dict.fromkeys(WATCHLIST))
    else:  # all
        scan_list = list(dict.fromkeys(TICKERS + WATCHLIST))

    typer.echo(f"\n{'='*65}")
    typer.echo(f"  Pattern Scanner  ·  {datetime.now().strftime('%d %b %Y  %H:%M')}")
    typer.echo(f"  Universe: {universe} ({len(scan_list)} stocks)  |  Min confidence: {min_confidence}")
    typer.echo(f"{'='*65}\n")

    # Only scan tickers that have cached CSV data
    scan_list = [t for t in scan_list
                 if os.path.exists(os.path.join(RAW_DIR, f"{_safe_name(t)}.csv"))]

    typer.echo(f"  Stocks with cached data: {len(scan_list)}\n")

    results: list[dict] = []
    failed:  list[str]  = []
    all_patterns: list[dict] = []  # collect ALL before capping

    for ticker in tqdm(scan_list, desc="Scanning patterns", ncols=70):
        try:
            csv = os.path.join(RAW_DIR, f"{_safe_name(ticker)}.csv")
            if not os.path.exists(csv):
                continue
            raw = pd.read_csv(csv, index_col=0, parse_dates=True)
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
            if len(raw) < 100:
                continue
            ind = prepare_indicators(raw)
            pats = scan_patterns(ind)
            for p in pats:
                if min_confidence == "HIGH" and p["confidence"] != "HIGH":
                    continue
                p["ticker"] = ticker
                # Quality score: breakout + confidence + pattern maturity
                p["_q"] = (3 if p.get("breaking_out") else 1) + \
                           (2 if p["confidence"] == "HIGH" else 0) + \
                           min(p.get("bars_forming", p.get("cup_bars",
                               p.get("pennant_bars", p.get("flag_bars", 5)))) / 20, 2)
                all_patterns.append(p)
        except Exception:
            failed.append(ticker)

    # Sort: HIGH first, then by pattern type
    results.sort(key=lambda x: (0 if x["confidence"] == "HIGH" else 1, x["pattern"]))

    # Rank by quality score across ALL stocks, then take top N
    all_patterns.sort(key=lambda p: -p.pop("_q", 0))
    results = all_patterns  # already ranked, no cap for CLI (show all)

    if not results:
        typer.echo("  No patterns found at the selected confidence level.")
    else:
        typer.echo(f"  Found {len(results)} pattern(s) across {len(scan_list)} stocks:\n")
        _CONF_COLOR = {"HIGH": "🟢", "MODERATE": "🟡"}
        for r in results:
            icon = _CONF_COLOR.get(r["confidence"], "⚪")
            typer.echo(f"  {icon} {r['ticker']:<20} [{r['pattern']}]  {r['confidence']}")
            typer.echo(f"     {r['description']}")
            typer.echo()

    if failed:
        typer.echo(f"  Errors on: {', '.join(failed[:5])}{'...' if len(failed) > 5 else ''}")

    if not dry_run and results:
        from bot.notifier import send_pattern_alert
        send_pattern_alert(results)
        typer.echo(f"  Pattern alert email sent ({len(results)} patterns).")
    elif not results:
        pass
    else:
        typer.echo("  [DRY RUN] Email not sent.")


@app.command()
def config() -> None:
    """Show the active strategy parameters loaded from config/strategy.yaml."""
    from core.config import load_config
    cfg = load_config()
    p   = cfg.to_params_dict()

    typer.echo("\nActive strategy parameters  (config/strategy.yaml)\n")
    groups = {
        "Exit / Risk":    ["sl_mult", "tp_mult_long", "tp_mult_short"],
        "Trend filters":  ["adx_long", "adx_short", "di_gap_min", "min_room_atr"],
        "Entry — PB-L":   ["rsi_pb_lo", "rsi_pb_hi", "pb_tol"],
        "Entry — PB50-L": ["rsi_pb50_lo", "rsi_pb50_hi", "pb50_tol"],
        "Entry — BO-L":   ["rsi_bo_lo", "rsi_bo_hi"],
        "Entry — shorts": ["rsi_pbs_lo", "rsi_pbs_hi", "pb_short_tol",
                           "rsi_bos_lo", "rsi_bos_hi"],
        "Volume":         ["vol_mult_long", "vol_mult_short"],
    }
    for group, keys in groups.items():
        typer.echo(f"  {group}:")
        for k in keys:
            if k in p:
                typer.echo(f"    {k:<20} {p[k]}")
    typer.echo(f"\n  data_period      {cfg.data_period}")
    typer.echo(f"  min_bars         {cfg.min_bars}")
    typer.echo(f"  cache_ttl_hours  {cfg.cache_ttl_hours}")
    typer.echo(f"  commission_pct   {cfg.commission_pct}")
    typer.echo(f"  slippage_pct     {cfg.slippage_pct}")
    typer.echo()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
