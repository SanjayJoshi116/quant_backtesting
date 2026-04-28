"""
core/config.py — Load and validate strategy parameters.

Usage (anywhere in the codebase):
    from core.config import load_config
    cfg = load_config()          # validated StrategyConfig object
    params = cfg.to_params_dict()  # flat dict compatible with backtester API
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "strategy.yaml"


class StrategyConfig(BaseModel):
    # ── Exit / risk ───────────────────────────────────────────────────────────
    sl_mult:        float = Field(gt=0, description="ATR multiplier for stop-loss")
    tp_mult_long:   float = Field(gt=0, description="ATR multiplier for long take-profit")
    tp_mult_short:  float = Field(gt=0, description="ATR multiplier for short take-profit")

    # ── Trend filters ─────────────────────────────────────────────────────────
    adx_long:     int   = Field(ge=0)
    adx_short:    int   = Field(ge=0)
    di_gap_min:   float = Field(ge=0)
    min_room_atr: float = Field(ge=0)

    # ── Entry: pullback EMA21 (PB-L) ─────────────────────────────────────────
    rsi_pb_lo: int   = Field(ge=0, le=100)
    rsi_pb_hi: int   = Field(ge=0, le=100)
    pb_tol:    float = Field(gt=1.0)

    # ── Entry: breakout (BO-L) ────────────────────────────────────────────────
    rsi_bo_lo: int = Field(ge=0, le=100)
    rsi_bo_hi: int = Field(ge=0, le=100)

    # ── Entry: short pullback (PB-S) ──────────────────────────────────────────
    rsi_pbs_lo:   int   = Field(ge=0, le=100)
    rsi_pbs_hi:   int   = Field(ge=0, le=100)
    pb_short_tol: float = Field(lt=1.0)

    # ── Entry: short breakout (BO-S) ──────────────────────────────────────────
    rsi_bos_lo: int = Field(ge=0, le=100)
    rsi_bos_hi: int = Field(ge=0, le=100)

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_mult_long:  float = Field(gt=0)
    vol_mult_short: float = Field(gt=0)

    # ── Data / cache ──────────────────────────────────────────────────────────
    data_period:     str = "2y"
    min_bars:        int = Field(gt=0)
    cache_ttl_hours: int = Field(gt=0)

    # ── Position sizing ───────────────────────────────────────────────────────
    starting_capital:   float = Field(gt=0,  default=100000.0)
    risk_per_trade_pct: float = Field(gt=0,  le=100, default=1.0)
    max_position_pct:   float = Field(gt=0,  le=100, default=20.0)

    # ── Market regime filter ──────────────────────────────────────────────────
    regime_enabled:    bool = True
    nifty_ema_period:  int  = Field(gt=0, default=200)

    # ── Execution costs ───────────────────────────────────────────────────────
    commission_pct: float = Field(ge=0, default=0.0005)
    slippage_pct:   float = Field(ge=0, default=0.0005)

    @model_validator(mode="after")
    def _check_rsi_ranges(self) -> "StrategyConfig":
        pairs = [
            ("rsi_pb_lo",  "rsi_pb_hi"),
            ("rsi_bo_lo",  "rsi_bo_hi"),
            ("rsi_pbs_lo", "rsi_pbs_hi"),
            ("rsi_bos_lo", "rsi_bos_hi"),
        ]
        for lo_field, hi_field in pairs:
            lo = getattr(self, lo_field)
            hi = getattr(self, hi_field)
            if lo >= hi:
                raise ValueError(f"{lo_field} ({lo}) must be < {hi_field} ({hi})")
        return self

    def to_params_dict(self) -> dict:
        """Flat dict compatible with the existing backtester params interface."""
        return {
            "sl_mult":        self.sl_mult,
            "tp_mult_long":   self.tp_mult_long,
            "tp_mult_short":  self.tp_mult_short,
            "adx_long":       self.adx_long,
            "adx_short":      self.adx_short,
            "rsi_pb_lo":      self.rsi_pb_lo,
            "rsi_pb_hi":      self.rsi_pb_hi,
            "rsi_bo_lo":      self.rsi_bo_lo,
            "rsi_bo_hi":      self.rsi_bo_hi,
            "rsi_pbs_lo":     self.rsi_pbs_lo,
            "rsi_pbs_hi":     self.rsi_pbs_hi,
            "rsi_bos_lo":     self.rsi_bos_lo,
            "rsi_bos_hi":     self.rsi_bos_hi,
            "vol_mult_long":  self.vol_mult_long,
            "vol_mult_short": self.vol_mult_short,
            "pb_tol":         self.pb_tol,
            "pb_short_tol":   self.pb_short_tol,
            "di_gap_min":     self.di_gap_min,
            "min_room_atr":   self.min_room_atr,
        }


# Module-level singleton — loaded once per process
_config: StrategyConfig | None = None


def load_config(path: Path | None = None) -> StrategyConfig:
    """Load and return the validated StrategyConfig singleton.

    Subsequent calls return the cached instance unless a custom path is given.
    Raises pydantic.ValidationError on bad values — fail fast at startup.
    """
    global _config
    if _config is not None and path is None:
        return _config

    p = path or _CONFIG_PATH
    with open(p, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    # Flatten nested YAML sections into a single dict
    flat: dict = {}
    for section in ("exit", "filters", "entry", "data", "regime", "sizing", "costs"):
        flat.update(raw.get(section, {}))

    # Rename 'period' → 'data_period' (avoid shadowing builtins)
    if "period" in flat:
        flat["data_period"] = flat.pop("period")

    cfg = StrategyConfig(**flat)
    if path is None:
        _config = cfg
    return cfg
