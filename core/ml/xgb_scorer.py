"""
core/ml/xgb_scorer.py

Walk-forward XGBoost signal scorer.

The model predicts P(win) for each signal at entry time.
It is used as a FILTER on top of the existing strategy — not a replacement.

Usage:
    python -m core.ml.xgb_scorer          # train + evaluate
    from core.ml.xgb_scorer import score_signal  # live scoring
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (classification_report,
                              precision_recall_fscore_support,
                              roc_auc_score)

try:
    import xgboost as xgb
except ImportError:
    raise ImportError("pip install xgboost")

from core.ml.feature_builder import FEATURE_COLS, build_features

MODEL_PATH  = Path("models/xgb_signal_scorer.joblib")
THRESH_PATH = Path("models/xgb_threshold.json")
MODEL_PATH.parent.mkdir(exist_ok=True)


# ── Model factory ─────────────────────────────────────────────────────────────

def _make_model(pos_weight: float = 1.0) -> xgb.XGBClassifier:
    return xgb.XGBClassifier(
        n_estimators      = 300,
        max_depth         = 4,       # shallow — avoids overfit on small data
        learning_rate     = 0.05,
        subsample         = 0.8,
        colsample_bytree  = 0.8,
        min_child_weight  = 10,      # require 10 samples per leaf
        scale_pos_weight  = pos_weight,
        eval_metric       = "logloss",
        random_state      = 42,
        verbosity         = 0,
    )


# ── Walk-forward validation ───────────────────────────────────────────────────

def walk_forward_validate(features: pd.DataFrame,
                          n_folds: int = 5,
                          threshold: float = 0.55) -> dict:
    """
    Time-ordered walk-forward: train on past, test on next window.
    This is the only correct way to validate a trading ML model.

    threshold: predict 'win' when P(win) >= threshold
    """
    features = features.sort_values("entry_date").reset_index(drop=True)
    n = len(features)
    fold_size = n // (n_folds + 1)

    fold_results = []
    print(f"\n  Walk-forward validation ({n_folds} folds, threshold={threshold})")
    print(f"  {'Fold':<6} {'Train':>6} {'Test':>5} {'Precision':>10} "
          f"{'Recall':>8} {'F1':>6} {'AUC':>6} {'Filter%':>8} {'WR_base':>8} {'WR_filt':>8}")
    print("  " + "-" * 80)

    for fold in range(n_folds):
        train_end   = fold_size * (fold + 1)
        test_start  = train_end
        test_end    = min(test_start + fold_size, n)

        tr = features.iloc[:train_end]
        te = features.iloc[test_start:test_end]

        if len(tr) < 50 or len(te) < 20:
            continue

        X_tr = tr[FEATURE_COLS].values.astype(np.float32)
        y_tr = tr["win"].values
        X_te = te[FEATURE_COLS].values.astype(np.float32)
        y_te = te["win"].values

        pos_weight = (y_tr == 0).sum() / max((y_tr == 1).sum(), 1)
        model = _make_model(pos_weight)
        model.fit(X_tr, y_tr, verbose=False)

        probs  = model.predict_proba(X_te)[:, 1]
        preds  = (probs >= threshold).astype(int)

        p, r, f, _ = precision_recall_fscore_support(
            y_te, preds, average="binary", zero_division=0)
        try:
            auc = roc_auc_score(y_te, probs)
        except Exception:
            auc = 0.5

        # Win rate: baseline vs filtered
        wr_base = float(y_te.mean()) * 100
        mask    = probs >= threshold
        wr_filt = float(y_te[mask].mean()) * 100 if mask.sum() > 0 else 0.0
        filter_pct = mask.mean() * 100

        fold_results.append({
            "fold": fold + 1, "n_train": len(tr), "n_test": len(te),
            "precision": p, "recall": r, "f1": f, "auc": auc,
            "wr_base": wr_base, "wr_filt": wr_filt, "filter_pct": filter_pct,
        })
        print(f"  {fold+1:<6} {len(tr):>6} {len(te):>5} {p:>10.3f} "
              f"{r:>8.3f} {f:>6.3f} {auc:>6.3f} {filter_pct:>7.1f}% "
              f"{wr_base:>7.1f}%  {wr_filt:>7.1f}%")

    if not fold_results:
        return {}

    avg = {k: float(np.mean([fr[k] for fr in fold_results]))
           for k in ["precision", "recall", "f1", "auc",
                     "wr_base", "wr_filt", "filter_pct"]}
    print(f"\n  {'AVG':<6} {'':>6} {'':>5} {avg['precision']:>10.3f} "
          f"{avg['recall']:>8.3f} {avg['f1']:>6.3f} {avg['auc']:>6.3f} "
          f"{avg['filter_pct']:>7.1f}% {avg['wr_base']:>7.1f}%  {avg['wr_filt']:>7.1f}%")

    wr_improvement = avg["wr_filt"] - avg["wr_base"]
    print(f"\n  Win rate improvement with filter: {wr_improvement:+.1f}pp")
    if avg["f1"] > 0.54 and wr_improvement > 2:
        print("  ✅ Model shows genuine edge — worth deploying")
    elif avg["f1"] > 0.50:
        print("  ⚠️  Marginal edge — monitor carefully")
    else:
        print("  ❌ No reliable edge — do not filter on this model")

    return {"folds": fold_results, "avg": avg}


# ── Feature importance ────────────────────────────────────────────────────────

def show_feature_importance(model: xgb.XGBClassifier) -> None:
    imp = model.feature_importances_
    ranked = sorted(zip(FEATURE_COLS, imp), key=lambda x: -x[1])
    print("\n  Feature importance:")
    for name, score in ranked:
        bar = "█" * int(score * 50)
        print(f"    {name:<20} {bar:<25} {score:.4f}")


# ── Train final model ─────────────────────────────────────────────────────────

def train_final_model(features: pd.DataFrame,
                      threshold: float = 0.55) -> xgb.XGBClassifier:
    """Train on ALL data for production deployment."""
    X = features[FEATURE_COLS].values.astype(np.float32)
    y = features["win"].values
    pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)

    model = _make_model(pos_weight)
    model.fit(X, y, verbose=False)
    joblib.dump(model, MODEL_PATH)
    json.dump({"threshold": threshold}, open(THRESH_PATH, "w"))
    print(f"  Model saved → {MODEL_PATH}")
    return model


# ── Live scoring ──────────────────────────────────────────────────────────────

_cached_model: xgb.XGBClassifier | None = None
_cached_threshold: float = 0.55


def score_signal(sig: dict) -> float:
    """
    Score a live signal dict. Returns P(win) in [0, 1].
    Returns 0.5 (neutral) if no model is available.
    """
    global _cached_model, _cached_threshold
    if _cached_model is None:
        if not MODEL_PATH.exists():
            return 0.5
        _cached_model = joblib.load(MODEL_PATH)
        if THRESH_PATH.exists():
            _cached_threshold = json.load(open(THRESH_PATH))["threshold"]

    enc = {"PB-L": 0, "BO-L": 1, "BASE-BO": 2, "PB-S": 4, "BO-S": 5}
    row = np.array([[
        enc.get(sig.get("signal_type", ""), 1),
        1 if sig.get("direction", "LONG") == "LONG" else 0,
        sig.get("rsi", 50.0),
        sig.get("adx", 20.0),
        sig.get("vol_ratio", 1.0),
        sig.get("atr", 5.0) / max(sig.get("entry", 100.0), 1e-6),
        sig.get("pct_from_high", -0.10),
        int(sig.get("near_support", False)),
        int(sig.get("bull_trend", True)),
        int(sig.get("green_mesh", True)),
    ]], dtype=np.float32)

    return round(float(_cached_model.predict_proba(row)[0][1]), 3)


def get_threshold() -> float:
    global _cached_threshold
    if THRESH_PATH.exists():
        _cached_threshold = json.load(open(THRESH_PATH))["threshold"]
    return _cached_threshold


# ── Backtest impact measurement ───────────────────────────────────────────────

def measure_sharpe_impact(features: pd.DataFrame,
                          threshold: float = 0.55) -> None:
    """
    Simulate: what happens to Sharpe if we only take signals
    where P(win) >= threshold?

    Uses the last 30% of data as the test set (most recent trades).
    """
    features = features.sort_values("entry_date").reset_index(drop=True)
    split    = int(len(features) * 0.70)
    train    = features.iloc[:split]
    test     = features.iloc[split:]

    X_tr = train[FEATURE_COLS].values.astype(np.float32)
    y_tr = train["win"].values
    X_te = test[FEATURE_COLS].values.astype(np.float32)

    pos_weight = (y_tr == 0).sum() / max((y_tr == 1).sum(), 1)
    model = _make_model(pos_weight)
    model.fit(X_tr, y_tr, verbose=False)

    probs = model.predict_proba(X_te)[:, 1]
    mask  = probs >= threshold

    def _sharpe(pnl: np.ndarray, ann: float = 252.0) -> float:
        if len(pnl) < 5 or pnl.std() == 0:
            return 0.0
        return float(pnl.mean() / pnl.std() * np.sqrt(ann / max(len(pnl), 1)))

    pnl_all  = test["pnl_on_equity"].values
    pnl_filt = test["pnl_on_equity"].values[mask]

    wr_all   = float((test["win"].values).mean()) * 100
    wr_filt  = float(test["win"].values[mask].mean()) * 100 if mask.sum() > 0 else 0
    pf_all   = (pnl_all[pnl_all > 0].sum() /
                abs(pnl_all[pnl_all <= 0].sum())) if (pnl_all <= 0).any() else 99
    pf_filt  = (pnl_filt[pnl_filt > 0].sum() /
                abs(pnl_filt[pnl_filt <= 0].sum())) if (pnl_filt <= 0).any() and len(pnl_filt) > 0 else 99

    print(f"\n  ── BACKTEST IMPACT (test set: last 30% = {len(test)} trades) ──")
    print(f"  {'Metric':<22} {'All signals':>12} {'ML-filtered':>12} {'Change':>10}")
    print("  " + "-" * 60)
    print(f"  {'Trades taken':<22} {len(pnl_all):>12} {mask.sum():>12} "
          f"{mask.sum()-len(pnl_all):>+10}")
    print(f"  {'Win rate':<22} {wr_all:>11.1f}% {wr_filt:>11.1f}% "
          f"{wr_filt-wr_all:>+9.1f}pp")
    print(f"  {'Profit factor':<22} {pf_all:>12.2f} {pf_filt:>12.2f} "
          f"{pf_filt-pf_all:>+10.2f}")
    print(f"  {'Sharpe (trade-based)':<22} {_sharpe(pnl_all):>12.2f} "
          f"{_sharpe(pnl_filt):>12.2f} "
          f"{_sharpe(pnl_filt)-_sharpe(pnl_all):>+10.2f}")
    print(f"  {'Avg pnl/trade':<22} {pnl_all.mean():>11.3f}% "
          f"{pnl_filt.mean():>11.3f}% "
          f"{pnl_filt.mean()-pnl_all.mean():>+9.3f}pp")
    print(f"  {'Signals kept':<22} {'100%':>12} {mask.mean()*100:>11.1f}% {'':>10}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    print("=" * 60)
    print("  XGBoost Signal Scorer — Training Pipeline")
    print("=" * 60)

    print("\n  Loading feature matrix...")
    features = build_features()
    print(f"  Total samples: {len(features)}")
    print(f"  Date range: {features['entry_date'].min().date()} → "
          f"{features['entry_date'].max().date()}")
    print(f"  Signal type distribution:")
    print(features["signal_type"].value_counts().to_string(header=False)
          .replace("\n", "\n    "))

    # Walk-forward validation
    results = walk_forward_validate(features, n_folds=5, threshold=0.55)

    # Feature importance (train on all data)
    X_all = features[FEATURE_COLS].values.astype(np.float32)
    y_all = features["win"].values
    pw    = (y_all == 0).sum() / max((y_all == 1).sum(), 1)
    m_imp = _make_model(pw)
    m_imp.fit(X_all, y_all, verbose=False)
    show_feature_importance(m_imp)

    # Sharpe impact
    measure_sharpe_impact(features, threshold=0.55)

    # Save if edge exists
    if results.get("avg", {}).get("f1", 0) > 0.50:
        print("\n  Saving production model...")
        train_final_model(features, threshold=0.55)
    else:
        print("\n  ⚠️  Model not saved — F1 below threshold")
