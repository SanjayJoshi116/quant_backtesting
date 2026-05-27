"""
core/paper_trader.py — Automated paper trading tracker.

Plugs into the screener pipeline:
  1. log_new_signals(signals)    — called after every screen run
  2. update_open_positions()     — checks SL/TP against latest OHLC
  3. get_stats()                 — returns live performance vs backtest

Rules (user-defined):
  - Entry = signal day's close price (user buys after 3 PM)
  - Window = 14 calendar days; EXPIRED if neither SL nor TP hit
  - One open position per ticker — duplicate signals skipped
  - Long only (shorts skipped; most retail can't short NSE stocks directly)
  - Never delete rows — every signal stays for statistical validation
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PAPER_LOG = Path("logs/paper_trades.csv")
MAX_DAYS  = 30   # 30 calendar days (~21 trading days)
# Backtest data shows: SL median=14 trading days, TP median=25 trading days.
# 14-day window expires 70% of trades before SL/TP — too noisy.
# 30-day window expires only 30% — captures most meaningful outcomes.

COLUMNS = [
    "signal_date", "ticker",       "signal_type", "direction",
    "entry_price", "sl",           "tp",          "rr",
    "score",       "sector",
    "qual_score",  "qual_tier",    # fundamental quality at time of signal
    "status",                                      # OPEN / TP_HIT / SL_HIT / EXPIRED
    "exit_price",  "exit_date",    "exit_reason",
    "pnl_pct",     "days_held",
]


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _load() -> pd.DataFrame:
    if not PAPER_LOG.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(PAPER_LOG, parse_dates=["signal_date", "exit_date"])
    return df


def _save(df: pd.DataFrame) -> None:
    PAPER_LOG.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PAPER_LOG, index=False)


# ── Core functions ────────────────────────────────────────────────────────────

def log_new_signals(signals: list[dict]) -> int:
    """
    Log today's screener signals as paper trades.

    Rules:
    - Skip if ticker already has an OPEN position
    - Skip short signals
    - Entry = today's close price (the signal's entry field)
    - Returns number of new trades added
    """
    df       = _load()
    today_str = date.today().strftime("%Y-%m-%d")

    # Tickers already open — don't create duplicate positions
    open_tickers: set[str] = set(
        df.loc[df["status"] == "OPEN", "ticker"]
    ) if not df.empty else set()

    new_rows = []
    for sig in signals:
        ticker = sig.get("ticker", "")

        if sig.get("direction", "LONG") != "LONG":
            continue          # long-only
        if ticker in open_tickers:
            continue          # already tracking this stock
        if not sig.get("entry"):
            continue

        new_rows.append({
            "signal_date": today_str,
            "ticker":      ticker,
            "signal_type": sig.get("signal_type", ""),
            "direction":   "LONG",
            "entry_price": round(float(sig["entry"]), 2),
            "sl":          round(float(sig.get("sl",  0)), 2),
            "tp":          round(float(sig.get("tp",  0)), 2),
            "rr":          sig.get("rr",    0),
            "score":       sig.get("score", 0),
            "sector":      sig.get("sector", ""),
            "qual_score":  sig.get("qual_score", ""),   # fundamental score at signal time
            "qual_tier":   sig.get("qual_tier",  "UNKNOWN"),
            "status":      "OPEN",
            "exit_price":  "",  "exit_date":   "",
            "exit_reason": "",  "pnl_pct":     "",  "days_held": "",
        })
        open_tickers.add(ticker)    # prevent two adds for the same ticker

    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        _save(df)

    return len(new_rows)


def update_open_positions() -> dict:
    """
    Check every OPEN paper trade against the latest OHLC.

    For each open position:
    - Replay all bars since entry in date order
    - First bar where Low ≤ SL  → SL_HIT
    - First bar where High ≥ TP → TP_HIT
    - If neither and days ≥ MAX_DAYS → EXPIRED (exit at latest close)

    Returns count dict: {updated, tp_hit, sl_hit, expired, still_open}
    """
    df = _load()
    if df.empty:
        return {"updated": 0, "tp_hit": 0, "sl_hit": 0,
                "expired": 0, "still_open": 0}

    open_idx = df.index[df["status"] == "OPEN"].tolist()
    if not open_idx:
        return {"updated": 0, "tp_hit": 0, "sl_hit": 0,
                "expired": 0, "still_open": 0}

    from core.data import fetch_or_load
    today = pd.Timestamp.today().normalize()
    counts = {"tp_hit": 0, "sl_hit": 0, "expired": 0}

    for idx in open_idx:
        row          = df.loc[idx]
        ticker       = str(row["ticker"])
        entry_price  = float(row["entry_price"])
        sl           = float(row["sl"])
        tp           = float(row["tp"])
        signal_date  = pd.Timestamp(row["signal_date"])
        days_elapsed = (today - signal_date).days

        try:
            ohlc = fetch_or_load(ticker)
            if ohlc is None or ohlc.empty:
                continue

            # Bars strictly AFTER the signal date
            bars = ohlc[ohlc.index > signal_date].copy()
            if bars.empty:
                # Data not yet updated — check expiry only
                if days_elapsed >= MAX_DAYS:
                    df.at[idx, "status"]      = "EXPIRED"
                    df.at[idx, "exit_price"]  = entry_price
                    df.at[idx, "exit_date"]   = today.strftime("%Y-%m-%d")
                    df.at[idx, "exit_reason"] = "EXPIRED"
                    df.at[idx, "pnl_pct"]     = 0.0
                    df.at[idx, "days_held"]   = days_elapsed
                    counts["expired"] += 1
                continue

            # ── Replay bars in order — first SL or TP hit wins ───────────────
            hit = None
            for bar_ts, bar in bars.iterrows():
                if bar["Low"] <= sl:
                    hit = ("SL_HIT", "SL", sl, bar_ts)
                    break
                if bar["High"] >= tp:
                    hit = ("TP_HIT", "TP", tp, bar_ts)
                    break

            if hit:
                status, reason, exit_px, exit_ts = hit
                pnl = (exit_px - entry_price) / entry_price * 100
                if status == "SL_HIT":
                    pnl = -abs(pnl)
                df.at[idx, "status"]      = status
                df.at[idx, "exit_price"]  = round(float(exit_px), 2)
                df.at[idx, "exit_date"]   = pd.Timestamp(exit_ts).strftime("%Y-%m-%d")
                df.at[idx, "exit_reason"] = reason
                df.at[idx, "pnl_pct"]     = round(pnl, 2)
                df.at[idx, "days_held"]   = (pd.Timestamp(exit_ts) - signal_date).days
                counts[status.lower()] += 1

            elif days_elapsed >= MAX_DAYS:
                last_close = float(bars["Close"].iloc[-1])
                pnl        = (last_close - entry_price) / entry_price * 100
                df.at[idx, "status"]      = "EXPIRED"
                df.at[idx, "exit_price"]  = round(last_close, 2)
                df.at[idx, "exit_date"]   = today.strftime("%Y-%m-%d")
                df.at[idx, "exit_reason"] = "EXPIRED"
                df.at[idx, "pnl_pct"]     = round(pnl, 2)
                df.at[idx, "days_held"]   = days_elapsed
                counts["expired"] += 1

        except Exception:
            continue

    _save(df)
    counts["updated"]    = sum(counts.values())
    counts["still_open"] = int((df["status"] == "OPEN").sum())
    return counts


def get_open_positions() -> pd.DataFrame:
    """
    Return all OPEN paper positions with current price and unrealised P&L.
    Called by the dashboard to show the live watchlist.
    """
    df = _load()
    if df.empty:
        return pd.DataFrame()

    open_df = df[df["status"] == "OPEN"].copy()
    if open_df.empty:
        return pd.DataFrame()

    from core.data import fetch_or_load
    today = pd.Timestamp.today().normalize()

    current_prices, unreal_pnl, days_open = [], [], []

    for _, row in open_df.iterrows():
        entry  = float(row["entry_price"])
        signal = pd.Timestamp(row["signal_date"])
        days   = (today - signal).days

        try:
            ohlc = fetch_or_load(str(row["ticker"]))
            if ohlc is not None and not ohlc.empty:
                cur = float(ohlc["Close"].iloc[-1])
            else:
                cur = entry
        except Exception:
            cur = entry

        pnl = (cur - entry) / entry * 100
        current_prices.append(round(cur, 2))
        unreal_pnl.append(round(pnl, 2))
        days_open.append(days)

    open_df = open_df.copy()
    open_df["current_price"] = current_prices
    open_df["unreal_pnl"]    = unreal_pnl
    open_df["days_open"]     = days_open
    open_df["days_left"]     = MAX_DAYS - open_df["days_open"]

    return open_df.sort_values("signal_date", ascending=False).reset_index(drop=True)


def get_stats() -> dict:
    """
    Compute paper trading stats for the dashboard.
    Returns comprehensive breakdown by signal type, score, exit reason.
    """
    df = _load()
    if df.empty:
        return {}

    n_open   = int((df["status"] == "OPEN").sum())
    n_total  = len(df)
    closed   = df[df["status"].isin(["TP_HIT","SL_HIT","EXPIRED"])].copy()

    if closed.empty:
        return {"open": n_open, "total": n_total, "closed": 0}

    closed["pnl_pct"] = pd.to_numeric(closed["pnl_pct"], errors="coerce")
    closed = closed.dropna(subset=["pnl_pct"])
    if closed.empty:
        return {"open": n_open, "total": n_total, "closed": 0}

    wins   = closed[closed["pnl_pct"] > 0]
    losses = closed[closed["pnl_pct"] <= 0]
    n_c    = len(closed)

    def _pf():
        gp = wins["pnl_pct"].sum()
        gl = abs(losses["pnl_pct"].sum())
        return round(gp / gl, 2) if gl > 0 else 99.0

    stats = {
        "open":          n_open,
        "total":         n_total,
        "closed":        n_c,
        "win_rate":      round(len(wins) / n_c * 100, 1),
        "avg_win":       round(float(wins["pnl_pct"].mean()),   2) if len(wins)   > 0 else 0,
        "avg_loss":      round(float(losses["pnl_pct"].mean()), 2) if len(losses) > 0 else 0,
        "profit_factor": _pf(),
        "avg_days":      round(float(pd.to_numeric(closed["days_held"], errors="coerce").mean()), 1),
        "by_score":    {},
        "by_signal":   {},
        "by_quality":  {},   # breakdown by fundamental tier — key insight
        "by_exit":     {},
        "recent":      [],
    }

    # By technical score — most actionable insight
    closed["_score"] = pd.to_numeric(closed["score"], errors="coerce").fillna(0).astype(int)
    for score, grp in closed.groupby("_score"):
        wr  = (grp["pnl_pct"] > 0).mean() * 100
        avg = grp["pnl_pct"].mean()
        stats["by_score"][int(score)] = {
            "n": len(grp), "wr": round(wr, 1), "avg": round(avg, 2)
        }

    # By signal type
    for sig, grp in closed.groupby("signal_type"):
        wr  = (grp["pnl_pct"] > 0).mean() * 100
        avg = grp["pnl_pct"].mean()
        stats["by_signal"][str(sig)] = {
            "n": len(grp), "wr": round(wr, 1), "avg": round(avg, 2)
        }

    # By fundamental quality tier — answers "does the fundamental filter add alpha?"
    if "qual_tier" in closed.columns:
        tier_order = ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]
        for tier in tier_order:
            grp = closed[closed["qual_tier"] == tier]
            if len(grp) == 0:
                continue
            grp_pnl = grp["pnl_pct"].dropna()
            if len(grp_pnl) == 0:
                continue
            wr  = (grp_pnl > 0).mean() * 100
            avg = grp_pnl.mean()
            gp  = grp_pnl[grp_pnl > 0].sum()
            gl  = abs(grp_pnl[grp_pnl <= 0].sum())
            pf  = round(gp / gl, 2) if gl > 0 else 99.0
            stats["by_quality"][tier] = {
                "n":  len(grp_pnl),
                "wr": round(wr, 1),
                "avg": round(avg, 2),
                "pf":  pf,
            }

    # By exit reason
    for reason, grp in closed.groupby("exit_reason"):
        stats["by_exit"][str(reason)] = {
            "n": len(grp), "avg_pnl": round(grp["pnl_pct"].mean(), 2)
        }

    # 10 most recent closed trades
    recent_cols = ["ticker", "signal_type", "entry_price",
                   "exit_price", "pnl_pct", "exit_reason", "days_held"]
    # Include qual columns if present
    for col in ["qual_score", "qual_tier"]:
        if col in closed.columns:
            recent_cols.append(col)
    recent = (closed.sort_values("exit_date", ascending=False)
              .head(10)[recent_cols]
              .to_dict("records"))
    stats["recent"] = recent

    return stats
