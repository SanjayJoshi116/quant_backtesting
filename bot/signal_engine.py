"""
signal_engine.py — Detect strategy signals on the last completed bar.

Reuses the same indicator DataFrame that indicators.py produces, so the
logic is 100% consistent with the backtester.  Only the last row is
evaluated (today's completed daily bar).

Returns a list of SignalResult dicts — one per triggered signal type.
"""

import sys
import os
import math
import pandas as pd

# Allow imports from the project root (indicators.py lives there)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from indicators import prepare_indicators
from core.config import load_config

# ── Signal type metadata ───────────────────────────────────────────────────────
SIGNAL_META = {
    "PB-L":    {"label": "Pullback to EMA 21",       "direction": "LONG",  "emoji": "🟢"},
    "BO-L":    {"label": "Breakout above high",       "direction": "LONG",  "emoji": "🚀"},
    "BASE-BO": {"label": "Flat base breakout",        "direction": "LONG",  "emoji": "📦"},
    "PB-S":    {"label": "Pullback to EMA 21",        "direction": "SHORT", "emoji": "🔴"},
    "BO-S":    {"label": "Breakdown below low",       "direction": "SHORT", "emoji": "🔻"},
}


def _mesh_bars(ema21: pd.Series, ema50: pd.Series) -> int:
    """Count consecutive bars the mesh has been in its current state."""
    is_green = (ema21 > ema50).values
    current  = is_green[-1]
    count    = 1
    for j in range(2, min(len(is_green) + 1, 300)):
        if is_green[-j] == current:
            count += 1
        else:
            break
    return count


