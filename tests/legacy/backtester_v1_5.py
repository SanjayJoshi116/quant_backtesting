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
                 market_regime: "pd.Series | None" = None,
                 breadth: "pd.Series | None" = None) -> list[dict]:
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

    # ── Breadth gate ──────────────────────────────────────────────────────────
    # Suppress breakout signals when the opportunity set is narrow. `breadth` is
    # the daily % of the universe in bull_trend (see analysis.compute_universe_
    # breadth) and must be supplied by the caller — it is cross-sectional, so a
    # single-ticker backtest cannot compute it.
    breadth_on  = bool(p.get("breadth_gate_enabled", False)) and breadth is not None
    breadth_min = float(p.get("breadth_min_pct", 20.0))
    breadth_sigs = set(p.get("breadth_gated_signals") or ["BO-L"])
    breadth_a = None
    if breadth_on:
        # Align once to this ticker's index; asof() inside the loop is far slower.
        breadth_a = breadth.reindex(df.index).ffill().values.astype(np.float64)

    # ── ML gate ───────────────────────────────────────────────────────────────
    # Regime-conditional: the filter costs money in bull runs and saves it in
    # bad regimes, so the bear threshold is stricter. See config/strategy.yaml.
    ml_on        = bool(p.get("ml_enabled", False))
    ml_thr       = float(p.get("ml_min_score", 0.50))
    ml_thr_bear  = float(p.get("ml_min_score_bear", 0.53))
    _score_fn    = None
    if ml_on:
        try:
            from core.ml.xgb_scorer import score_signal as _score_fn
        except Exception as _e:
            import warnings
            warnings.warn(f"ML gate requested but scorer unavailable: {_e}")
            ml_on = False

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

    # ── ML feature arrays (only needed when the gate is on) ───────────────────
    if ml_on:
        nsup_a  = df["near_support"].values.astype(bool) \
                  if "near_support" in df.columns else np.zeros(n, dtype=bool)
        gmesh_a = df["green_mesh"].values.astype(bool) \
                  if "green_mesh" in df.columns else np.zeros(n, dtype=bool)
        # Trailing 252-bar high INCLUDING the current bar — matches
        # core/ml/feature_builder.py so live scores use the same definition.
        hi252_a = df["High"].rolling(253, min_periods=1).max().values.astype(np.float64)

    # ── Bar validity ──────────────────────────────────────────────────────────
    # The per-bar guard used to call np.isnan() seven times per iteration
    # (~15.5M ufunc dispatches over the universe). Same predicate, computed once.
    bad_bar_a = (np.isnan(ema200_a) | np.isnan(rsi_a) | np.isnan(adx_a) |
                 np.isnan(atr_a) | np.isnan(vsma_a) | np.isnan(hh12_a) |
                 np.isnan(ll50_a))

    # ── Vectorised signal conditions ──────────────────────────────────────────
    # Every entry predicate is elementwise, so it is computed once over the whole
    # series instead of ~20 scalar comparisons on each of ~2,500 bars per ticker.
    # NaN compares False in all of these, matching the scalar version; the
    # explicit isnan guards on hh12/ll12 are kept for parity with the original.
    with np.errstate(invalid="ignore"):
        _vol_ok_l = vol_a >= vsma_a * vol_ml
        _vol_ok_s = vol_a >= vsma_a * vol_ms
        _adx_ok_l = adx_a >= adx_min_l
        _adx_ok_s = adx_a >= adx_min_s
        _di_dom   = (din_a - dip_a) >= di_gap_min
        _room_ok  = (close_a - ll50_a) >= atr_a * room_atr

        pb_l_ok = (bull_a & (low_a <= ema21_a * pb_tol) & (close_a > ema21_a) &
                   (rsi_a >= rsi_pb_lo) & (rsi_a <= rsi_pb_hi) &
                   cbull_a & _adx_ok_l & _vol_ok_l)

        base_bo_ok = (bull_a & base_bo_a &
                      (rsi_a >= rsi_bo_lo) & (rsi_a <= rsi_bo_hi) &
                      bocb_a & _adx_ok_l &
                      (vol_a >= vsma_a * vol_ml * 1.2))   # stronger volume on base breaks

        bo_l_ok = (bull_a & ~np.isnan(hh12_a) & (close_a > hh12_a) &
                   (rsi_a >= rsi_bo_lo) & (rsi_a <= rsi_bo_hi) &
                   bocb_a & _adx_ok_l & _vol_ok_l)

        pb_s_ok = (bear_a & (high_a >= ema21_a * pbs_tol) & (close_a < ema21_a) &
                   (rsi_a >= rsi_pbs_lo) & (rsi_a <= rsi_pbs_hi) &
                   cbear_a & _adx_ok_s & _vol_ok_s & _di_dom & _room_ok)

        bo_s_ok = (bear_a & ~np.isnan(ll12_a) & (close_a < ll12_a) &
                   (rsi_a >= rsi_bos_lo) & (rsi_a <= rsi_bos_hi) &
                   bocs_a & _adx_ok_s & _vol_ok_s & _di_dom & _room_ok)

    # ── Hot-path lists ────────────────────────────────────────────────────────
    # The loop runs ~2,500 iterations per ticker. Indexing a numpy array from
    # Python boxes a numpy scalar on every access, which costs more than the
    # comparison it feeds. Plain lists of Python floats/bools index far faster.
    # Arrays touched only at trade events (sparse) are left as numpy.
    bad_bar  = bad_bar_a.tolist()
    close_l  = close_a.tolist()
    atr_l    = atr_a.tolist()
    ema21_l  = ema21_a.tolist()
    ema50_l  = ema50_a.tolist()
    pb_l_l     = pb_l_ok.tolist()
    base_bo_l  = base_bo_ok.tolist()
    bo_l_l     = bo_l_ok.tolist()
    pb_s_l     = pb_s_ok.tolist()
    bo_s_l     = bo_s_ok.tolist()
    breadth_l  = breadth_a.tolist() if breadth_a is not None else None

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
        c  = close_l[i]
        at = atr_l[i]

        if bad_bar[i]:
            if in_pos and c == c and entry_px > 0:   # c == c is a fast NaN test
                raw_pnl = (c / entry_px - 1.0) if direction == "long" \
                          else (entry_px / c - 1.0)
                pnl_pct = (raw_pnl - _rtc) * 100.0
                pnl_on_equity = (raw_pnl - _rtc) * position_pct * 100.0
                entry_ts = pd.Timestamp(entry_date)
                exit_ts  = pd.Timestamp(dates[i])
                trades.append({
                    "ticker": ticker, "direction": direction,
                    "signal_type": sig_type,
                    "entry_date": entry_ts, "exit_date": exit_ts,
                    "entry_price": round(entry_px, 4), "exit_price": round(c, 4),
                    "exit_reason": "DATA_GAP",
                    "atr_at_entry": round(entry_atr, 4),
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_on_equity": round(pnl_on_equity, 4),
                    "position_pct": round(position_pct * 100, 2),
                    "bars_held": max((exit_ts - entry_ts).days, 1),
                })
                in_pos = False
            continue

        # ── EXIT ──────────────────────────────────────────────────────────────
        if in_pos:
            exit_px     = None
            exit_reason = None

            if direction == "long":
                mesh_brk = (ema21_l[i - 1] > ema50_l[i - 1]) and (ema21_l[i] <= ema50_l[i])
                if mesh_brk:
                    exit_px, exit_reason = c, "MeshBreak"
                elif c <= sl_px:
                    exit_px, exit_reason = sl_px, "SL"
                elif c >= tp_px:
                    exit_px, exit_reason = tp_px, "TP"

            else:  # short
                mesh_brk = (ema21_l[i - 1] < ema50_l[i - 1]) and (ema21_l[i] >= ema50_l[i])
                if mesh_brk:
                    exit_px, exit_reason = c, "MeshBreak"
                elif c >= sl_px:
                    exit_px, exit_reason = sl_px, "SL"
                elif c <= tp_px:
                    exit_px, exit_reason = tp_px, "TP"

            if exit_px is not None and entry_px > 0:
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
            new_sig  = ""
            is_long  = False
            is_short = False

            # Conditions are precomputed as boolean arrays before the loop
            # (see "Vectorised signal conditions" above) — same predicates, same
            # priority order, ~20 scalar ops per bar removed.
            if pb_l_l[i]:
                new_sig, is_long = "PB-L", True
            elif base_bo_l[i]:
                new_sig, is_long = "BASE-BO", True
            elif bo_l_l[i]:
                new_sig, is_long = "BO-L", True
            elif pb_s_l[i]:
                new_sig, is_short = "PB-S", True

            elif bo_s_l[i]:
                new_sig, is_short = "BO-S", True

            # Breadth gate: in a narrow market breakouts are mostly false
            # breakouts. Suppress the named signal types; leave the rest running.
            if breadth_on and new_sig in breadth_sigs:
                b = breadth_l[i]
                if b == b and b < breadth_min:
                    new_sig, is_long, is_short = "", False, False

            # Regime gate: block new long entries when Nifty is below EMA200
            if is_long and market_regime is not None:
                try:
                    is_long = bool(market_regime.asof(pd.Timestamp(dates[i])))
                    if not is_long:
                        new_sig = ""
                except Exception as _e:
                    import warnings
                    warnings.warn(f"Regime gate error: {_e}")

            # ── ML gate ───────────────────────────────────────────────────────
            # Scored only at signal bars (sparse), using bar-i values only.
            if ml_on and (is_long or is_short) and _score_fn is not None:
                pfh = ((c - hi252_a[i]) / hi252_a[i]) if (i >= 20 and hi252_a[i] > 0) else 0.0
                prob = _score_fn({
                    "signal_type":   new_sig,
                    "direction":     "LONG" if is_long else "SHORT",
                    "rsi":           float(rsi_a[i]),
                    "adx":           float(adx_a[i]),
                    "vol_ratio":     float(vol_a[i]) / max(float(vsma_a[i]), 1e-6),
                    "atr":           float(at),
                    "entry":         float(c),
                    "pct_from_high": float(pfh),
                    "near_support":  bool(nsup_a[i]),
                    "bull_trend":    bool(bull_a[i]),
                    "green_mesh":    bool(gmesh_a[i]),
                })
                # Stricter gate when the market regime is bearish.
                thr = ml_thr
                if market_regime is not None:
                    try:
                        if not bool(market_regime.asof(pd.Timestamp(dates[i]))):
                            thr = ml_thr_bear
                    except Exception as _e:
                        import warnings
                        warnings.warn(f"ML regime threshold lookup failed: {_e}")
                if prob < thr:
                    is_long = is_short = False
                    new_sig = ""

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
