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
        adx_long=18, adx_short=20, di_gap_min=5.0, min_room_atr=3.0,
        rsi_pb_lo=35, rsi_pb_hi=58, pb_tol=1.008,
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
    assert cfg.adx_long == 18


def test_to_params_dict_has_all_keys():
    cfg = StrategyConfig(**_valid_kwargs())
    p = cfg.to_params_dict()
    required = {
        "sl_mult", "tp_mult_long", "tp_mult_short",
        "adx_long", "adx_short",
        "rsi_pb_lo", "rsi_pb_hi", "rsi_bo_lo", "rsi_bo_hi",
        "rsi_pbs_lo", "rsi_pbs_hi", "rsi_bos_lo", "rsi_bos_hi",
        "vol_mult_long", "vol_mult_short",
        "pb_tol", "pb_short_tol",
        "di_gap_min", "min_room_atr",
    }
    assert required <= set(p.keys())
    assert "rsi_pb50_lo" not in p, "PB50-L removed — pb50 keys must not be in params dict"


def test_to_params_dict_values_match_config():
    cfg = StrategyConfig(**_valid_kwargs())
    p = cfg.to_params_dict()
    assert p["sl_mult"] == cfg.sl_mult
    assert p["rsi_pb_lo"] == cfg.rsi_pb_lo
    assert p["vol_mult_long"] == cfg.vol_mult_long


# ── RSI range validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("lo_field,hi_field", [
    ("rsi_pb_lo",  "rsi_pb_hi"),
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
    """v1.2 params: WFO + manually tuned improvements."""
    cfg = load_config()
    assert cfg.sl_mult == 1.5,       "Expected sl_mult=1.5"
    assert cfg.tp_mult_long == 3.5,  "Expected tp_mult_long=3.5"
    assert cfg.adx_long == 18,       "Expected adx_long=18 (tightened in v1.1)"
    assert cfg.rsi_pb_lo == 35,      "Expected rsi_pb_lo=35"
    assert not hasattr(cfg, "rsi_pb50_lo"), "PB50-L removed in v1.2"


# ── Execution / fill model (edge-reality-check) ───────────────────────────────

def test_execution_defaults_preserve_v15_behaviour():
    cfg = StrategyConfig(**_valid_kwargs())
    assert cfg.entry_fill == "signal_close"
    assert cfg.exit_fill == "close_at_level"
    p = cfg.to_params_dict()
    assert p["entry_fill"] == "signal_close"
    assert p["exit_fill"] == "close_at_level"


def test_active_config_execution_is_default():
    """strategy.yaml keeps v1.5 fills so main.py output is unchanged."""
    cfg = load_config()
    assert cfg.entry_fill == "signal_close"
    assert cfg.exit_fill == "close_at_level"


@pytest.mark.parametrize("field,value", [
    ("entry_fill", "next_close"),
    ("exit_fill", "at_open"),
])
def test_invalid_fill_mode_raises_with_allowed_values(field, value):
    with pytest.raises(ValidationError) as exc:
        StrategyConfig(**{**_valid_kwargs(), field: value})
    msg = str(exc.value)
    assert value in msg
    allowed = ("signal_close", "next_open") if field == "entry_fill" \
        else ("close_at_level", "close_at_close", "intraday")
    for a in allowed:
        assert a in msg


def test_fill_mode_params_override_wins():
    cfg = StrategyConfig(**_valid_kwargs())
    p = cfg.to_params_dict()
    p.update({"entry_fill": "next_open"})
    assert p["entry_fill"] == "next_open"
    assert cfg.entry_fill == "signal_close"


def test_edge_check_criteria_loaded_from_yaml():
    cfg = load_config()
    assert cfg.realistic_slippage_pct == 0.0015
    assert cfg.survive_min_sharpe == 0.5
    assert cfg.survive_beat_benchmark is True
    assert cfg.survive_min_breakeven_slippage_pct == 0.0025
    assert cfg.fail_if_any_period_negative is True
    assert cfg.causal_min_turnover_cr == 25.0
