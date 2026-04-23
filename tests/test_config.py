"""
Tests for core/config.py — Pydantic validation and load_config().

These are the most critical tests: a bad strategy.yaml edit must fail
loudly at startup, never silently corrupt a live signal or backtest run.
"""

import pytest
from pydantic import ValidationError

from core.config import load_config, StrategyConfig


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _valid_kwargs() -> dict:
    """Return a complete set of valid StrategyConfig kwargs."""
    return dict(
        sl_mult=1.5, tp_mult_long=3.5, tp_mult_short=2.25,
        adx_long=12, adx_short=20, di_gap_min=5.0, min_room_atr=3.0,
        rsi_pb_lo=35, rsi_pb_hi=58, pb_tol=1.008,
        rsi_pb50_lo=38, rsi_pb50_hi=55, pb50_tol=1.005,
        rsi_bo_lo=48, rsi_bo_hi=75,
        rsi_pbs_lo=45, rsi_pbs_hi=60, pb_short_tol=0.997,
        rsi_bos_lo=30, rsi_bos_hi=50,
        vol_mult_long=1.1, vol_mult_short=1.3,
        data_period="2y", min_bars=260, cache_ttl_hours=24,
    )


# ── Happy-path ────────────────────────────────────────────────────────────────

def test_load_config_returns_strategy_config():
    cfg = load_config()
    assert isinstance(cfg, StrategyConfig)


def test_load_config_singleton():
    """Second call returns the same cached object."""
    cfg1 = load_config()
    cfg2 = load_config()
    assert cfg1 is cfg2


def test_valid_kwargs_builds_config():
    cfg = StrategyConfig(**_valid_kwargs())
    assert cfg.sl_mult == 1.5
    assert cfg.tp_mult_long == 3.5
    assert cfg.adx_long == 12


def test_to_params_dict_has_all_keys():
    cfg = StrategyConfig(**_valid_kwargs())
    p = cfg.to_params_dict()
    required = {
        "sl_mult", "tp_mult_long", "tp_mult_short",
        "adx_long", "adx_short",
        "rsi_pb_lo", "rsi_pb_hi", "rsi_bo_lo", "rsi_bo_hi",
        "rsi_pb50_lo", "rsi_pb50_hi",
        "rsi_pbs_lo", "rsi_pbs_hi", "rsi_bos_lo", "rsi_bos_hi",
        "vol_mult_long", "vol_mult_short",
        "pb_tol", "pb50_tol", "pb_short_tol",
        "di_gap_min", "min_room_atr",
    }
    assert required <= set(p.keys())


def test_to_params_dict_values_match_config():
    cfg = StrategyConfig(**_valid_kwargs())
    p = cfg.to_params_dict()
    assert p["sl_mult"] == cfg.sl_mult
    assert p["rsi_pb_lo"] == cfg.rsi_pb_lo
    assert p["vol_mult_long"] == cfg.vol_mult_long


# ── RSI range validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("lo_field,hi_field", [
    ("rsi_pb_lo",  "rsi_pb_hi"),
    ("rsi_pb50_lo","rsi_pb50_hi"),
    ("rsi_bo_lo",  "rsi_bo_hi"),
    ("rsi_pbs_lo", "rsi_pbs_hi"),
    ("rsi_bos_lo", "rsi_bos_hi"),
])
def test_rsi_range_lo_ge_hi_raises(lo_field, hi_field):
    kwargs = _valid_kwargs()
    kwargs[lo_field] = 70
    kwargs[hi_field] = 30
    with pytest.raises(ValidationError, match=lo_field):
        StrategyConfig(**kwargs)


@pytest.mark.parametrize("lo_field,hi_field", [
    ("rsi_pb_lo",  "rsi_pb_hi"),
    ("rsi_bo_lo",  "rsi_bo_hi"),
])
def test_rsi_range_equal_raises(lo_field, hi_field):
    kwargs = _valid_kwargs()
    kwargs[lo_field] = kwargs[hi_field] = 50
    with pytest.raises(ValidationError):
        StrategyConfig(**kwargs)


# ── Field-level validation ────────────────────────────────────────────────────

def test_negative_sl_mult_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "sl_mult": -1.0})


def test_zero_sl_mult_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "sl_mult": 0.0})


def test_pb_tol_below_one_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "pb_tol": 0.99})


def test_pb_short_tol_above_one_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "pb_short_tol": 1.01})


def test_negative_adx_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "adx_long": -5})


def test_zero_min_bars_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "min_bars": 0})


def test_rsi_out_of_range_raises():
    with pytest.raises(ValidationError):
        StrategyConfig(**{**_valid_kwargs(), "rsi_pb_lo": 110})


# ── Active config values match strategy.yaml ─────────────────────────────────

def test_active_config_wfo_values():
    """WFO-optimised params must be active (not the old defaults)."""
    cfg = load_config()
    assert cfg.sl_mult == 1.5,       "Expected WFO sl_mult=1.5"
    assert cfg.tp_mult_long == 3.5,  "Expected WFO tp_mult_long=3.5"
    assert cfg.adx_long == 12,       "Expected WFO adx_long=12"
    assert cfg.rsi_pb_lo == 35,      "Expected WFO rsi_pb_lo=35"
