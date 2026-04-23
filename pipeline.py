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
    """Run the daily screener and send email alerts."""
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
