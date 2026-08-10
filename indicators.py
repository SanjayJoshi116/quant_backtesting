"""
indicators.py — Indicator computation module.

All calculations are strictly causal (no lookahead bias).
All rolling/shift operations use only past data.

ASSUMPTIONS VS PINE SCRIPT:
  • Pine Script's `ta.ema` uses RMA (Wilder MA) for ATR/ADX internals but EMA
    for plain EMA calls. The `ta` library matches this behaviour.
  • Weekly EMA50 uses shift(1) before reindex so each daily bar sees only the
    last *completed* weekly bar (matches barmerge.lookahead_off).
  • `highest_high_12` and `lowest_low_12` are shifted by 1 bar to exclude the
    current bar (matches Pine's `ta.highest(high, 12)[1]`).
  • `lowest_low_50` is *not* shifted (current bar included), matching Pine's
    `ta.lowest(low, room_bars)` used in the room_to_fall calculation.
"""

import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange
from core.patterns import add_pattern_columns


# ── Weekly EMA50 ───────────────────────────────────────────────────────────────
def compute_weekly_ema50(df: pd.DataFrame) -> pd.Series:
    """
    Resample daily close to weekly (week-ending Friday), compute EMA50,
    shift by 1 completed week to avoid lookahead, then forward-fill to daily.
    """
    weekly_close = df["Close"].resample("W-FRI").last().dropna()

    if len(weekly_close) < 52:
        # Not enough weekly history — return NaN series
        return pd.Series(np.nan, index=df.index, name="weekly_ema50")

    w_ema50 = EMAIndicator(close=weekly_close, window=50, fillna=False).ema_indicator()

    # shift(1): use the value from the *last completed* weekly bar, not the current one
    w_ema50_lag = w_ema50.shift(1)

    # Reindex to daily frequency, forward-fill (last known weekly value)
    daily = w_ema50_lag.reindex(df.index).ffill()
    daily.name = "weekly_ema50"
    return daily


# ── Cheap re-derivation for parameter search ──────────────────────────────────
CHEAP_PARAMS = ("hh_window", "ll_window", "ll50_window",
                "bo_close_frac", "candle_frac")


def patch_indicators(df: pd.DataFrame, **overrides) -> pd.DataFrame:
    """
    Return a shallow copy of a prepared frame with only the columns affected by
    `overrides` recomputed. Supports CHEAP_PARAMS only — these derive directly
    from raw OHLCV and touch nothing downstream.

    A full prepare_indicators() over 869 tickers costs ~50s; this costs ~1s, so
    a grid over hh_window is practical. Anything touching ATR or the EMAs feeds
    bull_trend / near_support / the flat-base detector and must go through
    prepare_indicators() instead.
    """
    bad = set(overrides) - set(CHEAP_PARAMS)
    if bad:
        raise ValueError(
            f"patch_indicators cannot re-derive {sorted(bad)} — these feed "
            f"downstream columns. Use prepare_indicators(**params) instead.")

    out = df.copy(deep=False)

    if "hh_window" in overrides:
        w = int(overrides["hh_window"])
        out["highest_high_12"] = df["High"].rolling(w, min_periods=w).max().shift(1)
    if "ll_window" in overrides:
        w = int(overrides["ll_window"])
        out["lowest_low_12"] = df["Low"].rolling(w, min_periods=w).min().shift(1)
    if "ll50_window" in overrides:
        w = int(overrides["ll50_window"])
        out["lowest_low_50"] = df["Low"].rolling(w, min_periods=w).min()
    if "bo_close_frac" in overrides:
        f = float(overrides["bo_close_frac"])
        out["bo_candle_bull"] = (df["Close"] > df["Open"]) & (df["Close"] >= df["High"] * f)
        out["bo_candle_bear"] = (df["Close"] < df["Open"]) & (df["Close"] <= df["Low"] * (2.0 - f))
    if "candle_frac" in overrides:
        f = float(overrides["candle_frac"])
        hl = (df["High"] - df["Low"]).clip(lower=1e-8)
        out["candle_bull"] = (df["Close"] > df["Open"]) & ((df["Close"] - df["Low"]) / hl >= f)
        out["candle_bear"] = (df["Close"] < df["Open"]) & ((df["High"] - df["Close"]) / hl >= f)

    return out


# ── Main indicator factory ─────────────────────────────────────────────────────
_IND_KEYS = ("ema_fast", "ema_slow", "ema_long", "rsi_window", "adx_window",
             "atr_window", "vol_sma", "slope_lookback", "hh_window",
             "ll_window", "ll50_window", "candle_frac", "bo_close_frac")


