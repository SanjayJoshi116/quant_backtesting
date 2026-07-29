"""
Tests for core/paper_trader.py — corporate-action reconciliation.

The behaviour under test: a position opened before a split ex-date holds
entry/SL/TP on the pre-split scale, while Yahoo has since divided the whole
cached history by the split factor. The tracker must rescale the stored levels
and keep tracking, not discard the position as corrupt data.

Dates are anchored to the real "today" so positions stay inside MAX_DAYS
without having to patch pandas' Timestamp (an extension type).
"""

import pandas as pd
import pytest

from core import paper_trader as pt

TODAY  = pd.Timestamp.today().normalize()
SIGNAL = TODAY - pd.Timedelta(days=10)      # comfortably inside MAX_DAYS
EX_1   = TODAY - pd.Timedelta(days=7)
EX_2   = TODAY - pd.Timedelta(days=3)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _bars(price: float, start: pd.Timestamp = SIGNAL, n: int = 11) -> pd.DataFrame:
    """Flat daily OHLC bars at `price`, starting on the signal date."""
    return pd.DataFrame(
        {"Open": price, "High": price, "Low": price,
         "Close": price, "Volume": 1_000_000.0},
        index=pd.date_range(start, periods=n, freq="D"),
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point PAPER_LOG at a temp file; returns a writer for seeding rows."""
    path = tmp_path / "paper_trades.csv"
    monkeypatch.setattr(pt, "PAPER_LOG", path)

    def write(**row) -> None:
        base = {c: "" for c in pt.COLUMNS}
        base.update(signal_date=SIGNAL.strftime("%Y-%m-%d"),
                    direction="LONG", status="OPEN")
        base.update(row)
        pd.DataFrame([base]).to_csv(path, index=False)

    return write


def _patch_data(monkeypatch, ohlc, splits) -> None:
    """Stub core.data so no network or disk cache is touched."""
    import core.data
    monkeypatch.setattr(core.data, "fetch_or_load", lambda t, force=False: ohlc)
    monkeypatch.setattr(core.data, "fetch_splits",  lambda t, force=False: splits)


def _row() -> pd.Series:
    return pd.read_csv(pt.PAPER_LOG).iloc[0]


# ── Split reconciliation ──────────────────────────────────────────────────────

def test_forward_split_rescales_levels_instead_of_erroring(ledger, monkeypatch):
    """1:5 split → stored levels divided by 5, position stays open."""
    ledger(ticker="SPLIT.NS", entry_price=1000.0, sl=900.0, tp=1200.0)
    # Post-split cache: the whole history is 1/5 the pre-split scale.
    _patch_data(monkeypatch, _bars(200.0), pd.Series([5.0], index=[EX_1]))

    counts = pt.update_open_positions()
    row = _row()

    assert counts["split_adjusted"] == 1
    assert counts["data_error"] == 0
    assert row["status"] == "OPEN"
    assert row["entry_price"] == pytest.approx(200.0)
    assert row["sl"]          == pytest.approx(180.0)
    assert row["tp"]          == pytest.approx(240.0)
    assert row["split_adj"]   == pytest.approx(5.0)


def test_reverse_split_rescales_upward(ledger, monkeypatch):
    """100:1 consolidation → stored levels multiplied by 100."""
    ledger(ticker="REV.NS", entry_price=2.0, sl=1.8, tp=2.4)
    _patch_data(monkeypatch, _bars(200.0), pd.Series([0.01], index=[EX_1]))

    pt.update_open_positions()
    row = _row()

    assert row["status"] == "OPEN"
    assert row["entry_price"] == pytest.approx(200.0)
    assert row["sl"]          == pytest.approx(180.0)


def test_unexplained_mismatch_defers_instead_of_killing_the_position(
        ledger, monkeypatch):
    """
    A mismatch no split explains is usually one bad fetch. Inside the trade
    window the position must survive untouched for the next run to retry —
    a single poisoned batch once closed 38 live positions this way.
    """
    ledger(ticker="BAD.NS", entry_price=1000.0, sl=900.0, tp=1200.0)
    _patch_data(monkeypatch, _bars(200.0), pd.Series(dtype="float64"))

    counts = pt.update_open_positions()
    row = _row()

    assert counts["deferred"] == 1
    assert counts["data_error"] == 0
    assert row["status"] == "OPEN"
    assert row["entry_price"] == pytest.approx(1000.0)   # left untouched


def test_mismatch_past_the_window_becomes_data_error(ledger, monkeypatch):
    """Once the trade window has run out, no refresh will rescue it."""
    old = TODAY - pd.Timedelta(days=pt.MAX_DAYS + 5)
    ledger(ticker="DEAD.NS", entry_price=1000.0, sl=900.0, tp=1200.0,
           signal_date=old.strftime("%Y-%m-%d"))
    _patch_data(monkeypatch, _bars(200.0, start=old, n=pt.MAX_DAYS + 6),
                pd.Series(dtype="float64"))

    counts = pt.update_open_positions()
    row = _row()

    assert counts["data_error"] == 1
    assert row["status"] == "DATA_ERROR"
    assert str(row["exit_reason"]).startswith("PRICE_MISMATCH")


def test_split_of_wrong_size_is_not_trusted(ledger, monkeypatch):
    """A 1:2 split cannot explain a 5x mismatch — don't rescale on it."""
    ledger(ticker="ODD.NS", entry_price=1000.0, sl=900.0, tp=1200.0)
    _patch_data(monkeypatch, _bars(200.0), pd.Series([2.0], index=[EX_1]))

    counts = pt.update_open_positions()
    assert counts["split_adjusted"] == 0
    assert counts["deferred"] == 1
    assert _row()["entry_price"] == pytest.approx(1000.0)


def test_split_before_signal_date_is_ignored(ledger, monkeypatch):
    """Only ex-dates AFTER entry affect a position's stored scale."""
    ledger(ticker="OLD.NS", entry_price=1000.0, sl=900.0, tp=1200.0)
    _patch_data(monkeypatch, _bars(200.0),
                pd.Series([5.0], index=[SIGNAL - pd.Timedelta(days=60)]))

    counts = pt.update_open_positions()
    assert counts["split_adjusted"] == 0
    assert counts["deferred"] == 1


def test_second_split_does_not_reapply_the_first(ledger, monkeypatch):
    """
    A position already adjusted for a 1:5 then sees a 1:2. Only the outstanding
    2x may be applied — the cumulative factor becomes 10, not 50.
    """
    ledger(ticker="TWICE.NS", entry_price=200.0, sl=180.0, tp=240.0,
           split_adj=5.0)   # 1:5 already folded in by an earlier run
    _patch_data(monkeypatch,
                _bars(100.0),                        # now 1/10 of original scale
                pd.Series([5.0, 2.0], index=[EX_1, EX_2]))

    pt.update_open_positions()
    row = _row()

    assert row["entry_price"] == pytest.approx(100.0)   # 200 / 2, not 200 / 10
    assert row["sl"]          == pytest.approx(90.0)
    assert row["split_adj"]   == pytest.approx(10.0)


def test_rescaled_position_resolves_on_the_adjusted_scale(ledger, monkeypatch):
    """After rescaling, the SL/TP replay must use post-split bars correctly."""
    ledger(ticker="HIT.NS", entry_price=1000.0, sl=900.0, tp=1200.0)
    ohlc = _bars(200.0)
    ohlc.iloc[5, ohlc.columns.get_loc("High")] = 260.0   # clears the 240 target
    _patch_data(monkeypatch, ohlc, pd.Series([5.0], index=[EX_1]))

    counts = pt.update_open_positions()
    row = _row()

    assert counts["tp_hit"] == 1
    assert row["status"] == "TP_HIT"
    assert row["exit_price"] == pytest.approx(240.0)
    assert row["pnl_pct"] == pytest.approx(20.0, abs=0.01)


def test_matching_price_needs_no_split_lookup(ledger, monkeypatch):
    """Within tolerance → untouched, and fetch_splits is never consulted."""
    ledger(ticker="FINE.NS", entry_price=200.0, sl=180.0, tp=240.0)

    def _boom(*a, **k):
        raise AssertionError("fetch_splits called for a well-matched price")

    import core.data
    monkeypatch.setattr(core.data, "fetch_or_load", lambda t, force=False: _bars(200.0))
    monkeypatch.setattr(core.data, "fetch_splits", _boom)

    counts = pt.update_open_positions()
    assert counts["data_error"] == 0
    assert _row()["status"] == "OPEN"


# ── Holding window ────────────────────────────────────────────────────────────

def test_hit_outside_the_window_does_not_resolve_the_trade(ledger, monkeypatch):
    """
    A target touched after day MAX_DAYS must not count. A skipped run once let
    12 positions keep running until they happened to hit SL or TP.
    """
    old = TODAY - pd.Timedelta(days=pt.MAX_DAYS + 10)
    ledger(ticker="LATE.NS", entry_price=100.0, sl=90.0, tp=120.0,
           signal_date=old.strftime("%Y-%m-%d"))
    ohlc = _bars(100.0, start=old, n=pt.MAX_DAYS + 11)
    ohlc.iloc[pt.MAX_DAYS + 5, ohlc.columns.get_loc("High")] = 130.0   # past day 30
    _patch_data(monkeypatch, ohlc, pd.Series(dtype="float64"))

    counts = pt.update_open_positions()
    row = _row()

    assert counts["tp_hit"] == 0
    assert row["status"] == "EXPIRED"
    assert float(row["days_held"]) <= pt.MAX_DAYS


def test_hit_inside_the_window_still_resolves(ledger, monkeypatch):
    """The cap must not swallow a legitimate in-window hit."""
    old = TODAY - pd.Timedelta(days=pt.MAX_DAYS + 10)
    ledger(ticker="INTIME.NS", entry_price=100.0, sl=90.0, tp=120.0,
           signal_date=old.strftime("%Y-%m-%d"))
    ohlc = _bars(100.0, start=old, n=pt.MAX_DAYS + 11)
    ohlc.iloc[3, ohlc.columns.get_loc("High")] = 130.0
    _patch_data(monkeypatch, ohlc, pd.Series(dtype="float64"))

    counts = pt.update_open_positions()
    row = _row()

    assert counts["tp_hit"] == 1
    assert row["exit_price"] == pytest.approx(120.0)
    assert float(row["days_held"]) == 3


def test_expiry_exits_on_the_last_in_window_bar(ledger, monkeypatch):
    """A late-resolved expiry must price off day 30, not off today."""
    old = TODAY - pd.Timedelta(days=pt.MAX_DAYS + 10)
    ledger(ticker="EXP.NS", entry_price=100.0, sl=90.0, tp=120.0,
           signal_date=old.strftime("%Y-%m-%d"))
    ohlc = _bars(100.0, start=old, n=pt.MAX_DAYS + 11)
    # Drift after the window closes — must not leak into the exit price.
    ohlc.iloc[pt.MAX_DAYS + 1:, ohlc.columns.get_loc("Close")] = 115.0
    _patch_data(monkeypatch, ohlc, pd.Series(dtype="float64"))

    pt.update_open_positions()
    row = _row()

    assert row["status"] == "EXPIRED"
    assert row["exit_price"] == pytest.approx(100.0)
    assert pd.Timestamp(row["exit_date"]) <= old + pd.Timedelta(days=pt.MAX_DAYS)


# ── Schema ────────────────────────────────────────────────────────────────────

def test_load_backfills_missing_split_adj_column(ledger):
    """A ledger written before split_adj existed must still load."""
    old_cols = [c for c in pt.COLUMNS if c != "split_adj"]
    pd.DataFrame([{c: "" for c in old_cols}]).to_csv(pt.PAPER_LOG, index=False)

    assert "split_adj" in pt._load().columns
