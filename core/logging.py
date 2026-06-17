"""
core/logging.py — Append-only CSV audit log writers.

Three logs, all in logs/:
  backtest_runs.csv  — one row per full backtest execution
  signals.csv        — one row per signal detected by the screener
  fetch_log.csv      — one row per data fetch (written by core/data.py)

Rows are never updated or deleted. Use run_id / signal_id (uuid4) to trace
a specific event back to the exact config and data that produced it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.config import load_config, StrategyConfig

_BASE = Path(__file__).parent.parent
_LOGS = _BASE / "logs"

# ── Column schemas ────────────────────────────────────────────────────────────

_BACKTEST_COLS = [
    "run_id", "timestamp", "config_version", "params_hash",
    "start_date", "end_date", "n_trades", "sharpe", "win_rate",
    "profit_factor", "max_dd", "results_path",
]

_SIGNAL_COLS = [
    "signal_id", "timestamp", "ticker", "signal_type", "direction",
    "entry_price", "sl", "tp", "rr", "score",
    "config_version", "params_hash", "status",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_logs() -> None:
    _LOGS.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _params_hash(cfg: StrategyConfig) -> str:
    """Stable 8-char hash of strategy parameters for traceability."""
    raw = json.dumps(cfg.to_params_dict(), sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()[:8]


def _append(path: Path, cols: list[str], row: dict) -> None:
    _ensure_logs()
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        if new_file:
            w.writeheader()
        w.writerow(row)


# ── Public writers ────────────────────────────────────────────────────────────

def log_backtest_run(
    n_trades:     int,
    sharpe:       float,
    win_rate:     float,
    profit_factor: float,
    max_dd:       float,
    start_date:   str,
    end_date:     str,
    results_path: str = "",
    cfg: StrategyConfig | None = None,
) -> str:
    """
    Append one row to logs/backtest_runs.csv.

    Returns the run_id (uuid4 string) for downstream reference.
    """
    if cfg is None:
        cfg = load_config()

    run_id = str(uuid.uuid4())
    _append(
        _LOGS / "backtest_runs.csv",
        _BACKTEST_COLS,
        {
            "run_id":         run_id,
            "timestamp":      _now(),
            "config_version": cfg.config_version,
            "params_hash":    _params_hash(cfg),
            "start_date":     start_date,
            "end_date":       end_date,
            "n_trades":       n_trades,
            "sharpe":         round(sharpe, 4),
            "win_rate":       round(win_rate, 2),
            "profit_factor":  round(profit_factor, 4),
            "max_dd":         round(max_dd, 2),
            "results_path":   results_path,
        },
    )
    return run_id


def log_signal(
    sig: dict,
    cfg: StrategyConfig | None = None,
    status: str = "DETECTED",
) -> str:
    """
    Append one row to logs/signals.csv for a detected signal.

    Parameters
    ----------
    sig    : signal dict returned by bot/signal_engine.detect()
    cfg    : StrategyConfig (defaults to load_config())
    status : "DETECTED" | "SENT" | "FAILED"

    Returns the signal_id for downstream reference.
    """
    if cfg is None:
        cfg = load_config()

    signal_id = str(uuid.uuid4())
    _append(
        _LOGS / "signals.csv",
        _SIGNAL_COLS,
        {
            "signal_id":      signal_id,
            "timestamp":      _now(),
            "ticker":         sig.get("ticker", ""),
            "signal_type":    sig.get("signal_type", ""),
            "direction":      sig.get("direction", ""),
            "entry_price":    sig.get("entry", ""),
            "sl":             sig.get("sl", ""),
            "tp":             sig.get("tp", ""),
            "rr":             sig.get("rr", ""),
            "score":          sig.get("score", ""),
            "config_version": cfg.config_version,
            "params_hash":    _params_hash(cfg),
            "status":         status,
        },
    )
    return signal_id
