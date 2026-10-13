"""User accounts, watchlist and portfolio.

Everything here sits behind a login. Public pages (dashboard, stock pages,
backtest, sentiment) never touch the database, so they keep working even if
the database is unreachable.

Auth: email + password (hashed with werkzeug) and optional Google sign-in
(enabled only when GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are set). Every
state-changing request needs a CSRF token (form field or X-CSRF-Token header).
"""
import logging
import random
import re
import secrets
import time
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from .models import Holding, User, WatchlistItem, db
from . import portfolio_utils as pu

logger = logging.getLogger(__name__)
acct = Blueprint("acct", __name__)

# Sign-up is limited to Gmail addresses (so they can also use Google sign-in).
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@gmail\.com$", re.IGNORECASE)
TICKER_RE = re.compile(r"^[A-Z0-9]{1,15}$")
MAX_WATCHLIST = 100
MAX_HOLDINGS = 500
MAX_QTY = 10_000_000
MIN_PASSWORD = 8


def password_problem(pw):
    """Return a message if `pw` breaks the password rules, else None."""
    if len(pw) < MIN_PASSWORD or len(pw) > 128:
        return f"Use a password of {MIN_PASSWORD}-128 characters."
    if not any(c.isupper() for c in pw):
        return "Password needs at least one capital letter."
    if not any(c.isdigit() for c in pw):
        return "Password needs at least one number."
    if not any(not c.isalnum() and not c.isspace() for c in pw):
        return "Password needs at least one special character (e.g. ! @ # $ %)."
    return None

# --- login throttle (per process; enough to slow down password guessing) ------
_FAILS = {}
_FAIL_LIMIT = 5
_FAIL_WINDOW = 600


def _throttle_key(email):
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip(),
            (email or "").lower())


def _too_many_attempts(email):
    key = _throttle_key(email)
    now = time.time()
    hits = [t for t in _FAILS.get(key, []) if now - t < _FAIL_WINDOW]
    _FAILS[key] = hits
    return len(hits) >= _FAIL_LIMIT


def _record_failure(email):
    _FAILS.setdefault(_throttle_key(email), []).append(time.time())


def _clear_failures(email):
    _FAILS.pop(_throttle_key(email), None)


# --- session, CSRF, current user ------------------------------------------------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def current_user():
    if "user" in g:
        return g.user
    g.user = None
    uid = session.get("uid")
    if uid:
        try:
            g.user = db.session.get(User, uid)
        except SQLAlchemyError:
            logger.warning("Could not load the signed-in user (database unreachable?)")
            db.session.rollback()
        if g.user is None:
            session.pop("uid", None)
    return g.user


@acct.app_context_processor
def inject_account_context():
    return {
        "current_user": current_user(),
        "csrf_token": csrf_token,
        "google_enabled": bool(current_app.config.get("GOOGLE_ENABLED")),
        "db_ephemeral": bool(current_app.config.get("DB_EPHEMERAL")),
    }


def _wants_json():
    return request.path.startswith("/api/")