def prepare_indicators(df: pd.DataFrame,
                       ema_fast: int | None = None,
                       ema_slow: int | None = None,
                       ema_long: int | None = None,
                       rsi_window: int | None = None,
                       adx_window: int | None = None,
                       atr_window: int | None = None,
                       vol_sma: int | None = None,
                       slope_lookback: int | None = None,
                       hh_window: int | None = None,
                       ll_window: int | None = None,
                       ll50_window: int | None = None,
                       candle_frac: float | None = None,
                       bo_close_frac: float | None = None) -> pd.DataFrame:
    """
    Compute all strategy indicators and derived columns.
    Input df must have columns: Open, High, Low, Close, Volume.
    Returns a new DataFrame with all indicator columns appended.

    Defaults reproduce the historical hardcoded values exactly, so existing
    callers are unaffected. They are arguments so the optimiser can search them:
    `hh_window` alone governs BO-L, which is 74% of all trades, and had never
    been tested at any value other than 12. See docs/PARAMETERS.md.
    """
    # Unset arguments fall back to config/strategy.yaml, so the backtester and
    # the live screener compute identical indicators from one source of truth.
    _local = locals()
    _cfg = None
    for _k in _IND_KEYS:
        if _local[_k] is None:
            if _cfg is None:
                from core.config import load_config
                _cfg = load_config()
            _local[_k] = getattr(_cfg, _k)
    (ema_fast, ema_slow, ema_long, rsi_window, adx_window, atr_window, vol_sma,
     slope_lookback, hh_window, ll_window, ll50_window, candle_frac,
     bo_close_frac) = (_local[_k] for _k in _IND_KEYS)

    df = df.copy()
    # Drop duplicate dates silently — some yfinance downloads contain them
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]

    # ── Core EMAs ─────────────────────────────────────────────────────────────
    df["EMA21"]  = EMAIndicator(close=df["Close"], window=ema_fast, fillna=False).ema_indicator()
    df["EMA50"]  = EMAIndicator(close=df["Close"], window=ema_slow, fillna=False).ema_indicator()
    df["EMA200"] = EMAIndicator(close=df["Close"], window=ema_long, fillna=False).ema_indicator()

    # ── RSI 14 ────────────────────────────────────────────────────────────────
    df["RSI"] = RSIIndicator(close=df["Close"], window=rsi_window, fillna=False).rsi()

    # ── ADX / DI+ / DI- (14) ──────────────────────────────────────────────────
    adx_ind     = ADXIndicator(
        high=df["High"], low=df["Low"], close=df["Close"],
        window=adx_window, fillna=False
    )
    df["ADX"]    = adx_ind.adx()
    df["DI_pos"] = adx_ind.adx_pos()
    df["DI_neg"] = adx_ind.adx_neg()

    # ── ATR 14 ────────────────────────────────────────────────────────────────
    df["ATR"] = AverageTrueRange(
        high=df["High"], low=df["Low"], close=df["Close"],
        window=atr_window, fillna=False
    ).average_true_range()

    # ── Volume SMA 20 ─────────────────────────────────────────────────────────
    df["VOL_SMA20"] = df["Volume"].rolling(window=vol_sma, min_periods=vol_sma).mean()

    # ── Weekly EMA 50 (higher-timeframe filter) ───────────────────────────────
    df["weekly_ema50"] = compute_weekly_ema50(df)
    df["weekly_bull"]  = df["Close"] > df["weekly_ema50"]
    df["weekly_bear"]  = df["Close"] < df["weekly_ema50"]

    # ── EMA slopes (5-bar look-back, strictly causal) ─────────────────────────
    df["ema21_slope"] = df["EMA21"] - df["EMA21"].shift(slope_lookback)
    df["ema50_slope"] = df["EMA50"] - df["EMA50"].shift(slope_lookback)

    # ── Mesh / trend composite ────────────────────────────────────────────────
    df["green_mesh"] = df["EMA21"] > df["EMA50"]
    df["red_mesh"]   = df["EMA21"] < df["EMA50"]

    df["bull_trend"] = (
        df["green_mesh"] &
        (df["EMA50"] > df["EMA200"]) &
        (df["ema21_slope"] > 0) &
        (df["ema50_slope"] > 0)
    )
    df["bear_trend"] = (
        df["red_mesh"] &
        (df["EMA50"] < df["EMA200"]) &
        (df["ema21_slope"] < 0) &
        (df["ema50_slope"] < 0)
    )

    # ── Candle quality ────────────────────────────────────────────────────────
    hl = (df["High"] - df["Low"]).clip(lower=1e-8)

    df["candle_bull"] = (
        (df["Close"] > df["Open"]) &
        ((df["Close"] - df["Low"]) / hl >= candle_frac)
    )
    df["candle_bear"] = (
        (df["Close"] < df["Open"]) &
        ((df["High"] - df["Close"]) / hl >= candle_frac)
    )
    df["bo_candle_bull"] = (
        (df["Close"] > df["Open"]) &
        (df["Close"] >= df["High"] * bo_close_frac)
    )
    df["bo_candle_bear"] = (
        (df["Close"] < df["Open"]) &
        (df["Close"] <= df["Low"] * (2.0 - bo_close_frac))
    )

    # ── Swing levels ──────────────────────────────────────────────────────────
    # shift(1): exclude current bar so the breakout condition is strictly
    # "close > the highest high of the previous 12 bars"  (no lookahead)
    df["highest_high_12"] = df["High"].rolling(window=hh_window, min_periods=hh_window).max().shift(1)
    df["lowest_low_12"]   = df["Low"].rolling(window=ll_window, min_periods=ll_window).min().shift(1)

    # NOT shifted: room_to_fall needs current bar's rolling low
    df["lowest_low_50"] = df["Low"].rolling(window=ll50_window, min_periods=ll50_window).min()

    # ── Chart patterns: swing S/R + flat base (requires ATR, computed above) ──
    add_pattern_columns(df)

    return df
