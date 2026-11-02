"""Tests for the daily alert runner (app/backend/alert_runner.py) with a fake mailer and synthetic data."""
import csv
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from flask import Flask

from app.backend import alert_runner
from app.backend.database import AlertRule, User, db, ensure_schema
from ml.analysis import data as D


class FakeMail:
    def __init__(self, configured=True, ok=True):
        self.configured, self.ok, self.sent = configured, ok, []

    def mail_configured(self):
        return self.configured

    def send_email(self, to, subject, text, html=None):
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})
        return self.ok


def _write(root, ticker, closes, dates):
    proc = root / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    with open(proc / f"{ticker}_features.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume", "Turnover", "Sector"])
        for d, c in zip(dates, closes):
            w.writerow([d, c, c * 1.01, c * 0.99, c, 1000, c * 1000, "Finance"])


def _days(n, end):
    e = date.fromisoformat(end)
    return [(e - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


@pytest.fixture
def world(tmp_path):
    data = tmp_path / "data"
    _write(data, "AAA", [100.0] * 69 + [120.0], _days(70, "2026-10-30"))            # closes 120 on the latest session
    _write(data, "BBB", [50.0] * 70, _days(70, "2026-10-30")[:-1] + ["2026-10-28"])   # BBB's last trade is older
    D._CACHE.clear()
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 't.db'}", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        ensure_schema(db.engine)
        a, b = User(email="a@example.com", name="Asha"), User(email="b@example.com", name="Bikram")
        db.session.add_all([a, b])
        db.session.commit()
        yield data, a, b


def _rule(user, ticker, kind, threshold=None, **k):
    r = AlertRule(user_id=user.id, ticker=ticker, kind=kind, threshold=threshold, **k)
    db.session.add(r)
    db.session.commit()
    return r


def test_fires_once_then_stays_quiet_until_rearmed(world):
    data, a, b = world
    r = _rule(a, "AAA", "price_above", 110)
    mail = FakeMail()
    s1 = alert_runner.run(data, mail=mail)
    assert s1["fired"] == 1 and s1["emails_sent"] == 1 and mail.sent[0]["to"] == "a@example.com"
    assert "AAA" in mail.sent[0]["text"] and "120.00" in mail.sent[0]["text"] and "Hello Asha" in mail.sent[0]["text"]
    db.session.refresh(r)
    assert r.state is True and r.last_fired == "2026-10-30" and r.last_checked == "2026-10-30"
    s2 = alert_runner.run(data, mail=mail)                 # same data again: nothing new to say
    assert s2["fired"] == 0 and len(mail.sent) == 1


def test_failed_send_is_retried_not_lost(world):
    data, a, b = world
    r = _rule(a, "AAA", "price_above", 110)
    assert alert_runner.run(data, mail=FakeMail(ok=False))["emails_failed"] == 1
    db.session.refresh(r)
    assert r.state is False and r.last_fired is None            # unchanged, so the next run tries again
    good = FakeMail()
    assert alert_runner.run(data, mail=good)["emails_sent"] == 1


def test_nothing_changes_when_email_is_not_configured(world):
    data, a, b = world
    r = _rule(a, "AAA", "price_above", 110)
    s = alert_runner.run(data, mail=FakeMail(configured=False))
    assert "not configured" in s["error"]
    db.session.refresh(r)
    assert r.state is False and r.last_checked is None


def test_dry_run_sends_nothing(world):
    data, a, b = world
    _rule(a, "AAA", "price_above", 110)
    mail = FakeMail()
    s = alert_runner.run(data, send=False, mail=mail)
    assert s["fired"] == 1 and mail.sent == []


def test_stock_that_did_not_trade_is_skipped(world):
    data, a, b = world
    _rule(a, "BBB", "price_below", 60)                       # BBB would match, but its last session is old
    mail = FakeMail()
    s = alert_runner.run(data, mail=mail)
    assert s["skipped"] == 1 and s["fired"] == 0 and mail.sent == []


def test_each_person_only_gets_their_own_alerts(world):
    data, a, b = world
    _rule(a, "AAA", "price_above", 110)
    _rule(b, "AAA", "price_below", 10)                       # not met
    _rule(b, "AAA", "move_up", 5)                            # met for B only
    mail = FakeMail()
    alert_runner.run(data, mail=mail)
    by_to = {m["to"]: m for m in mail.sent}
    assert set(by_to) == {"a@example.com", "b@example.com"}
    assert "closes at or above" in by_to["a@example.com"]["text"] and "rises" not in by_to["a@example.com"]["text"]
    assert "rises 5% or more" in by_to["b@example.com"]["text"] and "Hello Bikram" in by_to["b@example.com"]["text"]
    assert "Asha" not in by_to["b@example.com"]["text"] and "a@example.com" not in by_to["b@example.com"]["text"]


def test_paused_rules_are_ignored(world):
    data, a, b = world
    _rule(a, "AAA", "price_above", 110, active=False)
    mail = FakeMail()
    assert alert_runner.run(data, mail=mail)["rules"] == 0 and mail.sent == []


def test_announcement_alert_uses_new_items_only(world):
    data, a, b = world
    ext = data / "external"
    ext.mkdir()
    today = datetime.now(timezone.utc).date().isoformat()
    items = [{"url": "https://x/1", "title": "AAA announces AGM", "date": today, "ticker": "AAA", "kind": "announcement",
              "category": "agm", "category_label": "General meeting"}]
    (ext / "announcements.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    r = _rule(a, "AAA", "announcement")
    mail = FakeMail()
    assert alert_runner.run(data, mail=mail)["emails_sent"] == 1 and "AAA announces AGM" in mail.sent[0]["text"]
    assert alert_runner.run(data, mail=mail)["fired"] == 0                    # already told
    items.append(dict(items[0], url="https://x/2", title="AAA book closure"))
    (ext / "announcements.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    import os; os.utime(ext / "announcements.json", (1e9 + 5, 1e9 + 5))        # force the cached file to reload
    alert_runner.run(data, mail=mail)
    assert len(mail.sent) == 2 and "book closure" in mail.sent[1]["text"] and "AGM" not in mail.sent[1]["text"]


def test_email_is_html_escaped():
    subject, text, html = alert_runner.build_email("<b>Eve</b>", "2026-10-30", [("AAA", "d", ["<script>x</script>"], [])])
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;Eve" in html
