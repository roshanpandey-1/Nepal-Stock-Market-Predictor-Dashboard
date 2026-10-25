"""Why did a sector model say Buy, Sell or Hold for this stock today?

Two exact-or-near-exact SHAP-style attributions, written so the web process
needs nothing beyond the numpy / torch / xgboost it already imports (the
``shap`` package itself pulls in numba, pandas and scipy, which the free
host cannot afford -- see requirements-web.txt):

* XGBoost sectors -- XGBoost's own TreeSHAP (``pred_contribs=True``), which is
  exactly what ``shap.TreeExplainer`` computes for these models.
* LSTM sectors   -- expected gradients, the algorithm behind
  ``shap.GradientExplainer``: average of (x - baseline) * gradient along a
  straight line from a randomly chosen baseline day to today's window.

These are computed by scripts/build_explanations.py (run by GitHub Actions after
the daily price refresh and the weekly retrain) and saved to
models/explanations.json; the web server only reads that file. Computing them per
request was too heavy for the free host: the LSTM attribution runs the model
thousands of times and could exhaust its memory and take the site down.

Both explain the same number: the model's Buy score minus its Sell score (the
difference of the two output logits). Positive = pushed toward Buy, negative =
pushed toward Sell. ``attributions + baseline`` adds up to today's score, which
the tests check.

This describes what the model reacted to. It does NOT say the signal is right;
the reliability verdict (model_evidence.py) and the backtest page say that.
"""
import json
import pickle
from pathlib import Path

import numpy as np

BUY, SELL = 2, 0   # class indices used everywhere: 0 Sell, 1 Hold, 2 Buy

_LABELS = {
    "SMA_7": "7-day average price", "SMA_21": "21-day average price", "SMA_50": "50-day average price",
    "EMA_12": "12-day weighted average price", "EMA_26": "26-day weighted average price",
    "MACD": "MACD (trend momentum)", "MACD_Signal": "MACD signal line",
    "RSI_14": "RSI (overbought / oversold)", "Stoch": "Stochastic oscillator",
    "BB_High": "Upper Bollinger band", "BB_Low": "Lower Bollinger band", "BB_Width": "Bollinger band width",
    "ATR": "Average daily range (ATR)", "Volume_Change": "Change in trading volume", "OBV": "On-balance volume",
    "Close_lag_1": "Close 1 day ago", "Close_lag_3": "Close 3 days ago",
    "Close_lag_5": "Close 5 days ago", "Close_lag_10": "Close 10 days ago",
    "Return_lag_1": "Return over the last day", "Return_lag_3": "Return over 3 days",
    "Return_lag_5": "Return over 5 days", "Return_lag_10": "Return over 10 days",
}


def feature_label(name):
    return _LABELS.get(name, name.replace("_", " "))


def build_lstm(input_dim, hidden_dim=128, num_layers=2, dropout=0.3):
    """The sector LSTM architecture (same layers as api.signal and the trainer)."""
    import torch.nn as nn

    class StockLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim,
                                num_layers=num_layers, batch_first=True, dropout=dropout)
            self.classifier = nn.Sequential(nn.Linear(hidden_dim, 64), nn.ReLU(),
                                            nn.Dropout(0.2), nn.Linear(64, 3))

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.classifier(out[:, -1, :])

    return StockLSTM()


def xgb_attributions(model, x):
    """TreeSHAP for the Buy-minus-Sell margin of one feature row.

    Returns (per-feature attributions, baseline, score) with
    ``attributions.sum() + baseline == score``.
    """
    import xgboost as xgb
    x = np.asarray(x, dtype=float).reshape(1, -1)
    contribs = model.get_booster().predict(xgb.DMatrix(x), pred_contribs=True)
    contribs = np.asarray(contribs)[0]                    # (classes, features + 1); last column = bias
    diff = contribs[BUY] - contribs[SELL]
    return diff[:-1], float(diff[-1]), float(diff.sum())


def lstm_attributions(model, seq, background, n_samples=2000, seed=0):
    """Expected-gradients attribution of the Buy-minus-Sell logit for one window.

    ``seq`` is today's scaled (steps, features) window and ``background`` a
    stack of scaled windows from earlier days. Returns (per-feature
    attributions summed over the window's steps, baseline, score) where
    ``baseline`` is the model's average score over the background windows, so
    that attributions.sum() + baseline ~= score (exact only as n_samples grows).
    """
    import torch
    x = torch.as_tensor(np.asarray(seq, dtype=np.float32)).unsqueeze(0)           # (1, T, F)
    bg = torch.as_tensor(np.asarray(background, dtype=np.float32))                 # (B, T, F)
    gen = torch.Generator().manual_seed(seed)
    idx = torch.randint(0, bg.shape[0], (n_samples,), generator=gen)
    alpha = torch.rand(n_samples, 1, 1, generator=gen)
    base = bg[idx]
    point = (base + alpha * (x - base)).requires_grad_(True)

    def score(t):
        out = model(t)
        return out[:, BUY] - out[:, SELL]

    model.eval()
    grads = torch.autograd.grad(score(point).sum(), point)[0]
    attr = ((x - base) * grads).mean(dim=0)                                       # (T, F)
    with torch.no_grad():
        today = float(score(x).item())
        baseline = float(score(bg).mean().item())
    return attr.sum(dim=0).numpy(), baseline, today


