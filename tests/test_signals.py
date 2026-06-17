"""
Tests for bot/signal_engine.py — detect() behaviour and output contract.
"""

import math
import pytest

from bot.signal_engine import detect, _build, SIGNAL_META


# ── detect() contract ─────────────────────────────────────────────────────────

def test_detect_returns_list(cached_ticker_df):
    result = detect(cached_ticker_df, "RELIANCE.NS")
    assert isinstance(result, list)


def test_detect_too_few_bars_returns_empty(ohlcv_df_short):
    result = detect(ohlcv_df_short, "TEST.NS")
    assert result == []


def test_detect_exactly_260_bars(ohlcv_df):
    """At exactly 260 bars detect() should attempt (not skip early)."""
    df_260 = ohlcv_df.iloc[-260:].copy()
    result = detect(df_260, "TEST.NS")
    assert isinstance(result, list)


def test_detect_output_has_required_keys(cached_ticker_df, sample_config):
    signals = detect(cached_ticker_df, "RELIANCE.NS")
    required_keys = {
        "ticker", "signal_type", "direction", "entry", "sl", "tp",
        "rr", "score", "atr", "rsi", "adx", "ema21", "ema50", "ema200",
        "date", "label", "emoji",
    }
    for sig in signals:
        missing = required_keys - set(sig.keys())
        assert not missing, f"Signal dict missing keys: {missing}"


def test_detect_signal_types_are_valid(cached_ticker_df):
    valid_types = set(SIGNAL_META.keys())
    for sig in detect(cached_ticker_df, "RELIANCE.NS"):
        assert sig["signal_type"] in valid_types


def test_detect_direction_matches_signal_type(cached_ticker_df):
    for sig in detect(cached_ticker_df, "RELIANCE.NS"):
        meta_dir = SIGNAL_META[sig["signal_type"]]["direction"]
        assert sig["direction"] == meta_dir


def test_detect_score_in_range(cached_ticker_df):
    for sig in detect(cached_ticker_df, "RELIANCE.NS"):
        assert 0 <= sig["score"] <= 6


def test_detect_sl_tp_sensible(cached_ticker_df):
    """For longs: sl < entry < tp. For shorts: tp < entry < sl."""
    for sig in detect(cached_ticker_df, "RELIANCE.NS"):
        if sig["direction"] == "LONG":
            assert sig["sl"] < sig["entry"] < sig["tp"], \
                f"Long SL/TP wrong: {sig['sl']} < {sig['entry']} < {sig['tp']}"
        else:
            assert sig["tp"] < sig["entry"] < sig["sl"], \
                f"Short SL/TP wrong: {sig['tp']} < {sig['entry']} < {sig['sl']}"


def test_detect_rr_positive(cached_ticker_df):
    for sig in detect(cached_ticker_df, "RELIANCE.NS"):
        assert sig["rr"] > 0


def test_detect_params_override(cached_ticker_df):
    """Passing custom params must not crash and must still return a list."""
    custom = {"adx_long": 999}  # impossibly high ADX — should suppress longs
    result = detect(cached_ticker_df, "RELIANCE.NS", params=custom)
    assert isinstance(result, list)
    for sig in result:
        assert sig["signal_type"] not in ("PB-L", "PB50-L", "BO-L")


# ── SIGNAL_META completeness ──────────────────────────────────────────────────

def test_signal_meta_has_all_types():
    expected = {"PB-L", "BASE-BO", "BO-L", "PB-S", "BO-S"}
    assert set(SIGNAL_META.keys()) == expected


def test_signal_meta_directions():
    for sig_type, meta in SIGNAL_META.items():
        assert meta["direction"] in ("LONG", "SHORT")
        assert meta["emoji"]
        assert meta["label"]


# ── _build() helper ───────────────────────────────────────────────────────────

def test_build_long_returns_correct_keys(cached_ticker_df, sample_config):
    from indicators import prepare_indicators
    df = prepare_indicators(cached_ticker_df)
    last = df.iloc[-1]

    if any(math.isnan(v) for v in [
        last["EMA200"], last["RSI"], last["ADX"], last["ATR"],
        last["VOL_SMA20"], last["highest_high_12"], last["lowest_low_50"]
    ]):
        pytest.skip("Last bar has NaN indicators — synthetic data edge case")

    p = sample_config.to_params_dict()
    result = _build(
        "TEST.NS", "PB-L",
        last["Close"], last["ATR"], last["RSI"], last["ADX"],
        last["Volume"], last["VOL_SMA20"],
        last["EMA21"], last["EMA50"], last["EMA200"],
        bool(last["weekly_bull"]), bool(last["green_mesh"]),
        df, p,
    )
    assert result["ticker"] == "TEST.NS"
    assert result["signal_type"] == "PB-L"
    assert result["direction"] == "LONG"
    assert result["sl"] < result["entry"] < result["tp"]
