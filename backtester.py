"""
backtester.py — Bar-by-bar backtester.

Exit logic (long):  MeshBreak → SL → TP   (trailing stop removed)
Exit logic (short): MeshBreak → SL → TP

Design notes:
  • Entry price = close of signal bar.
  • Commission 0.05% + slippage 0.05% per side = 0.20% total round-trip cost.
  • SL / TP fixed at entry using ATR at entry time.
  • On daily bars the exit trigger uses the bar CLOSE (conservative).
    SL/TP fills recorded at the level itself, not at close.
  • Mesh-break exit fills at close.
  • Signal priority (long): PB-L > BASE-BO > BO-L.
  • One position at a time per ticker.
"""

import numpy as np
import pandas as pd

from core.config import load_config

def _round_trip_cost() -> float:
    cfg = load_config()
    return (cfg.commission_pct + cfg.slippage_pct) * 2


# ── Main backtester ────────────────────────────────────────────────────────────
def run_backtest(df: pd.DataFrame,
                 params: dict | None = None,
                 ticker: str = "",
                 market_regime: "pd.Series | None" = None) -> list[dict]:
    """
    Bar-by-bar backtest on a fully-prepared indicator DataFrame.
    Exits: MeshBreak / SL / TP only (no trailing stop).
    """
    cfg = load_config()
    p   = cfg.to_params_dict()
    if params:
        p.update(params)

    sl_mult     = float(p["sl_mult"])
    tp_long     = float(p["tp_mult_long"])
    tp_short    = float(p["tp_mult_short"])
    adx_min_l   = float(p["adx_long"])
    adx_min_s   = float(p["adx_short"])
    rsi_pb_lo   = float(p["rsi_pb_lo"])
    rsi_pb_hi   = float(p["rsi_pb_hi"])
    rsi_bo_lo   = float(p["rsi_bo_lo"])
    rsi_bo_hi   = float(p["rsi_bo_hi"])
    rsi_pbs_lo  = float(p["rsi_pbs_lo"])
    rsi_pbs_hi  = float(p["rsi_pbs_hi"])
    rsi_bos_lo  = float(p["rsi_bos_lo"])
    rsi_bos_hi  = float(p["rsi_bos_hi"])
    vol_ml      = float(p["vol_mult_long"])
    vol_ms      = float(p["vol_mult_short"])
    pb_tol      = float(p["pb_tol"])
    pbs_tol     = float(p["pb_short_tol"])
    di_gap_min  = float(p["di_gap_min"])
    room_atr    = float(p["min_room_atr"])

    # ── Position sizing constants (not varied by optimisation grid) ───────────
    _risk_frac = cfg.risk_per_trade_pct / 100.0   # e.g. 0.015 for 1.5%
    _max_pos   = cfg.max_position_pct   / 100.0   # e.g. 0.20 for 20%
    _rtc       = _round_trip_cost()               # round-trip cost fraction

    # ── Numpy arrays for speed ────────────────────────────────────────────────
    n        = len(df)
    dates    = df.index.to_numpy()
    close_a  = df["Close"].values.astype(np.float64)
    high_a   = df["High"].values.astype(np.float64)
    low_a    = df["Low"].values.astype(np.float64)
    vol_a    = df["Volume"].values.astype(np.float64)
    ema21_a  = df["EMA21"].values.astype(np.float64)
    ema50_a  = df["EMA50"].values.astype(np.float64)
    ema200_a = df["EMA200"].values.astype(np.float64)
    rsi_a    = df["RSI"].values.astype(np.float64)
    adx_a    = df["ADX"].values.astype(np.float64)
    dip_a    = df["DI_pos"].values.astype(np.float64)
    din_a    = df["DI_neg"].values.astype(np.float64)
    atr_a    = df["ATR"].values.astype(np.float64)
    vsma_a   = df["VOL_SMA20"].values.astype(np.float64)
    bull_a   = df["bull_trend"].values.astype(bool)
    bear_a   = df["bear_trend"].values.astype(bool)
    cbull_a  = df["candle_bull"].values.astype(bool)
    cbear_a  = df["candle_bear"].values.astype(bool)
    bocb_a   = df["bo_candle_bull"].values.astype(bool)
    bocs_a   = df["bo_candle_bear"].values.astype(bool)
    hh12_a    = df["highest_high_12"].values.astype(np.float64)
    ll12_a    = df["lowest_low_12"].values.astype(np.float64)
    base_bo_a = df["base_breakout"].values.astype(bool) \
                if "base_breakout" in df.columns else np.zeros(n, dtype=bool)

    ll50_a   = df["lowest_low_50"].values.astype(np.float64)

    # ── Position state ────────────────────────────────────────────────────────
    in_pos     = False
    direction  = ""
    entry_date = None
    entry_px   = 0.0
    entry_atr  = 0.0
    sig_type    = ""
    sl_px       = 0.0
    tp_px       = 0.0
    position_pct = 0.0   # fraction of equity deployed in current trade

    trades: list[dict] = []

    for i in range(1, n):
        c  = close_a[i]
        at = atr_a[i]

        if (np.isnan(ema200_a[i]) or np.isnan(rsi_a[i]) or
                np.isnan(adx_a[i]) or np.isnan(at) or
                np.isnan(vsma_a[i]) or np.isnan(hh12_a[i]) or
                np.isnan(ll50_a[i])):
            continue

        # ── EXIT ──────────────────────────────────────────────────────────────
        if in_pos:
            exit_px     = None
            exit_reason = None

            if direction == "long":
                mesh_brk = (ema21_a[i - 1] > ema50_a[i - 1]) and (ema21_a[i] <= ema50_a[i])
                if mesh_brk:
                    exit_px, exit_reason = c, "MeshBreak"
                elif c <= sl_px:
                    exit_px, exit_reason = sl_px, "SL"
                elif c >= tp_px:
                    exit_px, exit_reason = tp_px, "TP"

            else:  # short
                mesh_brk = (ema21_a[i - 1] < ema50_a[i - 1]) and (ema21_a[i] >= ema50_a[i])
                if mesh_brk:
                    exit_px, exit_reason = c, "MeshBreak"
                elif c >= sl_px:
                    exit_px, exit_reason = sl_px, "SL"
                elif c <= tp_px:
                    exit_px, exit_reason = tp_px, "TP"

            if exit_px is not None:
                raw_pnl = (exit_px / entry_px - 1.0) if direction == "long" \
                          else (entry_px / exit_px - 1.0)
                # pnl_pct: return on the position (signal quality metric)
                pnl_pct = (raw_pnl - _rtc) * 100.0
                # pnl_on_equity: actual impact on account equity with position sizing
                pnl_on_equity = (raw_pnl - _rtc) * position_pct * 100.0

                entry_ts  = pd.Timestamp(entry_date)
                exit_ts   = pd.Timestamp(dates[i])
                bars_held = max((exit_ts - entry_ts).days, 1)

                trades.append({
                    "ticker":        ticker,
                    "direction":     direction,
                    "signal_type":   sig_type,
                    "entry_date":    entry_ts,
                    "exit_date":     exit_ts,
                    "entry_price":   round(entry_px, 4),
                    "exit_price":    round(exit_px, 4),
                    "exit_reason":   exit_reason,
                    "atr_at_entry":  round(entry_atr, 4),
                    "pnl_pct":       round(pnl_pct, 4),
                    "pnl_on_equity": round(pnl_on_equity, 4),
                    "position_pct":  round(position_pct * 100, 2),
                    "bars_held":     bars_held,
                })
                in_pos = False

        # ── ENTRY ─────────────────────────────────────────────────────────────
        if not in_pos:
            bull = bull_a[i]
            bear = bear_a[i]
            r    = rsi_a[i]
            a    = adx_a[i]
            v    = vol_a[i]
            vs   = vsma_a[i]
            e21  = ema21_a[i]
            e50  = ema50_a[i]

            vol_ok_l = v >= vs * vol_ml
            vol_ok_s = v >= vs * vol_ms
            adx_ok_l = a >= adx_min_l
            adx_ok_s = a >= adx_min_s
            di_dom   = (din_a[i] - dip_a[i]) >= di_gap_min
            room_ok  = (c - ll50_a[i]) >= at * room_atr

            new_sig  = ""
            is_long  = False
            is_short = False

            # PB-L
            if (bull and
                    low_a[i] <= e21 * pb_tol and c > e21 and
                    rsi_pb_lo <= r <= rsi_pb_hi and
                    cbull_a[i] and adx_ok_l and vol_ok_l):
                new_sig, is_long = "PB-L", True

            # BASE-BO — flat base breakout (higher quality, checked before generic BO-L)
            elif (bull and base_bo_a[i] and
                    rsi_bo_lo <= r <= rsi_bo_hi and
                    bocb_a[i] and adx_ok_l and
                    v >= vs * vol_ml * 1.2):    # require stronger volume on base breaks
                new_sig, is_long = "BASE-BO", True

            # BO-L — generic 12-bar high breakout
            elif (bull and
                    not np.isnan(hh12_a[i]) and c > hh12_a[i] and
                    rsi_bo_lo <= r <= rsi_bo_hi and
                    bocb_a[i] and adx_ok_l and vol_ok_l):
                new_sig, is_long = "BO-L", True

            # PB-S
            elif (bear and
                    high_a[i] >= e21 * pbs_tol and c < e21 and
                    rsi_pbs_lo <= r <= rsi_pbs_hi and
                    cbear_a[i] and adx_ok_s and vol_ok_s and
                    di_dom and room_ok):
                new_sig, is_short = "PB-S", True

            # BO-S
            elif (bear and
                    not np.isnan(ll12_a[i]) and c < ll12_a[i] and
                    rsi_bos_lo <= r <= rsi_bos_hi and
                    bocs_a[i] and adx_ok_s and vol_ok_s and
                    di_dom and room_ok):
                new_sig, is_short = "BO-S", True




            # Regime gate: block new long entries when Nifty is below EMA200
            if is_long and market_regime is not None:
                try:
                    is_long = bool(market_regime.asof(pd.Timestamp(dates[i])))
                    if not is_long:
                        new_sig = ""
                except Exception:
                    pass

            if is_long:
                in_pos      = True
                direction   = "long"
                entry_date  = dates[i]
                entry_px    = c
                entry_atr   = at
                sig_type    = new_sig
                sl_px       = entry_px - at * sl_mult
                tp_px       = entry_px + at * tp_long
                sl_dist_pct = (at * sl_mult) / entry_px
                position_pct = min(_risk_frac / max(sl_dist_pct, 1e-6), _max_pos)

            elif is_short:
                in_pos      = True
                direction   = "short"
                entry_date  = dates[i]
                entry_px    = c
                entry_atr   = at
                sig_type    = new_sig
                sl_px       = entry_px + at * sl_mult
                tp_px       = entry_px - at * tp_short
                sl_dist_pct = (at * sl_mult) / entry_px
                position_pct = min(_risk_frac / max(sl_dist_pct, 1e-6), _max_pos)

    return trades
