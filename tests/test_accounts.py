"""Tests for user accounts, watchlist and portfolio (app/backend/accounts.py, app/backend/portfolio_utils.py)."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from app.backend.portfolio_utils import sector_breakdown, value_holdings


# ---------------- portfolio maths ----------------

def test_valuation_totals_and_unpriced_scrip():
    rows, tot = value_holdings({"A": 10, "B": 5}, {"A": {"lcp": 110, "ltp": 120, "sector": "Finance"}})
    a = next(r for r in rows if r["ticker"] == "A")
    b = next(r for r in rows if r["ticker"] == "B")
    assert (a["value_lcp"], a["value_ltp"], a["day_pl"]) == (1100, 1200, 100)
    assert b["priced"] is False and b["value_ltp"] == 0 and b["ltp"] is None
    assert tot["value_ltp"] == 1200 and tot["day_pl"] == 100 and tot["count"] == 2


def test_sector_breakdown_shares_sum_to_100():
    rows = [{"sector": "Finance", "value_ltp": 300.0}, {"sector": None, "value_ltp": 100.0}]
    out = sector_breakdown(rows)
    assert out[0]["sector"] == "Finance" and out[0]["share_pct"] == 75.0
    assert round(sum(s["share_pct"] for s in out), 2) == 100.0


# ---------------- accounts, through the Flask client ----------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    from app import create_app
    from app.backend import routes
    monkeypatch.setattr(routes, "_ticker_list", lambda: ["NABIL", "SCB", "NLIC"])
    monkeypatch.setattr(routes, "_company_names", lambda: {"NABIL": "Nabil Bank", "SCB": "Standard Chartered"})
    monkeypatch.setattr(routes, "_ticker_sector", lambda t: {"NABIL": "Commercial Banks", "SCB": "Commercial Banks"}.get(t))
    monkeypatch.setattr(routes, "_live_quote_safe", lambda t: None)
    monkeypatch.setattr(routes, "_latest_quote", lambda t: {
        "date": "2026-10-12", "close": 1000.0, "prev_close": 990.0, "change": 10.0, "change_pct": 1.01} if t in ("NABIL", "SCB", "NLIC") else None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _token(c):
    c.get("/login")
    with c.session_transaction() as s:
        return s["csrf"]


def _signup(c, email="a@gmail.com", password="Correct-horse1"):
    tok = _token(c)
    return c.post("/register", data={"email": email, "password": password, "confirm": password, "csrf_token": tok})


def _j(c, method, url, body=None):
    with c.session_transaction() as s:
        tok = s.get("csrf", "")
    return getattr(c, method)(url, json=body, headers={"X-CSRF-Token": tok})


def test_public_pages_do_not_need_login(client):
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200


def test_protected_pages_redirect_and_api_returns_401(client):
    r = client.get("/portfolio")
    assert r.status_code == 302 and "/login?next=" in r.headers["Location"]
    assert client.get("/api/me/portfolio").status_code == 401
    assert client.get("/watchlist").status_code == 302


def test_register_login_logout_flow(client):
    r = _signup(client)
    assert r.status_code == 302
    assert client.get("/portfolio").status_code == 200
    tok = client.get("/portfolio") and _token(client)
    assert client.post("/logout", data={"csrf_token": tok}).status_code == 302
    assert client.get("/portfolio").status_code == 302
    tok = _token(client)
    r = client.post("/login", data={"email": "a@gmail.com", "password": "Correct-horse1", "csrf_token": tok})
    assert r.status_code == 302
    assert client.get("/portfolio").status_code == 200


def test_wrong_password_and_duplicate_email_are_rejected(client):
    _signup(client)
    client.post("/logout", data={"csrf_token": _token(client)})
    r = client.post("/login", data={"email": "a@gmail.com", "password": "nope-nope", "csrf_token": _token(client)})
    assert r.status_code == 200 and b"Wrong email or password" in r.data
    r = _signup(client)
    assert r.status_code == 200 and b"already registered" in r.data


def test_short_password_rejected(client):
    r = _signup(client, password="short")
    assert r.status_code == 200 and b"8-128 characters" in r.data


def test_post_without_csrf_is_rejected(client):
    r = client.post("/register", data={"email": "x@gmail.com", "password": "Longenough1!", "confirm": "Longenough1!"})
    assert r.status_code == 400


def test_login_next_cannot_redirect_off_site(client):
    _signup(client)
    client.post("/logout", data={"csrf_token": _token(client)})
    r = client.post("/login", data={"email": "a@gmail.com", "password": "Correct-horse1",
                                    "csrf_token": _token(client), "next": "https://evil.example/x"})
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]


def test_login_is_throttled_after_repeated_failures(client):
    _signup(client)
    client.post("/logout", data={"csrf_token": _token(client)})
    for _ in range(5):
        client.post("/login", data={"email": "a@gmail.com", "password": "bad-bad-bad", "csrf_token": _token(client)})
    r = client.post("/login", data={"email": "a@gmail.com", "password": "Correct-horse1", "csrf_token": _token(client)})
    assert b"Too many failed attempts" in r.data


def test_watchlist_add_list_remove_and_validation(client):
    _signup(client)
    assert _j(client, "post", "/api/me/watchlist", {"ticker": "nabil"}).get_json()["watching"] is True
    _j(client, "post", "/api/me/watchlist", {"ticker": "NABIL"})          # duplicate is harmless
    items = client.get("/api/me/watchlist").get_json()["items"]
    assert [i["ticker"] for i in items] == ["NABIL"] and items[0]["ltp"] == 1000.0
    assert _j(client, "post", "/api/me/watchlist", {"ticker": "ZZZZ"}).status_code == 400
    assert client.get("/api/me/watchlist/status/NABIL").get_json()["watching"] is True
    assert _j(client, "delete", "/api/me/watchlist/NABIL").get_json()["watching"] is False
    assert client.get("/api/me/watchlist").get_json()["items"] == []


def test_holdings_add_replace_value_and_remove(client):
    _signup(client)
    assert _j(client, "post", "/api/me/holdings", {"ticker": "nabil", "quantity": "100"}).status_code == 201
    _j(client, "post", "/api/me/holdings", {"ticker": "SCB", "quantity": 10})
    again = _j(client, "post", "/api/me/holdings", {"ticker": "NABIL", "quantity": 150}).get_json()
    assert again["updated"] is True
    p = client.get("/api/me/portfolio").get_json()
    nabil = next(h for h in p["holdings"] if h["ticker"] == "NABIL")
    assert len(p["holdings"]) == 2 and nabil["quantity"] == 150 and nabil["ltp"] == 1000
    assert nabil["value_ltp"] == 150000 and p["totals"]["count"] == 2
    assert p["sectors"][0]["sector"] == "Commercial Banks"
    assert _j(client, "delete", "/api/me/holdings/NABIL").status_code == 200
    assert len(client.get("/api/me/portfolio").get_json()["holdings"]) == 1
    assert _j(client, "delete", "/api/me/holdings/NABIL").status_code == 404


def test_bad_holding_input_is_rejected(client):
    _signup(client)
    for bad in ({"quantity": 0}, {"quantity": "1.5"}, {"quantity": "abc"}, {"quantity": -3},
                {"ticker": "ZZZZ"}, {"ticker": ""}, {"ticker": "bad symbol!"}):
        assert _j(client, "post", "/api/me/holdings", {"ticker": "NABIL", "quantity": 10, **bad}).status_code == 400, bad


def test_users_cannot_see_or_delete_each_others_data(client):
    _signup(client, "a@gmail.com")
    _j(client, "post", "/api/me/holdings", {"ticker": "NABIL", "quantity": 10})
    _j(client, "post", "/api/me/watchlist", {"ticker": "SCB"})
    client.post("/logout", data={"csrf_token": _token(client)})
    _signup(client, "b@gmail.com")
    assert client.get("/api/me/portfolio").get_json()["holdings"] == []
    assert client.get("/api/me/watchlist").get_json()["items"] == []
    assert _j(client, "delete", "/api/me/holdings/NABIL").status_code == 404


def test_delete_account_removes_everything(client):
    _signup(client)
    _j(client, "post", "/api/me/holdings", {"ticker": "NABIL", "quantity": 10})
    _j(client, "post", "/api/me/watchlist", {"ticker": "SCB"})
    r = client.post("/profile", data={"action": "delete", "confirm_word": "CONFIRM", "csrf_token": _token(client)})
    assert r.status_code == 200
    from app.backend.database import Holding, User, WatchlistItem
    assert User.query.count() == 0 and Holding.query.count() == 0 and WatchlistItem.query.count() == 0


@pytest.mark.parametrize("typed", ["", "confirm", "CONFIRMED", "a@gmail.com", "yes"])
def test_delete_account_needs_the_exact_word(client, typed):
    _signup(client)
    client.post("/profile", data={"action": "delete", "confirm_word": typed, "csrf_token": _token(client)})
    from app.backend.database import User
    assert User.query.count() == 1


def test_google_button_disabled_when_not_configured(client):
    html = client.get("/login").data
    assert b"Continue with Google" in html and b"disabled" in html and b"/auth/google" not in html


@pytest.mark.parametrize("pw,msg", [
    ("lowercase1!", b"capital letter"),
    ("NoNumber!!", b"one number"),
    ("NoSpecial12", b"special character"),
])
def test_password_rules(client, pw, msg):
    r = _signup(client, password=pw)
    assert r.status_code == 200 and msg in r.data


@pytest.mark.parametrize("email", ["a@yahoo.com", "a@gmail.co", "a@@gmail.com", "nogmail.com", "a b@gmail.com"])
def test_only_gmail_addresses_can_sign_up(client, email):
    r = _signup(client, email=email)
    assert r.status_code == 200 and b"Gmail address" in r.data


def test_mismatched_confirm_is_flagged_on_the_field(client):
    tok = _token(client)
    r = client.post("/register", data={"email": "m@gmail.com", "password": "Correct-horse1",
                                       "confirm": "Different-horse1", "csrf_token": tok})
    assert r.status_code == 200 and b"Passwords don&#39;t match" in r.data and b'class="invalid"' in r.data


def test_taken_email_is_flagged_with_free_suggestions(client):
    _signup(client, "taken@gmail.com")
    client.post("/logout", data={"csrf_token": _token(client)})
    r = client.post("/register", data={"email": "TAKEN@gmail.com", "password": "Correct-horse1",
                                       "confirm": "Correct-horse1", "csrf_token": _token(client)})
    html = r.data.decode()
    assert r.status_code == 200 and "already registered" in html
    import re as _re
    chips = _re.findall(r'data-email="([^"]+)"', html)
    assert 1 <= len(chips) <= 3 and all(c.endswith("@gmail.com") and c != "taken@gmail.com" for c in chips)


def test_google_button_is_always_visible(client):
    r = client.get("/register")
    assert b"Continue with Google" in r.data


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    from app.backend import accounts, mailer
    accounts._RESET_REQS.clear()
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, text, html=None: sent.append((to, text)) or True)
    return sent


def _link(sent):
    import re as _re
    return _re.search(r"http://\S+/reset/\S+", sent[-1][1]).group(0).split("localhost")[-1]


def test_forgot_password_sends_a_link_that_resets_once(client, outbox):
    _signup(client)
    client.post("/logout", data={"csrf_token": _token(client)})
    r = client.post("/forgot", data={"email": "a@gmail.com", "csrf_token": _token(client)})
    assert r.status_code == 200 and b"sent a link" in r.data and len(outbox) == 1
    path = _link(outbox)
    assert client.get(path).status_code == 200
    bad = client.post(path, data={"password": "weakpass", "confirm": "weakpass", "csrf_token": _token(client)})
    assert bad.status_code == 200 and b"capital letter" in bad.data
    mism = client.post(path, data={"password": "Brand-new9!", "confirm": "Other-new9!", "csrf_token": _token(client)})
    assert b"Passwords don&#39;t match" in mism.data
    ok = client.post(path, data={"password": "Brand-new9!", "confirm": "Brand-new9!", "csrf_token": _token(client)})
    assert ok.status_code == 302 and "/login" in ok.headers["Location"]
    login = client.post("/login", data={"email": "a@gmail.com", "password": "Brand-new9!", "csrf_token": _token(client)})
    assert login.status_code == 302
    client.post("/logout", data={"csrf_token": _token(client)})
    assert client.get(path).status_code == 400          # link is single-use
    old = client.post("/login", data={"email": "a@gmail.com", "password": "Correct-horse1", "csrf_token": _token(client)})
    assert old.status_code == 200


def test_forgot_password_does_not_reveal_unknown_emails(client, outbox):
    r = client.post("/forgot", data={"email": "nobody@gmail.com", "csrf_token": _token(client)})
    assert r.status_code == 200 and b"sent a link" in r.data and outbox == []


def test_forgot_password_is_rate_limited_and_bad_tokens_rejected(client, outbox):
    _signup(client)
    client.post("/logout", data={"csrf_token": _token(client)})
    for _ in range(5):
        client.post("/forgot", data={"email": "a@gmail.com", "csrf_token": _token(client)})
    assert len(outbox) == 3
    assert client.get("/reset/not-a-real-token").status_code == 400


def test_mailer_posts_to_brevo_and_falls_back_to_logging(monkeypatch):
    from app.backend import mailer
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    assert mailer.send_email("x@gmail.com", "s", "t") is False        # not configured: logged only
    monkeypatch.setenv("BREVO_API_KEY", "k"); monkeypatch.setenv("MAIL_SENDER", "me@gmail.com")
    seen = {}

    class R:
        status_code = 201
        text = ""

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return R()

    monkeypatch.setattr(mailer.requests, "post", fake_post)
    assert mailer.send_email("x@gmail.com", "Hello", "body", "<p>body</p>") is True
    assert seen["url"].endswith("/v3/smtp/email") and seen["headers"]["api-key"] == "k"
    assert seen["json"]["to"] == [{"email": "x@gmail.com"}] and seen["json"]["sender"]["email"] == "me@gmail.com"


def test_healthz_is_fast_and_public(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.data == b"ok"
    assert client.head("/healthz").status_code == 200


def test_todays_change_uses_previous_close_even_after_the_close():
    # market closed: LCP == LTP (Meroshare style) but the session still moved +10/share
    rows, tot = value_holdings({"A": 10, "B": 4}, {
        "A": {"lcp": 120, "ltp": 120, "change": 10.0, "change_pct": 9.09},
        "B": {"lcp": 50, "ltp": 50, "change": -2.5, "change_pct": -4.76}})
    a = next(r for r in rows if r["ticker"] == "A")
    assert a["day_pl"] == 100 and a["change_pct"] == 9.09
    assert tot["day_pl"] == 90 and tot["day_pct"] == round(90 / (1400 - 90) * 100, 2)


def test_portfolio_api_reports_todays_change(client):
    _signup(client)
    tok = _token(client)
    client.post("/api/me/holdings", json={"ticker": "NABIL", "quantity": 5}, headers={"X-CSRF-Token": tok})
    d = client.get("/api/me/portfolio").get_json()
    assert d["totals"]["day_pl"] == 50.0          # 5 shares x +10 vs previous close
    assert d["holdings"][0]["change_pct"] == 1.01


def _run_py_data_dir(monkeypatch, tmp_path, preset):
    """Import run.py fresh and report which data folder the app resolved."""
    import importlib, sys
    for m in [m for m in sys.modules if m == "run" or m == "app" or m.startswith("app.")]:
        monkeypatch.delitem(sys.modules, m)
    if preset is None:
        monkeypatch.delenv("DATA_DIR", raising=False)
    else:
        monkeypatch.setenv("DATA_DIR", preset)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    importlib.import_module("run")
    return sys.modules["app.backend.api"].DATA_DIR.as_posix()


def test_run_py_defaults_to_the_deployed_snapshot(monkeypatch, tmp_path):
    assert _run_py_data_dir(monkeypatch, tmp_path, None) == "deploy_data"


def test_run_py_respects_an_explicit_data_dir(monkeypatch, tmp_path):
    assert _run_py_data_dir(monkeypatch, tmp_path, "data") == "data"
