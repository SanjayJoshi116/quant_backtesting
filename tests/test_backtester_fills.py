"""
Tests for the backtester fill model (execution.entry_fill / execution.exit_fill).

Synthetic frames carry every indicator column run_backtest reads, set so that
no signal fires except where a test forces one. Each spec scenario in
openspec/changes/edge-reality-check/specs/backtest-execution-model is covered.
"""

import numpy as np
import pandas as pd
import pytest

from backtester import run_backtest, EXIT_FILLS

# Fixed so the arithmetic in each scenario is readable (ATR 4 → SL 6 away).
P = {"sl_mult": 1.5, "tp_mult_long": 3.0, "tp_mult_short": 2.0, "ml_enabled": False}


def make_frame(n: int = 10, px: float = 100.0, atr: float = 4.0) -> pd.DataFrame:
    """Flat, signal-free frame: no trend flags, no candles, no mesh break."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    f = pd.DataFrame(index=idx)
    for col in ("Open", "High", "Low", "Close"):
        f[col] = px
    f["Volume"]          = 1_000_000.0
    f["VOL_SMA20"]       = 500_000.0
    f["EMA21"], f["EMA50"], f["EMA200"] = 101.0, 100.0, 90.0
    f["RSI"]             = 55.0
    f["ADX"]             = 30.0
    f["DI_pos"], f["DI_neg"] = 10.0, 10.0
    f["ATR"]             = atr
    f["highest_high_12"] = 1e6
    f["lowest_low_12"]   = 0.0
    f["lowest_low_50"]   = 0.0
    for col in ("bull_trend", "bear_trend", "candle_bull", "candle_bear",
                "bo_candle_bull", "bo_candle_bear"):
        f[col] = False
    return f


def set_bar(f: pd.DataFrame, i: int, o=None, h=None, lo=None, c=None) -> None:
    """Set bar i's OHLC; unspecified fields default to the close."""
    c = f["Close"].iat[i] if c is None else c
    for col, v in (("Open", o), ("High", h), ("Low", lo), ("Close", c)):
        f.iloc[i, f.columns.get_loc(col)] = c if v is None else v
    if h is None:
        f.iloc[i, f.columns.get_loc("High")] = max(f["Open"].iat[i], c)
    if lo is None:
        f.iloc[i, f.columns.get_loc("Low")] = min(f["Open"].iat[i], c)


def long_signal(f: pd.DataFrame, i: int) -> None:
    """Force a BO-L signal on bar i (close breaks the 12-bar high)."""
    f.iloc[i, f.columns.get_loc("bull_trend")] = True
    f.iloc[i, f.columns.get_loc("bo_candle_bull")] = True
    f.iloc[i, f.columns.get_loc("highest_high_12")] = f["Close"].iat[i] - 1.0


def short_signal(f: pd.DataFrame, i: int) -> None:
    """Force a BO-S signal on bar i (close breaks the 12-bar low)."""
    for col, v in (("bear_trend", True), ("bo_candle_bear", True), ("RSI", 40.0),
                   ("DI_neg", 30.0), ("Volume", 2_000_000.0),
                   ("lowest_low_12", f["Close"].iat[i] + 1.0)):
        f.iloc[i, f.columns.get_loc(col)] = v


def bt(f, entry="signal_close", exit_="close_at_level", **extra):
    stats: dict = {}
    trades = run_backtest(f, params={**P, "entry_fill": entry, "exit_fill": exit_, **extra},
                          ticker="TEST.NS", stats=stats)
    return trades, stats


# ── Config / validation ──────────────────────────────────────────────────────

def test_invalid_mode_rejected_with_allowed_values():
    with pytest.raises(ValueError, match="close_at_level, close_at_close, intraday"):
        bt(make_frame(), exit_="at_the_moon")
    with pytest.raises(ValueError, match="signal_close, next_open"):
        bt(make_frame(), entry="tomorrow")


# ── Next-open entry ──────────────────────────────────────────────────────────

def test_next_open_fill_and_sl_level():
    f = make_frame()
    long_signal(f, 3)
    set_bar(f, 4, o=102.0, c=100.0)       # fill at 102; SL = 102 - 4*1.5 = 96
    set_bar(f, 5, c=96.5)                 # above the stop: still open
    set_bar(f, 6, c=95.9)                 # through the stop
    trades, stats = bt(f, entry="next_open")
    assert len(trades) == 1 and stats["unfilled"] == 0
    t = trades[0]
    assert t["entry_date"] == f.index[4]
    assert t["entry_price"] == 102.0
    assert t["exit_date"] == f.index[6]
    assert t["exit_reason"] == "SL" and t["exit_price"] == pytest.approx(96.0)
    assert t["atr_at_entry"] == 4.0


