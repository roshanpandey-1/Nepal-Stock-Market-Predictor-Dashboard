"""The /backtest page leads with the honest signal tests (models/signal_evidence.json)."""
import json
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

REAL = Path(__file__).resolve().parents[1] / "deploy_data" / "models" / "signal_evidence.json"


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def make(with_evidence):
        from app import create_app
        from app.backend import routes
        models = tmp_path / "models"
        models.mkdir(exist_ok=True)
        if with_evidence:
            shutil.copy(REAL, models / "signal_evidence.json")
        monkeypatch.setattr(routes, "MODELS_DIR", models)
        app = create_app()
        app.config["TESTING"] = True
        return app.test_client()
    return make


def test_shipped_evidence_file_is_complete():
    d = json.loads(REAL.read_text(encoding="utf-8"))
    assert d["verdict"] == "no_trading_edge" and len(d["tests"]) == 2 and len(d["sectors"]) == 11
    for t in d["tests"]:
        assert t["ic_ci"][0] < t["ic"] < t["ic_ci"][1]
    for s in d["sectors"]:
        assert s["b_lo"] <= s["b_ic"] <= s["b_hi"] and s["verdict"] in ("clear", "unclear")


def test_page_shows_honest_summary_first(make_client):
    html = make_client(True).get("/backtest").get_data(as_text=True)
    assert "How well do the signals really work?" in html
    assert "not an ability to make money after NEPSE costs" in html
    assert "Test 1 - models deployed until 24 Oct 2026" in html and "Test 2 - retrained on the past" in html
    assert "Single-stock demonstration" in html
    assert html.index("Short answer") < html.index("Single-stock demonstration")


def test_page_still_renders_without_the_evidence_file(make_client):
    r = make_client(False).get("/backtest")
    assert r.status_code == 200
    assert "Out-of-Sample Backtest" in r.get_data(as_text=True)


def test_sentiment_is_gone_from_the_dashboard(make_client):
    c = make_client(True)
    assert c.get("/sentiment").status_code == 404
    assert c.get("/api/sentiment/NABIL").status_code == 404
    html = c.get("/backtest").get_data(as_text=True)
    assert ">Sentiment</a>" not in html


def test_privacy_and_terms_pages_are_public_and_linked(make_client):
    c = make_client(True)
    privacy = c.get("/privacy")
    terms = c.get("/terms")
    assert privacy.status_code == 200 and "Privacy Policy" in privacy.get_data(as_text=True)
    assert terms.status_code == 200 and "Not financial advice" in terms.get_data(as_text=True)
    footer = c.get("/backtest").get_data(as_text=True)
    assert 'href="/privacy"' in footer and 'href="/terms"' in footer
