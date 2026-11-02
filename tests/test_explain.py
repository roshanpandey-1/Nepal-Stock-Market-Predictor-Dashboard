"""Tests for the 'Why this signal?' explanations (app/backend/explain.py and /api/explain/<ticker>)."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest

from app.backend import explain

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


# ---------------- built offline from the real saved models ----------------
@pytest.mark.parametrize("ticker,model_type", [("CHCL", "LSTM"), ("HDL", "XGBoost")])
def test_explain_ticker_with_the_deployed_models(ticker, model_type):
    pytest.importorskip("torch")
    import csv
    data = REPO / "deploy_data"
    with open(data / "processed" / f"{ticker}_features.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    d = explain.explain_ticker(rows, data / "models")
    assert d["model_type"] == model_type and d["signal"] in ("Buy", "Sell", "Hold")
    assert len(d["drivers"]) == 8 and sum(x["share_pct"] for x in d["drivers"]) <= 100.01
    assert d["as_of"] == rows[-1]["Date"]
    p = d["probabilities"]
    assert set(p) == {"Sell", "Hold", "Buy"} and sum(p.values()) == pytest.approx(1, abs=0.01)
    assert max(p, key=p.get) == d["signal"]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    from app import create_app
    from app.backend import api
    data = REPO / "deploy_data"
    monkeypatch.setattr(api, "MODELS_DIR", data / "models")
    monkeypatch.setattr(api, "PROCESSED_DIR", data / "processed")
    # the web request must only read the prebuilt file, never run the models
    def boom(*a, **k):
        raise AssertionError("explanations must not be computed during a web request")
    monkeypatch.setattr(explain, "lstm_attributions", boom)
    monkeypatch.setattr(explain, "xgb_attributions", boom)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.mark.parametrize("ticker,model_type", [("CHCL", "LSTM"), ("HDL", "XGBoost")])
def test_explain_endpoint_reads_the_prebuilt_file(client, ticker, model_type):
    d = client.get(f"/api/explain/{ticker}").get_json()
    assert d["model_type"] == model_type and d["signal"] in ("Buy", "Sell", "Hold")
    assert len(d["drivers"]) == 8 and all(x["toward"] in ("Buy", "Sell") for x in d["drivers"])
    assert d["reliability"]["level"] in ("no_edge", "unproven", "tested", "unknown")
    assert d["generated"]


def test_shipped_explanations_cover_every_stock():
    import json
    data = REPO / "deploy_data"
    shipped = json.loads((data / "models" / "explanations.json").read_text(encoding="utf-8"))
    tickers = [t for t in (data / "processed" / "ticker_list.txt").read_text().split() if t]
    assert set(tickers) <= set(shipped["stocks"])


def test_build_script_runs_without_flask(tmp_path):
    """GitHub Actions run scripts/build_explanations.py without the web dependencies."""
    pytest.importorskip("torch")
    import json
    import shutil
    import subprocess
    import sys
    src = REPO / "deploy_data"
    (tmp_path / "processed").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "processed" / "ticker_list.txt").write_text("CHCL\nHDL\n")
    for t in ("CHCL", "HDL"):
        shutil.copy(src / "processed" / f"{t}_features.csv", tmp_path / "processed")
    for f in ("Hydro_Power_lstm_model_oos.pth", "Hydro_Power_scaler_oos.pkl",
              "Manufacturing_And_Processing_xgb_model_oos.pkl"):
        shutil.copy(src / "models" / f, tmp_path / "models")
    block_web = ("import sys, runpy\n"
                 "for m in ('flask', 'flask_sqlalchemy', 'flask_cors', 'authlib', 'sqlalchemy'):\n"
                 "    sys.modules[m] = None\n"
                 f"sys.argv = ['build_explanations.py', '--data-dir', {str(tmp_path)!r}]\n"
                 f"runpy.run_path({str(REPO / 'scripts' / 'build_explanations.py')!r}, run_name='__main__')\n")
    r = subprocess.run([sys.executable, "-c", block_web], cwd=REPO, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads((tmp_path / "models" / "explanations.json").read_text(encoding="utf-8"))
    assert out["stocks"]["CHCL"]["model_type"] == "LSTM" and out["stocks"]["HDL"]["model_type"] == "XGBoost"


def test_explain_unknown_ticker_is_404(client):
    assert client.get("/api/explain/NOPE").status_code == 404


def test_explain_without_the_file_says_so(client, monkeypatch, tmp_path):
    from app.backend import api
    monkeypatch.setattr(api, "MODELS_DIR", tmp_path)
    explain._FILE_CACHE.update(key=None, data={})
    d = client.get("/api/explain/CHCL").get_json()
    assert "not been built" in d["error"]


# ---------------- /api/signal on Render: read the prebuilt file, never load a model ----------------
def test_signal_comes_from_the_prebuilt_file_when_live_scoring_is_off(client, monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("LIVE_MODEL_SCORING", "0")
    data = REPO / "deploy_data"
    shipped = json.loads((data / "models" / "explanations.json").read_text(encoding="utf-8"))
    shipped["stocks"]["CHCL"]["probabilities"] = {"Sell": 0.1, "Hold": 0.7, "Buy": 0.2}
    shipped["stocks"]["CHCL"]["signal"] = "Hold"
    (tmp_path / "explanations.json").write_text(json.dumps(shipped), encoding="utf-8")
    from app.backend import api
    monkeypatch.setattr(api, "MODELS_DIR", tmp_path)
    import builtins
    real_import = builtins.__import__
    def no_torch(name, *a, **k):
        if name == "torch" or name.startswith("torch."):
            raise AssertionError("the web request must not import torch")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_torch)
    d = client.get("/api/signal/CHCL").get_json()
    assert d["signal"] == "Hold" and d["source"] == "precomputed" and d["confidence"] == 0.7
    assert d["reliability"]["level"] in ("no_edge", "unproven", "tested", "unknown")
    hdl = client.get("/api/signal/HDL").get_json()                 # older file without probabilities still works
    assert hdl["signal"] in ("Buy", "Sell", "Hold") and hdl["source"] == "precomputed"
    assert (hdl["probabilities"] is None) == (hdl["confidence"] is None)


def test_signal_without_a_prebuilt_entry_says_so_instead_of_loading_a_model(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_MODEL_SCORING", "0")
    from app.backend import api
    (tmp_path / "explanations.json").write_text('{"generated": "x", "stocks": {}}', encoding="utf-8")
    monkeypatch.setattr(api, "MODELS_DIR", tmp_path)
    d = client.get("/api/signal/CHCL").get_json()
    assert d["signal"] is None and "not been computed" in d["error"]
    assert client.get("/api/signal/..%2Fx").status_code == 404


def test_live_scoring_is_off_by_default_on_render(monkeypatch):
    from app.backend import api
    monkeypatch.delenv("LIVE_MODEL_SCORING", raising=False)
    monkeypatch.setenv("RENDER", "true")
    assert api._live_scoring_allowed() is False
    monkeypatch.delenv("RENDER")
    assert api._live_scoring_allowed() is True
