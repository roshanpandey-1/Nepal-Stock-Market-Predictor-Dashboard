"""Tests for the 'Why this signal?' explanations (app/explain.py and /api/explain/<ticker>)."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest

from app import explain

REPO = Path(__file__).resolve().parents[1]


def test_xgb_attributions_add_up_to_the_models_buy_minus_sell_margin():
    from xgboost import XGBClassifier
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 6))
    y = np.where(X[:, 0] > 0.4, 2, np.where(X[:, 1] < -0.4, 0, 1))
    model = XGBClassifier(n_estimators=40, max_depth=3, verbosity=0).fit(X, y)
    row = X[7]
    attr, base, score = explain.xgb_attributions(model, row)
    margins = model.get_booster().predict(__import__("xgboost").DMatrix(row.reshape(1, -1)), output_margin=True)[0]
    assert attr.sum() + base == pytest.approx(score, abs=1e-4)
    assert score == pytest.approx(margins[2] - margins[0], abs=1e-4)
    assert abs(attr[0]) + abs(attr[1]) > 3 * np.abs(attr[2:]).max() * 0.5  # the two features that built the labels lead


def test_expected_gradients_is_exact_for_a_linear_score_and_repeatable():
    torch = pytest.importorskip("torch")
    w = torch.randn(4, 3)

    class Lin(torch.nn.Module):
        def forward(self, x):                     # (N, steps=2, feats=2) -> three "logits"
            return x.reshape(x.shape[0], -1) @ w

    model = Lin()
    x = np.random.default_rng(1).normal(size=(2, 2)).astype(np.float32)
    bg = np.random.default_rng(2).normal(size=(1, 2, 2)).astype(np.float32)     # one baseline -> exact
    attr, base, score = explain.lstm_attributions(model, x, bg, n_samples=50)
    assert attr.sum() + base == pytest.approx(score, abs=1e-4)
    again, _, _ = explain.lstm_attributions(model, x, bg, n_samples=50)
    assert np.allclose(attr, again)


def test_top_drivers_orders_by_size_and_names_direction():
    out = explain.top_drivers(np.array([0.1, -0.5, 0.2]), ["RSI_14", "BB_Width", "OBV"], np.array([40.0, 9.0, np.nan]), k=2)
    assert [d["feature"] for d in out] == ["BB_Width", "OBV"]
    assert out[0]["toward"] == "Sell" and out[1]["toward"] == "Buy"
    assert out[0]["label"] == "Bollinger band width" and out[1]["value"] is None
    assert out[0]["share_pct"] == pytest.approx(62.5)


# ---------------- through the real saved models ----------------
@pytest.fixture
def client(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from app import api, create_app
    data = REPO / "deploy_data"
    monkeypatch.setattr(api, "MODELS_DIR", data / "models")
    monkeypatch.setattr(api, "PROCESSED_DIR", data / "processed")
    api._EXPLAIN_CACHE.clear()
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.parametrize("ticker,model_type", [("CHCL", "LSTM"), ("HDL", "XGBoost")])
def test_explain_endpoint_for_both_model_types(client, ticker, model_type):
    d = client.get(f"/api/explain/{ticker}").get_json()
    assert d["model_type"] == model_type and d["signal"] in ("Buy", "Sell", "Hold")
    assert len(d["drivers"]) == 8 and sum(x["share_pct"] for x in d["drivers"]) <= 100.01
    assert all(x["toward"] in ("Buy", "Sell") for x in d["drivers"])
    assert d["reliability"]["level"] in ("no_edge", "unproven", "tested", "unknown")
    assert client.get(f"/api/explain/{ticker}").get_json() == d     # repeat view (cached) is identical


def test_explain_unknown_ticker_is_404(client):
    assert client.get("/api/explain/NOPE").status_code == 404