def top_drivers(attr, names, values, k=8):
    """The k features with the largest effect, strongest first, in plain words."""
    attr = np.asarray(attr, dtype=float)
    total = float(np.abs(attr).sum()) or 1.0
    out = []
    for i in np.argsort(-np.abs(attr))[:k]:
        out.append({
            "feature": names[i], "label": feature_label(names[i]),
            "value": None if values is None or not np.isfinite(values[i]) else round(float(values[i]), 4),
            "effect": round(float(attr[i]), 4),
            "share_pct": round(100 * abs(float(attr[i])) / total, 1),
            "toward": "Buy" if attr[i] > 0 else "Sell",
        })
    return out


# --------------------------------------------------------------------------- batch build and lookup
EXPLANATIONS_FILE = "explanations.json"
BACKGROUND_DAYS = 60   # earlier days the LSTM explanation compares today against


def explain_ticker(rows, models_dir, drop_cols, lstm_sectors, seq_len=10, labels=("Sell", "Hold", "Buy")):
    """Explanation payload for one stock's feature rows (list of CSV dicts), or {"error": ...}.

    Uses the same saved model and the same latest rows as /api/signal.
    """
    models_dir = Path(models_dir)
    sector = rows[0].get("Sector") if rows else None
    if not sector:
        return {"error": "no sector for this stock"}
    name = sector.replace(" ", "_").replace("/", "_")
    feature_cols = [c for c in rows[0].keys() if c not in drop_cols]
    is_lstm = sector in lstm_sectors
    model_path = models_dir / (f"{name}_lstm_model_oos.pth" if is_lstm else f"{name}_xgb_model_oos.pkl")
    scaler_path = models_dir / f"{name}_scaler_oos.pkl"
    if not model_path.exists() or (is_lstm and not scaler_path.exists()):
        return {"error": "model not found for this sector"}

    def clean_row(r):
        try:
            return [float(r[c]) for c in feature_cols]
        except (ValueError, TypeError):
            return None

    if is_lstm:
        import torch
        usable = [(r, c) for r in rows[-(seq_len + BACKGROUND_DAYS + 5):] if (c := clean_row(r)) is not None]
        if len(usable) < seq_len + 10:
            return {"error": "not enough recent clean data to explain this signal"}
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        scaled = scaler.transform([c for _, c in usable])
        windows = np.stack([scaled[i - seq_len:i] for i in range(seq_len, len(scaled) + 1)])
        model = build_lstm(len(feature_cols))
        model.load_state_dict(torch.load(model_path, map_location="cpu"))
        model.eval()
        attr, baseline, score = lstm_attributions(model, windows[-1], windows[:-1][-BACKGROUND_DAYS:])
        with torch.no_grad():
            probs = torch.softmax(model(torch.FloatTensor(windows[-1]).unsqueeze(0)), dim=1).squeeze(0).tolist()
        values, as_of, method = usable[-1][1], usable[-1][0]["Date"], "expected_gradients"
        compared = f"this stock's own previous {len(windows) - 1} trading days"
    else:
        latest = next(((r, c) for r in reversed(rows) if (c := clean_row(r)) is not None), None)
        if latest is None:
            return {"error": "no clean recent row to explain"}
        with open(model_path, "rb") as f:
            model = pickle.load(f)
        attr, baseline, score = xgb_attributions(model, latest[1])
        probs = [float(p) for p in model.predict_proba([latest[1]])[0]]
        values, as_of, method = latest[1], latest[0]["Date"], "tree_shap"
        compared = "the average day in the model's training data"

    return {
        "sector": sector, "as_of": as_of, "method": method,
        "model_type": "LSTM" if is_lstm else "XGBoost",
        "signal": labels[int(max(range(3), key=lambda i: probs[i]))],
        "score": round(score, 3), "baseline": round(baseline, 3), "compared_with": compared,
        "drivers": top_drivers(attr, feature_cols, values, k=8),
    }


_FILE_CACHE = {"key": None, "data": {}}


def load_explanations(models_dir):
    """The prebuilt explanations file ({} if missing), re-read when it changes."""
    path = Path(models_dir) / EXPLANATIONS_FILE
    try:
        key = (str(path), path.stat().st_mtime)
        if _FILE_CACHE["key"] != key:
            _FILE_CACHE.update(key=key, data=json.loads(path.read_text(encoding="utf-8")))
        return _FILE_CACHE["data"]
    except (OSError, ValueError):
        return {}
