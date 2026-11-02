"""Tests for the alert rule engine (ml/analysis/alerts.py)."""
import pytest

from ml.analysis import alerts as A


def row(**k):
    base = {"ticker": "NABIL", "date": "2026-10-30", "close": 1000.0, "change_pct": 1.0, "relative_volume": 1.0,
            "turnover": 5e6, "rsi_14": 50.0, "cross_price_sma50": None, "cross_macd": None}
    base.update(k)
    return base


def rule(kind, threshold=None, state=False, **k):
    return {"kind": kind, "threshold": threshold, "state": state, "created": "2026-10-01", **k}


@pytest.mark.parametrize("kind,threshold,r,met", [
    ("price_above", 1000, row(close=1000.0), True), ("price_above", 1000.01, row(close=1000.0), False),
    ("price_below", 1000, row(close=1000.0), True), ("price_below", 999.99, row(close=1000.0), False),
    ("move_up", 5, row(change_pct=5.0), True), ("move_up", 5, row(change_pct=4.99), False),
    ("move_down", 5, row(change_pct=-5.0), True), ("move_down", 5, row(change_pct=-4.0), False),
    ("volume_spike", 3, row(relative_volume=3.0), True), ("volume_spike", 3, row(relative_volume=2.9), False),
    ("volume_spike", 3, row(relative_volume=9.0, turnover=1e5), False),            # illiquid noise ignored
    ("rsi_above", 70, row(rsi_14=70.0), True), ("rsi_above", 70, row(rsi_14=69.9), False),
    ("rsi_below", 30, row(rsi_14=30.0), True), ("rsi_below", 30, row(rsi_14=31), False),
    ("cross_sma50_up", None, row(cross_price_sma50="up"), True), ("cross_sma50_up", None, row(cross_price_sma50="down"), False),
    ("cross_sma50_down", None, row(cross_price_sma50="down"), True),
    ("macd_cross_up", None, row(cross_macd="up"), True), ("macd_cross_down", None, row(cross_macd="up"), False),
])
def test_conditions(kind, threshold, r, met):
    assert A.evaluate(rule(kind, threshold), r, "2026-10-30")["state"] is met


def test_missing_numbers_never_fire():
    r = row(close=None, change_pct=None, relative_volume=None, rsi_14=None)
    for kind, thr in (("price_above", 1), ("price_below", 1), ("move_up", 1), ("move_down", 1),
                      ("volume_spike", 2), ("rsi_above", 60), ("rsi_below", 40)):
        out = A.evaluate(rule(kind, thr), r, "2026-10-30")
        assert out["fire"] is False and out["state"] is False


def test_fires_on_transition_only_and_rearms():
    first = A.evaluate(rule("price_above", 1000), row(close=1100.0), "2026-10-30")
    assert first["fire"] and "1,100.00" in first["messages"][0]
    again = A.evaluate(rule("price_above", 1000, state=True), row(close=1100.0, date="2026-10-31"), "2026-10-31")
    assert again["fire"] is False and again["state"] is True and again["messages"] == []      # still above: quiet
    dropped = A.evaluate(rule("price_above", 1000, state=True), row(close=900.0, date="2026-11-01"), "2026-11-01")
    assert dropped["state"] is False and dropped["fire"] is False                              # re-armed
    back = A.evaluate(rule("price_above", 1000, state=dropped["state"]), row(close=1100.0, date="2026-11-02"), "2026-11-02")
    assert back["fire"] is True


def test_stock_that_did_not_trade_is_skipped_and_keeps_state():
    stale = row(date="2026-10-28", close=1100.0)
    out = A.evaluate(rule("price_above", 1000, state=False), stale, "2026-10-30")
    assert out["skip"] and out["fire"] is False and out["state"] is False
    assert A.evaluate(rule("price_above", 1000, state=True), None, "2026-10-30")["state"] is True


def item(url, date="2026-10-30", cat="dividend"):
    return {"url": url, "date": date, "title": f"title {url}", "category": cat, "category_label": cat.title(), "ticker": "NABIL"}


def test_announcement_rule_fires_once_per_item():
    r = rule("announcement")
    items = [item("u1"), item("u2", "2026-09-01"), item("u3", cat="agm")]
    out = A.evaluate(r, None, "2026-10-30", items)
    assert out["fire"] and len(out["messages"]) == 2                    # u2 is older than the rule
    nxt = A.evaluate(dict(r, seen=out["seen"]), None, "2026-10-31", items + [item("u4")])
    assert nxt["fire"] and len(nxt["messages"]) == 1 and "u4" in nxt["messages"][0]
    assert A.evaluate(dict(r, seen=nxt["seen"]), None, "2026-11-01", items + [item("u4")])["fire"] is False


def test_announcement_category_filter():
    out = A.evaluate(rule("announcement", category="agm"), None, "2026-10-30", [item("u1"), item("u3", cat="agm")])
    assert len(out["messages"]) == 1 and "u3" in out["messages"][0]


def test_validate():
    assert A.validate("price_above", "1,100.456") == (1100.46, None)
    assert A.validate("cross_sma50_up", "ignored") == (None, None)
    assert A.validate("announcement", None, "dividend") == (None, "dividend")
    assert A.validate("price_above", 5, "dividend") == (5.0, None)             # category only applies to announcements
    for bad in (("nope", 1), ("price_above", "abc"), ("price_above", 0), ("move_up", 50), ("rsi_below", 90),
                ("announcement", None, "weird")):
        with pytest.raises(ValueError):
            A.validate(*bad)


def test_every_kind_can_be_described_and_listed():
    for k in A.KINDS:
        assert A.describe(k, 3.0, "agm")
    assert {x["kind"] for x in A.kinds_for_ui()} == set(A.KINDS)
