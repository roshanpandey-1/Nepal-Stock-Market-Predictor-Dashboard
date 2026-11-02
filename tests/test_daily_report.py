"""Tests for the daily market report (ml/analysis/daily_report.py and
scripts/build_daily_report.py)."""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

from ml.analysis import daily_report, market

DEPLOY = Path("deploy_data")
needs_data = pytest.mark.skipif(not (DEPLOY / "processed" / "NABIL_features.csv").exists(),
                                reason="deploy_data snapshot not present")

_spec = importlib.util.spec_from_file_location("build_daily_report", "scripts/build_daily_report.py")
bdr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bdr)


@needs_data
def test_report_matches_market_summary():
    rep = daily_report.build(DEPLOY)
    s = market.summary(DEPLOY)
    assert rep["date"] == s["as_of"]
    assert rep["breadth"] == s["breadth"]
    last = rep["recent_sessions"][-1]
    assert last["date"] == rep["date"]
    # per-session aggregates use the same rounding, so they agree with the breadth counts
    assert last["advancing"] == s["breadth"]["advancing"]
    assert last["declining"] == s["breadth"]["declining"]
    assert abs(last["turnover"] - s["totals"]["turnover"]) < 1
    assert rep["nepse_index"] is None and rep["nepse_index_note"]
    assert rep["headline"] and rep["risks"][-1].startswith("Not covered")
    assert "not a forecast" in rep["disclaimer"]


@needs_data
def test_index_used_only_for_same_session():
    date = market.summary(DEPLOY)["as_of"]
    row = {"date": date, "value": 2650.5, "change": 10.0, "change_pct": 0.38}
    assert daily_report.build(DEPLOY, index_row=row)["nepse_index"]["value"] == 2650.5
    assert "2,650.50" in daily_report.build(DEPLOY, index_row=row)["headline"][0]
    stale = dict(row, date="2000-01-01")
    assert daily_report.build(DEPLOY, index_row=stale)["nepse_index"] is None


def test_capture_index_rules():
    when = datetime(2026, 10, 30, 16, 20, tzinfo=bdr.NEPAL_TZ)
    closed = lambda: {"market_open": False, "index": {"value": 2700.1, "change": -5.0, "change_pct": -0.18}}
    got = bdr.capture_index("2026-10-30", now=when, fetch=closed)
    assert got["value"] == 2700.1 and got["date"] == "2026-10-30"
    # wrong day in Nepal -> never filed under that session
    assert bdr.capture_index("2026-10-29", now=when, fetch=closed) is None
    # market still open -> not a close
    assert bdr.capture_index("2026-10-30", now=when, fetch=lambda: dict(closed(), market_open=True)) is None
    # NEPSE unreachable / library missing -> None, no exception
    def boom():
        raise ConnectionError("blocked")
    assert bdr.capture_index("2026-10-30", now=when, fetch=boom) is None


def test_index_csv_roundtrip(tmp_path):
    p = tmp_path / "nepse_index.csv"
    rows = {"2026-10-30": {"date": "2026-10-30", "value": 2700.1, "change": -5.0, "change_pct": -0.18, "captured_at": "x"}}
    bdr.write_index(p, rows)
    back = bdr.read_index(p)
    assert back["2026-10-30"]["value"] == 2700.1 and back["2026-10-30"]["change_pct"] == -0.18


def test_report_route_rejects_bad_dates():
    from app.backend import routes
    assert routes._load_market_report("../../etc/passwd") is None
    assert routes._load_market_report("2026-13-99x") is None