@acct.before_request
def _check_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            if _wants_json():
                return jsonify({"ok": False, "error": "Invalid or missing CSRF token. Reload the page."}), 400
            return render_template("account_message.html", title="Session expired",
                                   message="Your form expired. Go back, reload the page and try again."), 400


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if _wants_json():
                return jsonify({"ok": False, "error": "Please log in first."}), 401
            return redirect(url_for("acct.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


@acct.errorhandler(SQLAlchemyError)
def _db_down(exc):
    db.session.rollback()
    logger.exception("Database error")
    if _wants_json():
        return jsonify({"ok": False, "error": "Accounts are temporarily unavailable. Try again shortly."}), 503
    return render_template("account_message.html", title="Accounts unavailable",
                           message="Accounts are temporarily unavailable. The rest of the site still works."), 503


def _safe_next(target):
    """Only allow same-site relative redirects after login."""
    if not target:
        return url_for("main.dashboard")
    parts = urlparse(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return url_for("main.dashboard")
    return target


def _start_session(user):
    session.clear()
    session["uid"] = user.id
    session["csrf"] = secrets.token_hex(16)
    session.permanent = True
    g.user = user


# --- register / login / logout ------------------------------------------------
def _suggest_emails(email, limit=3):
    """Up to `limit` free Gmail addresses close to a taken one."""
    local = email.split("@", 1)[0]
    base = re.sub(r"[^a-z0-9._]", "", local.lower())[:40] or "user"
    year = datetime.now().year
    pool = {f"{base}{random.randint(10, 99)}", f"{base}{random.randint(100, 999)}",
            f"{base}.{year}", f"{base}_{random.randint(10, 99)}",
            f"{base}{year % 100}", f"{base}.nepse", f"{base}.{random.randint(1, 9)}"}
    cands = [f"{c}@gmail.com" for c in sorted(pool)]
    taken = {u.email for u in User.query.filter(User.email.in_(cands)).all()}
    free = [c for c in cands if c not in taken]
    random.shuffle(free)
    return free[:limit]


@acct.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("acct.portfolio"))
    nxt = request.values.get("next", "")
    errors, suggestions = {}, []
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        name = (request.form.get("name") or "").strip()[:80] or None
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not EMAIL_RE.match(email) or len(email) > 254:
            errors["email"] = "Use a Gmail address, like name@gmail.com."
        elif User.query.filter_by(email=email).first():
            errors["email"] = "That email is already registered."
            suggestions = _suggest_emails(email)
        if password_problem(password):
            errors["password"] = password_problem(password)
        elif password.lower() == email:
            errors["password"] = "The password can't be the same as your email."
        if "password" not in errors and confirm != password:
            errors["confirm"] = "Passwords don't match."
        if not errors:
            user = User(email=email, name=name, password_hash=generate_password_hash(password))
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:  # lost a race with another sign-up
                db.session.rollback()
                errors["email"] = "That email is already registered."
                suggestions = _suggest_emails(email)
            else:
                _start_session(user)
                return redirect(_safe_next(nxt))
    return render_template("register.html", next=nxt, errors=errors, suggestions=suggestions)


@acct.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(_safe_next(request.args.get("next")))
    nxt = request.values.get("next", "")
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if _too_many_attempts(email):
            flash("Too many failed attempts. Wait a few minutes and try again.", "error")
        else:
            user = User.query.filter_by(email=email).first()
            # compare against a dummy hash when the user doesn't exist, so timing doesn't leak it
            ok = check_password_hash(user.password_hash, password) if user and user.password_hash \
                else (check_password_hash(_DUMMY_HASH, password) and False)
            if ok:
                _clear_failures(email)
                _start_session(user)
                return redirect(_safe_next(nxt))
            _record_failure(email)
            if user and not user.password_hash and user.google_sub:
                flash("This account uses Google sign-in. Use the Google button below.", "error")
            else:
                flash("Wrong email or password.", "error")
    return render_template("login.html", next=nxt)


_DUMMY_HASH = generate_password_hash("not-a-real-password")


@acct.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.dashboard"))


# --- Google sign-in -------------------------------------------------------------
@acct.route("/auth/google")
def google_login():
    oauth = current_app.extensions.get("oauth_client")
    if not current_app.config.get("GOOGLE_ENABLED") or oauth is None:
        flash("Google sign-in isn't set up on this site.", "error")
        return redirect(url_for("acct.login"))
    session["oauth_next"] = _safe_next(request.args.get("next"))
    return oauth.google.authorize_redirect(url_for("acct.google_callback", _external=True))


@acct.route("/auth/google/callback")
def google_callback():
    oauth = current_app.extensions.get("oauth_client")
    if not current_app.config.get("GOOGLE_ENABLED") or oauth is None:
        return redirect(url_for("acct.login"))
    try:
        token = oauth.google.authorize_access_token()
        info = token.get("userinfo") or {}
    except Exception:  # state mismatch, user cancelled, network
        logger.warning("Google sign-in failed", exc_info=True)
        flash("Google sign-in didn't complete. Please try again.", "error")
        return redirect(url_for("acct.login"))
    email = (info.get("email") or "").strip().lower()
    sub = info.get("sub")
    if not email or not sub or not info.get("email_verified"):
        flash("Google didn't return a verified email address.", "error")
        return redirect(url_for("acct.login"))

    user = User.query.filter_by(google_sub=sub).first() or User.query.filter_by(email=email).first()
    if user is None:
        user = User(email=email, name=(info.get("name") or "")[:80] or None, google_sub=sub)
        db.session.add(user)
    elif not user.google_sub:
        user.google_sub = sub  # link an existing email account (Google verified the address)
    db.session.commit()
    nxt = session.get("oauth_next") or url_for("main.dashboard")
    _start_session(user)
    return redirect(_safe_next(nxt))


# --- profile ------------------------------------------------------------------
@acct.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "name":
            user.name = (request.form.get("name") or "").strip()[:80] or None
            db.session.commit()
            flash("Name updated.", "ok")
        elif action == "password":
            new = request.form.get("new_password") or ""
            if user.password_hash and not check_password_hash(user.password_hash, request.form.get("current_password") or ""):
                flash("Current password is wrong.", "error")
            elif password_problem(new):
                flash(password_problem(new), "error")
            elif request.form.get("confirm") != new:
                flash("The two new passwords don't match.", "error")
            else:
                user.password_hash = generate_password_hash(new)
                db.session.commit()
                flash("Password updated.", "ok")
        elif action == "delete":
            if (request.form.get("confirm_email") or "").strip().lower() != user.email:
                flash("Type your email exactly to confirm deleting the account.", "error")
            else:
                db.session.delete(user)
                db.session.commit()
                session.clear()
                return render_template("account_message.html", title="Account deleted",
                                       message="Your account, watchlist and portfolio were deleted."), 200
        return redirect(url_for("acct.profile"))
    return render_template("profile.html", user=user)


# --- price helpers ----------------------------------------------------------------
def _price_for(ticker):
    """Last closing price (lcp) and last traded price (ltp) for one ticker.

    Market open:   LTP is the live trade price, LCP is the previous close.
    Market closed: both equal the latest close (that is what Meroshare shows).
    No live feed:  fall back to the last processed daily close.
    """
    from . import routes as r
    processed = r._latest_quote(ticker)
    live = r._live_quote_safe(ticker)
    name = (live or {}).get("name") if live else None
    name = r._company_names().get(ticker) or name or ticker
    out = {"name": name, "sector": r._ticker_sector(ticker), "lcp": None, "ltp": None,
           "change": None, "change_pct": None, "source": None, "market_open": None}
    if live and live.get("ltp") is not None:
        out["ltp"] = live["ltp"]
        out["market_open"] = live.get("market_open")
        out["change"] = live.get("change")
        out["change_pct"] = live.get("change_pct")
        if live.get("market_open"):
            out["lcp"] = live.get("prev_close") or (processed or {}).get("close") or live["ltp"]
        else:
            out["lcp"] = live["ltp"]
        out["source"] = "live"
    elif processed:
        out["ltp"] = out["lcp"] = processed["close"]
        out["change"] = processed.get("change")
        out["change_pct"] = processed.get("change_pct")
        out["source"] = f"close {processed['date']}"
    return out


def _known_ticker(ticker):
    from . import routes as r
    if ticker in set(r._ticker_list()):
        return True
    return bool(r._live_quote_safe(ticker))


# --- pages ---------------------------------------------------------------------
@acct.route("/watchlist")
@login_required
def watchlist_page():
    return render_template("watchlist.html")


@acct.route("/portfolio")
@login_required
def portfolio():
    return render_template("portfolio.html")


# --- JSON API: watchlist ------------------------------------------------------------
@acct.route("/api/me/watchlist", methods=["GET"])
@login_required
def api_watchlist():
    user = current_user()
    items = WatchlistItem.query.filter_by(user_id=user.id).order_by(WatchlistItem.added_at.desc()).all()
    rows = []
    for it in items:
        p = _price_for(it.ticker)
        rows.append({"ticker": it.ticker, "name": p["name"], "sector": p["sector"], "ltp": p["ltp"],
                     "change": p["change"], "change_pct": p["change_pct"], "source": p["source"]})
    return jsonify({"ok": True, "items": rows})


@acct.route("/api/me/watchlist/status/<ticker>")
@login_required
def api_watch_status(ticker):
    user = current_user()
    on = WatchlistItem.query.filter_by(user_id=user.id, ticker=ticker.upper()).first() is not None
    return jsonify({"ok": True, "watching": on})


@acct.route("/api/me/watchlist", methods=["POST"])
@login_required
def api_watch_add():
    user = current_user()
    data = request.get_json(silent=True) or {}
    ticker = str(data.get("ticker") or "").strip().upper()
    if not TICKER_RE.match(ticker) or not _known_ticker(ticker):
        return jsonify({"ok": False, "error": f"'{ticker or '?'}' isn't a NEPSE symbol we track."}), 400
    if WatchlistItem.query.filter_by(user_id=user.id).count() >= MAX_WATCHLIST:
        return jsonify({"ok": False, "error": f"Watchlist is full ({MAX_WATCHLIST} stocks)."}), 400
    db.session.add(WatchlistItem(user_id=user.id, ticker=ticker))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()  # already on the list -- treat as success
    return jsonify({"ok": True, "ticker": ticker, "watching": True})


@acct.route("/api/me/watchlist/<ticker>", methods=["DELETE"])
@login_required
def api_watch_remove(ticker):
    user = current_user()
    WatchlistItem.query.filter_by(user_id=user.id, ticker=ticker.upper()).delete()
    db.session.commit()
    return jsonify({"ok": True, "ticker": ticker.upper(), "watching": False})


# --- JSON API: portfolio ------------------------------------------------------------
@acct.route("/api/me/portfolio")
@login_required
def api_portfolio():
    user = current_user()
    quantities = {h.ticker: h.quantity for h in Holding.query.filter_by(user_id=user.id).all()}
    prices = {t: _price_for(t) for t in quantities}
    rows, totals = pu.value_holdings(quantities, prices)
    for r in rows:
        r["source"] = (prices.get(r["ticker"]) or {}).get("source")
    market_open = next((p["market_open"] for p in prices.values() if p.get("market_open") is not None), None)
    return jsonify({
        "ok": True,
        "holdings": rows,
        "totals": totals,
        "sectors": pu.sector_breakdown(rows),
        "market_open": market_open,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


@acct.route("/api/me/holdings", methods=["POST"])
@login_required
def api_holding_save():
    """Add a scrip, or replace the quantity if the user already holds it."""
    user = current_user()
    data = request.get_json(silent=True) or {}
    ticker = str(data.get("ticker") or "").strip().upper()
    try:
        if not TICKER_RE.match(ticker):
            raise pu.PortfolioError("Enter a valid NEPSE symbol.")
        try:
            qty = int(str(data.get("quantity")).replace(",", "").strip())
        except (TypeError, ValueError):
            raise pu.PortfolioError("Quantity must be a whole number of shares.")
        if not 1 <= qty <= MAX_QTY:
            raise pu.PortfolioError("Quantity must be at least 1.")
        existing = Holding.query.filter_by(user_id=user.id, ticker=ticker).first()
        if existing is None:
            if not _known_ticker(ticker):
                raise pu.PortfolioError(f"'{ticker}' isn't a NEPSE symbol we track.")
            if Holding.query.filter_by(user_id=user.id).count() >= MAX_HOLDINGS:
                raise pu.PortfolioError(f"Holdings limit reached ({MAX_HOLDINGS}).")
    except pu.PortfolioError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    if existing is None:
        db.session.add(Holding(user_id=user.id, ticker=ticker, quantity=qty))
    else:
        existing.quantity = qty
    db.session.commit()
    return jsonify({"ok": True, "ticker": ticker, "quantity": qty, "updated": existing is not None}), 201


@acct.route("/api/me/holdings/<ticker>", methods=["DELETE"])
@login_required
def api_holding_delete(ticker):
    user = current_user()
    h = Holding.query.filter_by(user_id=user.id, ticker=ticker.upper()).first()
    if h is None:
        return jsonify({"ok": False, "error": "Holding not found."}), 404
    db.session.delete(h)
    db.session.commit()
    return jsonify({"ok": True})
