"""Database models for user accounts, watchlists and portfolio transactions.

Holdings are never stored: they are derived from the transaction log (see
app/backend/portfolio_utils.py), so editing or deleting a past transaction can never
leave a stale balance behind.
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _now():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    name = db.Column(db.String(80))
    # NULL for accounts created through Google sign-in only.
    password_hash = db.Column(db.String(255))
    google_sub = db.Column(db.String(64), unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)

    watchlist = db.relationship("WatchlistItem", backref="user", cascade="all, delete-orphan")
    holdings = db.relationship("Holding", backref="user", cascade="all, delete-orphan")
    alerts = db.relationship("AlertRule", backref="user", cascade="all, delete-orphan")
    searches = db.relationship("SearchHistory", backref="user", cascade="all, delete-orphan")

    @property
    def display_name(self):
        return self.name or self.email.split("@")[0]


class WatchlistItem(db.Model):
    __tablename__ = "watchlist_items"
    __table_args__ = (db.UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ticker = db.Column(db.String(20), nullable=False)
    added_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)


class Holding(db.Model):
    """Shares of one scrip the user owns (the balance, as Meroshare shows it)."""
    __tablename__ = "holdings"
    __table_args__ = (db.UniqueConstraint("user_id", "ticker", name="uq_holding_user_ticker"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ticker = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    # Optional: what the user paid per share on average, typed in by them (never guessed).
    avg_cost = db.Column(db.Float)
    updated_at = db.Column(db.DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class SearchHistory(db.Model):
    """Tickers a user opened from the search bar; one row per ticker, newest wins."""
    __tablename__ = "search_history"
    __table_args__ = (db.UniqueConstraint("user_id", "ticker", name="uq_search_user_ticker"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ticker = db.Column(db.String(20), nullable=False)
    searched_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)


class AlertRule(db.Model):
    """One alert a user set up, e.g. "NABIL closes above 1100" or "volume spike on NICA".

    Rules are checked once a day after the end-of-day data is refreshed. A rule fires
    when its condition turns from false to true (not on every day it stays true), and
    is re-armed when the condition turns false again.
    """
    __tablename__ = "alert_rules"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ticker = db.Column(db.String(20), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    threshold = db.Column(db.Float)             # price, percent, RSI level or volume multiple
    category = db.Column(db.String(30))         # announcement category filter (optional)
    active = db.Column(db.Boolean, default=True, nullable=False)
    state = db.Column(db.Boolean, default=False, nullable=False)   # condition was true at last check
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)
    last_checked = db.Column(db.String(10))     # session date (YYYY-MM-DD) of the last check
    seen = db.Column(db.Text, default="[]", nullable=False)   # announcements: links already alerted on (JSON list)
    last_fired = db.Column(db.String(10))       # session date of the last alert email
    last_message = db.Column(db.String(300))


def ensure_schema(engine):
    """Add columns that were introduced after a table was first created.

    db.create_all() creates missing tables but never alters existing ones, so a
    deployed database would otherwise lack newer columns. Only ever adds nullable
    columns, so it is safe to run on every start.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    wanted = {"holdings": [("avg_cost", "FLOAT")]}
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