def detect(df_raw: pd.DataFrame, ticker: str, params: dict = None) -> list[dict]:
    """
    Run indicator computation + signal detection on df_raw.

    Parameters
    ----------
    df_raw  : OHLCV DataFrame with DatetimeIndex (from yfinance)
    ticker  : ticker symbol string (for display)
    params  : override strategy params (defaults to config.PARAMS)

    Returns
    -------
    List of signal dicts.  Empty list = no signal today.
    """
    p = load_config().to_params_dict()
    if params:
        p.update(params)

    if len(df_raw) < 260:
        return []

    # Accept pre-computed indicator df (has EMA21 col) to avoid double computation
    df = df_raw if "EMA21" in df_raw.columns else prepare_indicators(df_raw)

    # ── Pull last-bar values ───────────────────────────────────────────────────
    last = df.iloc[-1]

    c    = last["Close"]
    h    = last["High"]
    lo   = last["Low"]
    v    = last["Volume"]

    e21  = last["EMA21"]
    e50  = last["EMA50"]
    e200 = last["EMA200"]
    rsi  = last["RSI"]
    adx  = last["ADX"]
    dip  = last["DI_pos"]
    din  = last["DI_neg"]
    atr  = last["ATR"]
    vsma = last["VOL_SMA20"]
    hh12 = last["highest_high_12"]
    ll12 = last["lowest_low_12"]
    ll50 = last["lowest_low_50"]

    bull  = bool(last["bull_trend"])
    bear  = bool(last["bear_trend"])
    cbull = bool(last["candle_bull"])
    cbear = bool(last["candle_bear"])
    bocb  = bool(last["bo_candle_bull"])
    bocs  = bool(last["bo_candle_bear"])
    wbull = bool(last["weekly_bull"])
    green = bool(last["green_mesh"])

    # Pattern columns
    base_bo    = bool(last.get("base_breakout",  False))
    base_q     = int(last.get("base_quality",    0))

    # Skip bar if any critical indicator is NaN
    if any(math.isnan(x) for x in [e200, rsi, adx, atr, vsma, hh12, ll50]):
        return []

    # ── Shared filters ─────────────────────────────────────────────────────────
    adx_ok_l  = adx >= p["adx_long"]
    adx_ok_s  = adx >= p["adx_short"]
    vol_ok_l  = v   >= vsma * p["vol_mult_long"]
    vol_ok_s  = v   >= vsma * p["vol_mult_short"]
    di_dom    = (din - dip) >= p["di_gap_min"]
    room_ok   = (c - ll50)  >= atr * p["min_room_atr"]

    signals: list[dict] = []

    # ── PB-L  (Pullback to EMA21) ──────────────────────────────────────────────
    if (bull and
            lo <= e21 * p["pb_tol"] and c > e21 and
            p["rsi_pb_lo"] <= rsi <= p["rsi_pb_hi"] and
            cbull and adx_ok_l and vol_ok_l):
        signals.append(_build(ticker, "PB-L", c, atr, rsi, adx, v, vsma,
                               e21, e50, e200, wbull, green, df, p))

    # ── BASE-BO  (Flat base breakout) — checked before generic BO-L ─────────────
    elif (bull and base_bo and
            p["rsi_bo_lo"] <= rsi <= p["rsi_bo_hi"] and
            bocb and adx_ok_l and
            v >= vsma * p["vol_mult_long"] * 1.2):   # require stronger volume on base breaks
        signals.append(_build(ticker, "BASE-BO", c, atr, rsi, adx, v, vsma,
                               e21, e50, e200, wbull, green, df, p,
                               base_quality=base_q))

    # ── BO-L  (Breakout above 12-bar high) ────────────────────────────────────
    elif (bull and not math.isnan(hh12) and c > hh12 and
            p["rsi_bo_lo"] <= rsi <= p["rsi_bo_hi"] and
            bocb and adx_ok_l and vol_ok_l):
        signals.append(_build(ticker, "BO-L", c, atr, rsi, adx, v, vsma,
                               e21, e50, e200, wbull, green, df, p))

    # ── PB-S  (Pullback short) ─────────────────────────────────────────────────
    elif (bear and
            h >= e21 * p["pb_short_tol"] and c < e21 and
            p["rsi_pbs_lo"] <= rsi <= p["rsi_pbs_hi"] and
            cbear and adx_ok_s and vol_ok_s and di_dom and room_ok):
        signals.append(_build(ticker, "PB-S", c, atr, rsi, adx, v, vsma,
                               e21, e50, e200, wbull, green, df, p,
                               short=True))

    # ── BO-S  (Breakdown) ──────────────────────────────────────────────────────
    elif (bear and not math.isnan(ll12) and c < ll12 and
            p["rsi_bos_lo"] <= rsi <= p["rsi_bos_hi"] and
            bocs and adx_ok_s and vol_ok_s and di_dom and room_ok):
        signals.append(_build(ticker, "BO-S", c, atr, rsi, adx, v, vsma,
                               e21, e50, e200, wbull, green, df, p,
                               short=True))


    # ML gate. Off by default, so screener behaviour is unchanged until enabled.
    # Every signal still carries "ml_score" for display either way.
    if p.get("ml_enabled", False):
        signals = [s for s in signals if s.get("ml_pass", True)]

    return signals


