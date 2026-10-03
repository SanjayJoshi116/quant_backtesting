"""
Tests for tools/edge_reality_check.py — verdict logic, break-even
interpolation and period slicing, on hand-made inputs (no cached data needed).
"""

import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from edge_reality_check import (breakeven_slippage, breakeven_value, compute_verdict,
                                period_slices, yearly_returns, _fmt_criteria)
from core.config import load_config


@pytest.fixture
def cfg():
    return load_config()


def _m(**kw):
    base = {"cagr": 20.0, "sharpe": 1.0, "benchmark_cagr": 11.0,
            "breakeven_slippage": 0.004, "cagr_2016-2020": 10.0, "cagr_2021+": 25.0}
    base.update(kw)
    return base


def _results(rows):
    return {r["criterion"]: r["result"] for r in rows}


# ── Verdict ──────────────────────────────────────────────────────────────────

def test_verdict_survives_lists_every_criterion_as_pass(cfg):
    verdict, rows = compute_verdict(_m(), cfg)
    assert verdict == "SURVIVES"
    assert all(r["result"] == "PASS" for r in rows)
    names = {r["criterion"] for r in rows}
    assert {"Sharpe (daily, realistic)", "Break-even slippage per side",
            "CAGR vs Nifty 50 price CAGR", "Full-period CAGR",
            "CAGR 2016-2020", "CAGR 2021+"} <= names
    assert all("measured" in r and "threshold" in r for r in rows)


@pytest.mark.parametrize("period", ["cagr_2016-2020", "cagr_2021+"])
def test_negative_period_forces_fails(cfg, period):
    verdict, rows = compute_verdict(_m(**{period: -0.1}), cfg)
    assert verdict == "FAILS"


def test_zero_period_cagr_fails(cfg):
    assert compute_verdict(_m(**{"cagr_2021+": 0.0}), cfg)[0] == "FAILS"


def test_non_positive_full_cagr_fails(cfg):
    assert compute_verdict(_m(cagr=0.0), cfg)[0] == "FAILS"


def test_period_rule_can_be_disabled(cfg):
    c = cfg.model_copy(update={"fail_if_any_period_negative": False})
    verdict, rows = compute_verdict(_m(**{"cagr_2016-2020": -3.0}), c)
    assert verdict == "SURVIVES"
    assert "CAGR 2016-2020" not in _results(rows)


@pytest.mark.parametrize("kw,failed", [
    ({"sharpe": 0.49},                  "Sharpe (daily, realistic)"),
    ({"cagr": 10.0},                    "CAGR vs Nifty 50 price CAGR"),
    ({"breakeven_slippage": 0.0024},    "Break-even slippage per side"),
    ({"benchmark_cagr": None},          "CAGR vs Nifty 50 price CAGR"),
])
def test_one_survive_miss_is_marginal(cfg, kw, failed):
    verdict, rows = compute_verdict(_m(**kw), cfg)
    assert verdict == "MARGINAL"
    assert _results(rows)[failed] == "FAIL"


def test_thresholds_are_inclusive_where_stated(cfg):
    verdict, _ = compute_verdict(_m(sharpe=cfg.survive_min_sharpe,
                                    breakeven_slippage=cfg.survive_min_breakeven_slippage_pct), cfg)
    assert verdict == "SURVIVES"


def test_benchmark_criterion_skipped_when_disabled(cfg):
    c = cfg.model_copy(update={"survive_beat_benchmark": False})
    verdict, rows = compute_verdict(_m(cagr=5.0), c)
    assert verdict == "SURVIVES"
    assert "CAGR vs Nifty 50 price CAGR" not in _results(rows)


def test_criteria_formatting_shows_percent(cfg):
    _, rows = compute_verdict(_m(breakeven_slippage=math.inf), cfg)
    df = _fmt_criteria(rows).set_index("criterion")
    assert df.loc["Break-even slippage per side", "measured"] == "above sweep"
    assert df.loc["Break-even slippage per side", "threshold"] == ">= 0.25%"


# ── Break-even interpolation ────────────────────────────────────────────────

def test_breakeven_interpolated_between_bracketing_points():
    pts = [(0.0005, 4.0), (0.0010, 2.0), (0.0015, 1.0), (0.0025, -1.0), (0.0050, -5.0)]
    kind, x = breakeven_slippage(pts, 0.0)
    assert kind == "interpolated"
    assert x == pytest.approx(0.0020)          # halfway between 0.15% and 0.25%


def test_breakeven_above_range():
    pts = [(0.0005, 9.0), (0.0050, 1.0)]
    assert breakeven_slippage(pts, 0.0) == ("above_range", None)
    assert breakeven_value(("above_range", None)) == math.inf


def test_breakeven_below_range():
    pts = [(0.0005, -1.0), (0.0050, -9.0)]
    assert breakeven_slippage(pts, 0.0) == ("below_range", None)
    assert breakeven_value(("below_range", None)) == 0.0


def test_breakeven_against_benchmark_target():
    pts = [(0.0005, 15.0), (0.0015, 11.0), (0.0025, 7.0)]
    kind, x = breakeven_slippage(pts, 12.0)
    assert kind == "interpolated" and x == pytest.approx(0.00125)


# ── Periods ──────────────────────────────────────────────────────────────────

def test_period_slices_share_one_account():
    idx = pd.to_datetime(["2019-12-31", "2020-06-30", "2020-12-31", "2021-01-04", "2022-01-03"])
    eq = pd.Series([100.0, 110.0, 120.0, 121.0, 150.0], index=idx)
    s = period_slices(eq)
    assert s["2016-2020"].index.max() == pd.Timestamp("2020-12-31")
    # 2021+ starts from the 2020 year-end equity, not a fresh account.
    assert s["2021+"].iloc[0] == 120.0 and s["2021+"].iloc[-1] == 150.0


def test_yearly_returns_chain():
    idx = pd.to_datetime(["2020-01-02", "2020-12-31", "2021-12-31"])
    yr = yearly_returns(pd.Series([100.0, 110.0, 121.0], index=idx))
    assert yr.loc[2020] == pytest.approx(10.0) and yr.loc[2021] == pytest.approx(10.0)
