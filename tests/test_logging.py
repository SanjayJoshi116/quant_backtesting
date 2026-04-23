"""
Tests for core/logging.py — audit log writers.
"""

import csv
from pathlib import Path

import pytest

from core.logging import log_backtest_run, log_signal, _params_hash

_LOGS = Path(__file__).parent.parent / "logs"


# ── _params_hash ──────────────────────────────────────────────────────────────

def test_params_hash_is_deterministic(sample_config):
    assert _params_hash(sample_config) == _params_hash(sample_config)


def test_params_hash_length(sample_config):
    assert len(_params_hash(sample_config)) == 8


def test_params_hash_changes_on_param_change(sample_config):
    from core.config import StrategyConfig
    modified = sample_config.model_copy(update={"sl_mult": 99.9})
    assert _params_hash(sample_config) != _params_hash(modified)


# ── log_backtest_run ──────────────────────────────────────────────────────────

def test_log_backtest_run_creates_file():
    log_backtest_run(
        n_trades=100, sharpe=1.5, win_rate=55.0,
        profit_factor=1.4, max_dd=-20.0,
        start_date="2020-01-01", end_date="2025-12-31",
    )
    assert (_LOGS / "backtest_runs.csv").exists()


def test_log_backtest_run_schema():
    log_backtest_run(
        n_trades=50, sharpe=0.8, win_rate=48.0,
        profit_factor=1.1, max_dd=-35.0,
        start_date="2021-01-01", end_date="2026-01-01",
    )
    with open(_LOGS / "backtest_runs.csv") as f:
        reader = csv.DictReader(f)
        assert set(reader.fieldnames) == {
            "run_id", "timestamp", "config_version", "params_hash",
            "start_date", "end_date", "n_trades", "sharpe",
            "win_rate", "profit_factor", "max_dd", "results_path",
        }


def test_log_backtest_run_returns_uuid():
    run_id = log_backtest_run(
        n_trades=10, sharpe=2.0, win_rate=60.0,
        profit_factor=1.8, max_dd=-10.0,
        start_date="2022-01-01", end_date="2026-01-01",
    )
    assert len(run_id) == 36          # UUID4 string length
    assert run_id.count("-") == 4


def test_log_backtest_run_appends_rows():
    path = _LOGS / "backtest_runs.csv"
    rows_before = _row_count(path)
    log_backtest_run(
        n_trades=1, sharpe=0.1, win_rate=50.0,
        profit_factor=1.0, max_dd=-5.0,
        start_date="2023-01-01", end_date="2026-01-01",
    )
    assert _row_count(path) == rows_before + 1


def test_log_backtest_run_params_hash_consistent(sample_config):
    h1 = _params_hash(sample_config)
    run_id = log_backtest_run(
        n_trades=0, sharpe=0.0, win_rate=0.0,
        profit_factor=0.0, max_dd=0.0,
        start_date="2024-01-01", end_date="2026-01-01",
        cfg=sample_config,
    )
    # Read last row and verify hash matches
    with open(_LOGS / "backtest_runs.csv") as f:
        rows = list(csv.DictReader(f))
    last = rows[-1]
    assert last["run_id"] == run_id
    assert last["params_hash"] == h1


# ── log_signal ────────────────────────────────────────────────────────────────

_SAMPLE_SIG = {
    "ticker": "WIPRO.NS", "signal_type": "PB-L", "direction": "LONG",
    "entry": 290.5, "sl": 278.3, "tp": 323.0, "rr": 2.66, "score": 5,
}


def test_log_signal_creates_file():
    log_signal(_SAMPLE_SIG)
    assert (_LOGS / "signals.csv").exists()


def test_log_signal_schema():
    log_signal(_SAMPLE_SIG)
    with open(_LOGS / "signals.csv") as f:
        reader = csv.DictReader(f)
        assert set(reader.fieldnames) == {
            "signal_id", "timestamp", "ticker", "signal_type", "direction",
            "entry_price", "sl", "tp", "rr", "score",
            "config_version", "params_hash", "status",
        }


def test_log_signal_returns_uuid():
    sid = log_signal(_SAMPLE_SIG)
    assert len(sid) == 36
    assert sid.count("-") == 4


def test_log_signal_default_status_is_detected():
    log_signal(_SAMPLE_SIG)
    with open(_LOGS / "signals.csv") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["status"] == "DETECTED"


def test_log_signal_custom_status():
    log_signal(_SAMPLE_SIG, status="SENT")
    with open(_LOGS / "signals.csv") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["status"] == "SENT"


def test_log_signal_appends_rows():
    path = _LOGS / "signals.csv"
    rows_before = _row_count(path)
    log_signal(_SAMPLE_SIG)
    assert _row_count(path) == rows_before + 1


def test_log_signal_ticker_and_type_recorded():
    log_signal(_SAMPLE_SIG)
    with open(_LOGS / "signals.csv") as f:
        rows = list(csv.DictReader(f))
    last = rows[-1]
    assert last["ticker"] == "WIPRO.NS"
    assert last["signal_type"] == "PB-L"
    assert last["direction"] == "LONG"
    assert float(last["entry_price"]) == pytest.approx(290.5)


def test_log_signal_params_hash_matches_config(sample_config):
    expected_hash = _params_hash(sample_config)
    log_signal(_SAMPLE_SIG, cfg=sample_config)
    with open(_LOGS / "signals.csv") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["params_hash"] == expected_hash


# ── helpers ───────────────────────────────────────────────────────────────────

def _row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path) as f:
        return sum(1 for _ in f) - 1  # subtract header
