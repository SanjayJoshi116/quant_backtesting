"""
core/ml/kronos_features.py

Kronos-derived path features for signal scoring.

Kronos (https://github.com/shiyu-coder/Kronos, MIT) is a generative foundation
model for candlestick sequences. Vendored under vendor/kronos/.

For each signal bar we sample N independent future paths and then replay each one
through the SAME exit logic the backtester uses, producing a Monte-Carlo estimate
of the quantity the strategy actually depends on:

    P(take-profit hit before stop-loss)

Exit logic mirrors backtester.py exactly — close-only barriers, priority
MeshBreak -> SL -> TP. It is NOT an intrabar high/low touch.

Strictly causal: only bars up to and including the signal bar are ever fed to the
model. Note however that the PRE-TRAINED WEIGHTS may have seen market history
overlapping any backtest window — see LEAKAGE note below.

LEAKAGE
-------
HF weights NeoQuasar/Kronos-small were created 2025-06-30, last modified
2025-09-09. Treat any signal dated before ~2025-09-09 as potentially contaminated:
the model may have been trained on those very bars. Only post-cutoff signals give
an honest read. KRONOS_SAFE_CUTOFF below encodes this.

Usage:
    from core.ml.kronos_features import KronosScorer
    s = KronosScorer(lookback=256, n_paths=16)
    feats = s.path_features(hist_df, entry_price, atr, direction="long")
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import load_config

_ROOT = Path(__file__).resolve().parent.parent.parent
_VENDOR = _ROOT / "vendor" / "kronos"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

TOKENIZER_REPO = "NeoQuasar/Kronos-Tokenizer-base"
MODEL_REPO     = "NeoQuasar/Kronos-small"

# Weights last modified 2025-09-09; signals before this may be in-sample for Kronos.
KRONOS_SAFE_CUTOFF = pd.Timestamp("2025-09-09")

FEATURE_COLS_KRONOS = [
    "k_p_tp", "k_p_sl", "k_p_none", "k_exp_ret",
    "k_fwd_vol", "k_p_up", "k_mfe_atr", "k_mae_atr",
]

_PRICE_COLS = ["open", "high", "low", "close", "volume"]


def _ema_next(prev: float, price: float, span: int) -> float:
    a = 2.0 / (span + 1.0)
    return a * price + (1.0 - a) * prev


class KronosScorer:
    """Lazily-loaded Kronos predictor + path-feature extraction."""

    def __init__(self, lookback: int = 256, n_paths: int = 16,
                 pred_len: int = 24, device: str = "cpu",
                 temperature: float = 1.0, top_p: float = 0.9):
        self.lookback = lookback
        self.n_paths = n_paths
        self.pred_len = pred_len
        self.device = device
        self.temperature = temperature
        self.top_p = top_p
        self._pred = None

        cfg = load_config()
        p = cfg.to_params_dict()
        self.sl_mult = float(p["sl_mult"])
        self.tp_long = float(p["tp_mult_long"])
        self.tp_short = float(p["tp_mult_short"])

    # ── model ────────────────────────────────────────────────────────────────
    def _predictor(self):
        if self._pred is None:
            from model import Kronos, KronosTokenizer, KronosPredictor
            tok = KronosTokenizer.from_pretrained(TOKENIZER_REPO)
            mdl = Kronos.from_pretrained(MODEL_REPO)
            mdl.eval()
            tok.eval()
            self._pred = KronosPredictor(mdl, tok, device=self.device,
                                         max_context=self.lookback)
        return self._pred

    # ── path sampling ────────────────────────────────────────────────────────
    def sample_paths(self, hist: pd.DataFrame) -> np.ndarray | None:
        """
        hist: DataFrame indexed by date with lower-case OHLCV, ending AT the
              signal bar. Returns (n_paths, pred_len) array of simulated closes.

        predict() averages its internal samples, so we instead batch the same
        series n_paths times with sample_count=1 to get independent draws.
        """
        h = hist.iloc[-self.lookback:][_PRICE_COLS]
        if len(h) < self.lookback or h.isnull().values.any():
            return None
        pred = self._predictor()
        x_ts = pd.Series(h.index)
        y_ts = pd.Series(pd.bdate_range(h.index[-1] + pd.Timedelta(days=1),
                                        periods=self.pred_len))
        try:
            out = pred.predict_batch(
                [h] * self.n_paths, [x_ts] * self.n_paths, [y_ts] * self.n_paths,
                pred_len=self.pred_len, T=self.temperature, top_p=self.top_p,
                sample_count=1, verbose=False)
        except Exception as e:
            warnings.warn(f"Kronos predict_batch failed: {e}")
            return None
        return np.asarray([o["close"].values for o in out], dtype=np.float64)

    # ── barrier replay (mirrors backtester.py) ───────────────────────────────
    def _replay(self, closes: np.ndarray, entry: float, atr: float,
                direction: str, ema21_0: float, ema50_0: float) -> dict:
        long = direction == "long"
        sl_px = entry - atr * self.sl_mult if long else entry + atr * self.sl_mult
        tp_px = entry + atr * self.tp_long if long else entry - atr * self.tp_short

        n_tp = n_sl = n_mesh = 0
        mfes, maes, finals = [], [], []

        for path in closes:
            e21, e50 = ema21_0, ema50_0
            hit = None
            for c in path:
                p21, p50 = e21, e50
                e21 = _ema_next(e21, c, 21)
                e50 = _ema_next(e50, c, 50)
                mesh = (p21 > p50 and e21 <= e50) if long else (p21 < p50 and e21 >= e50)
                if mesh:
                    hit = "mesh"
                    break
                if long:
                    if c <= sl_px:
                        hit = "sl"
                        break
                    if c >= tp_px:
                        hit = "tp"
                        break
                else:
                    if c >= sl_px:
                        hit = "sl"
                        break
                    if c <= tp_px:
                        hit = "tp"
                        break
            if hit == "tp":
                n_tp += 1
            elif hit == "sl":
                n_sl += 1
            elif hit == "mesh":
                n_mesh += 1

            sign = 1.0 if long else -1.0
            exc = sign * (path - entry) / max(atr, 1e-9)
            mfes.append(float(exc.max()))
            maes.append(float(exc.min()))
            finals.append(sign * (float(path[-1]) / entry - 1.0))

        n = len(closes)
        finals = np.asarray(finals)
        return {
            "k_p_tp":    n_tp / n,
            "k_p_sl":    n_sl / n,
            "k_p_none":  (n - n_tp - n_sl) / n,     # includes MeshBreak + timeout
            "k_exp_ret": float(finals.mean()),
            "k_fwd_vol": float(finals.std()),
            "k_p_up":    float((finals > 0).mean()),
            "k_mfe_atr": float(np.mean(mfes)),
            "k_mae_atr": float(np.mean(maes)),
        }

    # ── public ───────────────────────────────────────────────────────────────
    def path_features(self, hist: pd.DataFrame, entry_price: float, atr: float,
                      direction: str, ema21: float, ema50: float) -> dict | None:
        """Sample paths and replay them. Returns None if the forecast failed."""
        if not np.isfinite([entry_price, atr, ema21, ema50]).all() or atr <= 0:
            return None
        closes = self.sample_paths(hist)
        if closes is None:
            return None
        return self._replay(closes, float(entry_price), float(atr),
                            direction, float(ema21), float(ema50))