def test_next_open_uses_signal_bar_atr():
    f = make_frame()
    long_signal(f, 3)
    set_bar(f, 4, o=102.0)
    f.iloc[4, f.columns.get_loc("ATR")] = 40.0   # fill-bar ATR must be ignored
    set_bar(f, 5, c=95.9)
    trades, _ = bt(f, entry="next_open")
    assert trades[0]["exit_reason"] == "SL"
    assert trades[0]["exit_price"] == pytest.approx(96.0)


def test_signal_on_final_bar_is_unfilled():
    f = make_frame()
    long_signal(f, len(f) - 1)
    trades, stats = bt(f, entry="next_open")
    assert trades == [] and stats["unfilled"] == 1


def test_signal_before_gap_bar_is_unfilled():
    f = make_frame()
    long_signal(f, 3)
    f.iloc[4, f.columns.get_loc("ATR")] = np.nan
    trades, stats = bt(f, entry="next_open")
    assert trades == [] and stats["unfilled"] == 1


def test_signal_before_nan_open_is_unfilled():
    f = make_frame()
    long_signal(f, 3)
    f.iloc[4, f.columns.get_loc("Open")] = np.nan
    trades, stats = bt(f, entry="next_open")
    assert trades == [] and stats["unfilled"] == 1


def test_no_new_signal_while_pending():
    f = make_frame()
    long_signal(f, 3)
    long_signal(f, 4)                     # fires while bar 3's entry is pending
    set_bar(f, 6, c=90.0)
    trades, stats = bt(f, entry="next_open")
    assert len(trades) == 1 and trades[0]["entry_date"] == f.index[4]
    assert stats["unfilled"] == 0


# ── Exit fills ───────────────────────────────────────────────────────────────

def _long_at_106(f):
    """Long entered at close 106 on bar 3 with ATR 4 → SL 100, TP 118."""
    set_bar(f, 3, c=106.0)
    long_signal(f, 3)


def test_close_gap_through_stop_close_at_close():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=103.0, c=94.0)
    (t,), _ = bt(f, exit_="close_at_close")
    assert t["exit_reason"] == "SL" and t["exit_price"] == 94.0
    (t,), _ = bt(f, exit_="close_at_level")
    assert t["exit_reason"] == "SL" and t["exit_price"] == pytest.approx(100.0)


def test_intraday_open_gaps_below_stop():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=95.0, h=97.0, lo=93.0, c=97.0)
    (t,), _ = bt(f, exit_="intraday")
    assert t["exit_reason"] == "SL" and t["exit_price"] == 95.0


def test_intraday_stop_touched_without_gap():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=103.0, h=105.0, lo=99.0, c=104.0)
    (t,), _ = bt(f, exit_="intraday")
    assert t["exit_reason"] == "SL" and t["exit_price"] == pytest.approx(100.0)
    # Close-based modes never see the intraday touch.
    (t,), _ = bt(f, exit_="close_at_level")
    assert t["exit_date"] != f.index[4]


def test_intraday_sl_wins_when_bar_spans_both():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=106.0, h=130.0, lo=99.0, c=110.0)
    (t,), _ = bt(f, exit_="intraday")
    assert t["exit_reason"] == "SL" and t["exit_price"] == pytest.approx(100.0)


def test_intraday_tp_gap_fills_at_better_open():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=125.0, h=126.0, lo=124.0, c=125.0)
    (t,), _ = bt(f, exit_="intraday")
    assert t["exit_reason"] == "TP" and t["exit_price"] == 125.0


def test_intraday_short_gaps_above_stop():
    f = make_frame()
    set_bar(f, 3, c=94.0)                 # short at 94, ATR 4 → SL 100
    short_signal(f, 3)
    set_bar(f, 4, o=106.0, h=107.0, lo=105.0, c=106.0)
    (t,), _ = bt(f, exit_="intraday")
    assert t["direction"] == "short"
    assert t["exit_reason"] == "SL" and t["exit_price"] == 106.0


def test_meshbreak_stays_close_based_in_intraday():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=106.0, h=107.0, lo=105.0, c=105.5)
    f.iloc[4, f.columns.get_loc("EMA21")] = 99.0      # 21 crosses below 50
    (t,), _ = bt(f, exit_="intraday")
    assert t["exit_reason"] == "MeshBreak" and t["exit_price"] == 105.5


def test_data_gap_stays_close_based_and_records_modes():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, c=104.0)
    f.iloc[4, f.columns.get_loc("RSI")] = np.nan
    (t,), _ = bt(f, exit_="intraday")
    assert t["exit_reason"] == "DATA_GAP" and t["exit_price"] == 104.0
    assert t["entry_fill"] == "signal_close" and t["exit_fill"] == "intraday"


# ── Costs and records ────────────────────────────────────────────────────────

def test_identical_prices_give_identical_pnl_across_modes():
    f = make_frame()
    _long_at_106(f)
    set_bar(f, 4, o=100.0, h=100.0, lo=100.0, c=100.0)   # exactly at the stop
    results = [bt(f, exit_=m)[0][0] for m in EXIT_FILLS]
    assert {(t["entry_price"], t["exit_price"]) for t in results} == {(106.0, 100.0)}
    assert len({t["pnl_pct"] for t in results}) == 1
    assert len({t["pnl_on_equity"] for t in results}) == 1


