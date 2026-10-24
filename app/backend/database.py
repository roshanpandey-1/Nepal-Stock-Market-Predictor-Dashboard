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
