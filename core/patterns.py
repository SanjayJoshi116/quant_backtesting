"""
core/patterns.py — Chart pattern detection: swing pivots, S/R zones, flat bases.

All computations are strictly causal — only past bars are used at each step.

Columns added to the indicator DataFrame:
  last_pivot_high   float  price of the most recent confirmed swing high
  last_pivot_low    float  price of the most recent confirmed swing low
  near_support      bool   price within 1.5 ATR of a prior swing low
  near_resistance   bool   price within 1.5 ATR of a prior swing high
  in_flat_base      bool   last base_period bars form a tight consolidation
  base_high         float  top of the current base (breakout target)
  base_range_pct    float  base height as % of price
  base_quality      int    0-3 quality score (tightness, volume, duration)
  base_breakout     bool   today's close breaks above yesterday's base top
"""

from __future__ import annotations
import pandas as pd


# ── Swing pivot detection ─────────────────────────────────────────────────────

def _causal_pivots(
    high: pd.Series,
    low:  pd.Series,
    n:    int = 3,
) -> tuple[pd.Series, pd.Series]:
    """
    Return (pivot_high_price, pivot_low_price) — NaN where no pivot is confirmed.

    Causal logic: at bar j, bar (j-n) is a confirmed swing high if
    high[j-n] is the maximum of the 2n+1 bar window ending at bar j.
    This means we look n bars into the past to confirm, which is valid.
    """
    window = 2 * n + 1

    roll_max = high.rolling(window, min_periods=window).max()
    roll_min = low.rolling(window,  min_periods=window).min()

    # high shifted n bars back = high[j-n] at index j
    past_high = high.shift(n)
    past_low  = low.shift(n)

    is_ph = past_high >= roll_max   # bar j-n was max of 2n+1 window
    is_pl = past_low  <= roll_min   # bar j-n was min of 2n+1 window

    pivot_high_price = past_high.where(is_ph)   # NaN where not a pivot
    pivot_low_price  = past_low.where(is_pl)

    return pivot_high_price, pivot_low_price


# ── S/R proximity ─────────────────────────────────────────────────────────────

def _sr_proximity(
    close:             pd.Series,
    atr:               pd.Series,
    pivot_high_price:  pd.Series,
    pivot_low_price:   pd.Series,
    atr_mult:          float = 1.5,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Return (last_pivot_high, last_pivot_low, near_resistance, near_support).

    last_pivot_high/low: forward-filled so every bar has the most recent level.
    near_resistance/support: True when price is within atr_mult × ATR of level.
    """
    last_ph = pivot_high_price.ffill()
    last_pl = pivot_low_price.ffill()

    near_resistance = (close - last_ph).abs() <= atr * atr_mult
    near_support    = (close - last_pl).abs() <= atr * atr_mult

    return last_ph, last_pl, near_resistance.fillna(False), near_support.fillna(False)


# ── Flat base detection ───────────────────────────────────────────────────────

def _flat_base(
    high:          pd.Series,
    low:           pd.Series,
    close:         pd.Series,
    volume:        pd.Series,
    period:        int   = 15,   # min 3 trading weeks — short bases are noise
    max_range_pct: float = 5.0,  # tighter than typical daily range; real consolidation
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Return (in_flat_base, base_high, base_range_pct, base_quality, base_breakout).

    A flat base is period bars where:
      - (max_high - min_low) / close < max_range_pct%  → tight range
      - volume has contracted vs the prior period       → sellers exhausted

    base_quality 0-3:
      +1  range < max_range_pct (by definition if in_flat_base is True)
      +1  range < max_range_pct / 2  (very tight — high quality)
      +1  volume in base < 0.85 × volume before base   (clear contraction)

    base_breakout: previous bar was in a flat base AND current close > base_high
    (shift(1) ensures full causality — we can't know today whether we're still
     in a base until after the close).
    """
    base_max  = high.rolling(period, min_periods=period).max()
    base_min  = low.rolling(period,  min_periods=period).min()
    base_rng  = (base_max - base_min) / close.rolling(period).mean() * 100.0

    vol_in_base     = volume.rolling(period).mean()
    vol_before_base = volume.shift(period).rolling(period).mean()
    vol_contracting = vol_in_base < vol_before_base * 0.85

    # Tight range is the only mandatory condition.
    # Volume contraction improves quality but is not required —
    # many good bases form on low but steady volume.
    in_base = (base_rng < max_range_pct)

    # Quality score (0-3)
    q  = in_base.astype(int)                               # +1 for tight range
    q += (base_rng < max_range_pct / 2).astype(int)        # +1 for very tight range
    q += vol_contracting.fillna(False).astype(int)          # +1 for vol contraction
    quality = q.clip(0, 3)

    # Breakout: yesterday in base, today breaks above yesterday's base top
    breakout = in_base.shift(1).fillna(False) & (close > base_max.shift(1))

    return in_base, base_max, base_rng, quality, breakout


# ── Public API ────────────────────────────────────────────────────────────────

def add_pattern_columns(
    df:            pd.DataFrame,
    pivot_n:       int   = 3,
    base_period:   int   = 15,
    max_range_pct: float = 5.0,
    sr_atr_mult:   float = 1.5,
) -> pd.DataFrame:
    """
    Append chart pattern columns to an indicator DataFrame in-place.

    Requires columns: High, Low, Close, Volume, ATR (from prepare_indicators).
    """
    ph, pl = _causal_pivots(df["High"], df["Low"], n=pivot_n)

    last_ph, last_pl, near_res, near_sup = _sr_proximity(
        df["Close"], df["ATR"], ph, pl, atr_mult=sr_atr_mult
    )

    in_base, base_high, base_rng, base_q, base_bo = _flat_base(
        df["High"], df["Low"], df["Close"], df["Volume"],
        period=base_period, max_range_pct=max_range_pct,
    )

    df["last_pivot_high"]  = last_ph
    df["last_pivot_low"]   = last_pl
    df["near_resistance"]  = near_res
    df["near_support"]     = near_sup
    df["in_flat_base"]     = in_base
    df["base_high"]        = base_high
    df["base_range_pct"]   = base_rng
    df["base_quality"]     = base_q
    df["base_breakout"]    = base_bo

    return df