def test_trade_records_carry_modes():
    f = make_frame()
    long_signal(f, 3)
    set_bar(f, 4, o=102.0)
    set_bar(f, 5, o=90.0, c=90.0)
    (t,), _ = bt(f, entry="next_open", exit_="intraday")
    assert (t["entry_fill"], t["exit_fill"]) == ("next_open", "intraday")


# ── No lookahead ─────────────────────────────────────────────────────────────

def _mutate_bar(f: pd.DataFrame, i: int) -> pd.DataFrame:
    """Scramble every non-NaN field of bar i so a signal decision reading it would change."""
    g = f.copy()
    for col in ("Open", "High", "Low", "Close", "EMA21", "EMA50", "EMA200",
                "highest_high_12", "lowest_low_12", "lowest_low_50"):
        g.iloc[i, g.columns.get_loc(col)] *= 1.37
    for col, v in (("Volume", 1.0), ("RSI", 5.0), ("ADX", 1.0)):
        g.iloc[i, g.columns.get_loc(col)] = v
    for col in ("bull_trend", "bear_trend", "candle_bull", "candle_bear",
                "bo_candle_bull", "bo_candle_bear"):
        g.iloc[i, g.columns.get_loc(col)] = not g[col].iat[i]
    return g


def test_no_lookahead_synthetic():
    f = make_frame()
    long_signal(f, 3)
    set_bar(f, 5, c=90.0)
    base, _ = bt(f)
    mut, _  = bt(_mutate_bar(f, 4))
    assert base[0]["entry_date"] == mut[0]["entry_date"] == f.index[3]
    assert base[0]["entry_price"] == mut[0]["entry_price"]


@pytest.mark.parametrize("entry", ["signal_close", "next_open"])
def test_no_lookahead_real_data(cached_ticker_df, entry):
    from indicators import prepare_indicators
    df = prepare_indicators(cached_ticker_df)
    shift = 1 if entry == "next_open" else 0
    base, _ = bt(df, entry=entry)
    if not base:
        pytest.skip("no trades on this frame")
    pos = {d: k for k, d in enumerate(df.index)}
    for t in base[:5]:
        sig_i = pos[t["entry_date"]] - shift
        if sig_i + 1 >= len(df):
            continue
        mut, _ = bt(_mutate_bar(df, sig_i + 1), entry=entry)
        before = [x["entry_date"] for x in base if pos[x["entry_date"]] <= sig_i + shift]
        after  = [x["entry_date"] for x in mut  if pos[x["entry_date"]] <= sig_i + shift]
        assert before == after, f"bar {sig_i + 1} changed the signal on bar {sig_i}"


# ── Regression against the v1.5 baseline ────────────────────────────────────

def test_default_modes_reproduce_v1_5_baseline():
    """Default fill modes must match the frozen v1.5 engine on the SAME data.

    This compares against tests/legacy/backtester_v1_5.py live rather than
    against the checked-in CSV. The CSV pins absolute adjusted prices, which
    move every time a constituent pays a dividend: re-measured on 2026-10-03 the
    fixture was off by a per-ticker constant (ESCORTS +1.13%, MUKANDLTD +2.14%,
    JYOTHYLAB +1.78%, …), and on PNCINFRA the rescale had shifted a marginal
    signal to a different bar. It also pins position_pct, which depends on
    sizing config and has nothing to do with the fill model.

    Running both engines over the same frames cancels both effects, so the test
    now checks the invariant it actually claims: defaults are bit-identical to
    v1.5. The fixture is kept for provenance and regenerated by
    `python -m tests.legacy.fill_baseline`.
    """
    from tests.legacy.backtester_v1_5 import run_backtest as run_v1_5
    from tests.legacy.fill_baseline import cases_available, run_cases
    if not cases_available():
        pytest.skip("cached price data for the baseline tickers is not present")

    exp = run_cases(run_v1_5)
    got = run_cases(run_backtest)

    assert (got["entry_fill"] == "signal_close").all()
    assert (got["exit_fill"] == "close_at_level").all()
    got = got.drop(columns=["entry_fill", "exit_fill"])

    assert list(got.columns) == list(exp.columns)
    assert len(got) == len(exp)
    for col in ("case", "ticker", "direction", "signal_type", "exit_reason"):
        assert (got[col].values == exp[col].values).all(), col
    for col in ("entry_date", "exit_date"):
        assert (pd.to_datetime(got[col]).values == exp[col].values).all(), col
    for col in ("entry_price", "exit_price", "atr_at_entry", "pnl_pct",
                "pnl_on_equity", "position_pct", "bars_held"):
        np.testing.assert_allclose(got[col].astype(float), exp[col].astype(float),
                                   rtol=0, atol=1e-9, err_msg=col)