# ── Builder helper ─────────────────────────────────────────────────────────────
def _build(ticker, sig_type, c, atr, rsi, adx, v, vsma,
           e21, e50, e200, wbull, green_mesh, df, p,
           short=False, base_quality=0) -> dict:

    sl_mult = p["sl_mult"]
    tp_mult = p["tp_mult_short"] if short else p["tp_mult_long"]

    if short:
        sl_price = round(c + atr * sl_mult, 2)
        tp_price = round(c - atr * tp_mult, 2)
    else:
        sl_price = round(c - atr * sl_mult, 2)
        tp_price = round(c + atr * tp_mult, 2)

    rr_ratio = round(abs(tp_price - c) / max(abs(c - sl_price), 0.01), 2)
    sl_pct   = round((sl_price / c - 1) * 100, 2)
    tp_pct   = round((tp_price / c - 1) * 100, 2)

    last      = df.iloc[-1]
    bull_trend = bool(last["bull_trend"])
    near_sup   = bool(last.get("near_support", False))

    # Signal score (0–7)
    # BASE-BO gets extra points from base_quality (0-3) instead of standard RSI check
    if sig_type == "BASE-BO":
        score = sum([
            1 if bull_trend                         else 0,   # trend
            1 if adx >= p["adx_long"]               else 0,   # ADX strength
            1 if v >= vsma * p["vol_mult_long"]      else 0,   # volume
            1 if wbull                               else 0,   # weekly trend
            1 if near_sup                            else 0,   # at support
            min(base_quality, 2),                             # base quality (0-2)
        ])
    else:
        score = sum([
            1 if bull_trend                                   else 0,   # trend
            1 if adx >= p["adx_long"]                        else 0,   # ADX
            1 if v >= vsma * p["vol_mult_long"]               else 0,   # volume
            1 if p["rsi_pb_lo"] <= rsi <= p["rsi_pb_hi"]     else 0,   # RSI in range
            1 if bool(last["candle_bull"])                    else 0,   # candle
            1 if wbull                                        else 0,   # weekly
            1 if near_sup                                     else 0,   # at support level
        ])

    mb = _mesh_bars(df["EMA21"], df["EMA50"])

    # ── Intraday move on signal bar (timing quality) ─────────────────────────
    bar_open = float(df["Open"].iloc[-1])
    intraday_move_pct = round((c - bar_open) / bar_open * 100, 1)

    # ── % drawdown from 52-week high ─────────────────────────────────────────
    recent_high = float(df["High"].iloc[:-1].rolling(252, min_periods=20).max().iloc[-1])
    pct_from_high = round((c - recent_high) / recent_high * 100, 1)

    # ── S/R test count — how many times has price tested the current support ─
    sr_test_count = 0
    sr_level = last.get("last_pivot_low", None)
    if sr_level and not math.isnan(float(sr_level)):
        lvl = float(sr_level)
        tol = lvl * 0.015   # 1.5% zone around the level
        sr_test_count = int(
            ((df["Low"].iloc[-200:] >= lvl - tol) &
             (df["Low"].iloc[-200:] <= lvl + tol)).sum()
        )

    sig = {
        "ticker":         ticker,
        "signal_type":    sig_type,
        "label":          SIGNAL_META[sig_type]["label"],
        "direction":      SIGNAL_META[sig_type]["direction"],
        "emoji":          SIGNAL_META[sig_type]["emoji"],
        "date":           df.index[-1].strftime("%d %b %Y"),
        "entry":          round(c, 2),
        "sl":             sl_price,
        "tp":             tp_price,
        "sl_pct":         sl_pct,
        "tp_pct":         tp_pct,
        "rr":             rr_ratio,
        "atr":            round(atr, 2),
        "rsi":            round(rsi, 1),
        "adx":            round(adx, 1),
        "vol_ratio":      round(v / vsma, 2),
        "ema21":          round(e21, 2),
        "ema50":          round(e50, 2),
        "ema200":         round(e200, 2),
        "weekly_bull":    wbull,
        "green_mesh":     green_mesh,
        "mesh_bars":      mb,
        "score":          score,
        "pct_from_high":      pct_from_high,
        "sr_test_count":      sr_test_count,
        "intraday_move_pct":  intraday_move_pct,
    }

    # ── ML score ─────────────────────────────────────────────────────────────
    # Always attached for visibility (screener shows it); only used to suppress
    # the signal when ml_enabled is on. Returns 0.5 if no model is trained.
    try:
        from core.ml.xgb_scorer import score_signal
        sig["ml_score"] = score_signal(sig)
    except Exception as e:
        import warnings
        warnings.warn(f"ML scoring failed for {ticker}: {e}")
        sig["ml_score"] = 0.5

    if p.get("ml_enabled", False):
        thr = float(p.get("ml_min_score", 0.50))
        sig["ml_pass"] = sig["ml_score"] >= thr
    else:
        sig["ml_pass"] = True

    return sig
