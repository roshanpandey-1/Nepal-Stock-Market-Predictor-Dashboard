import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask

logger = logging.getLogger(__name__)


def _database_uri():
    """DATABASE_URL (Postgres on Render) or a local SQLite file for development.

    Render/Heroku-style `postgres://` URLs are rewritten for SQLAlchemy. Returns
    (uri, ephemeral): `ephemeral` is True when we fell back to SQLite on a host
    whose disk is wiped on every deploy, so the UI can warn about it.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url, False
    path = Path(os.environ.get("SQLITE_PATH", "instance/accounts.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.resolve()}", bool(os.environ.get("RENDER"))


def create_app(test_config=None):
    # Pages and assets live in app/frontend so the browser side is one folder.
    # static_url_path stays "/static", so every URL on the site is unchanged.
    app = Flask(__name__, template_folder="frontend/templates",
                static_folder="frontend/static", static_url_path="/static")

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        # A random per-process key is safe but logs everyone out on every restart.
        # Never fall back to a fixed, public string.
        secret = secrets.token_hex(32)
        logger.warning("SECRET_KEY is not set; using a temporary key (sessions reset on restart).")
    app.secret_key = secret

    uri, ephemeral = _database_uri()
    on_render = bool(os.environ.get("RENDER"))
    app.config.update(
        SQLALCHEMY_DATABASE_URI=uri,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        DB_EPHEMERAL=ephemeral,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=on_render,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        GOOGLE_ENABLED=bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET")),
    )
    if test_config:
        app.config.update(test_config)

    if on_render:
        # Render terminates TLS in front of gunicorn; trust its forwarded headers so
        # url_for(_external=True) (the Google callback URL) is https.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from app.routes import main
    from app.api import api
    app.register_blueprint(main)
    app.register_blueprint(api, url_prefix="/api")

    @app.route("/healthz")
    def healthz():
        # Tiny, database-free page for uptime pingers (keeps Render's free
        # plan from sleeping) and Render's own health check.
        return "ok", 200, {"Cache-Control": "no-store", "Content-Type": "text/plain"}

    _init_accounts(app)
    return app


def _init_accounts(app):
    """Accounts are optional infrastructure: if anything here fails the public
    dashboard still starts and serves."""
    from app.models import db
    from app.accounts import acct
    db.init_app(app)
    app.register_blueprint(acct)

    if app.config["GOOGLE_ENABLED"]:
        from authlib.integrations.flask_client import OAuth
        oauth = OAuth(app)
        oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        app.extensions["oauth_client"] = oauth

    with app.app_context():
        try:
            db.create_all()
        except Exception:
            logger.exception("Could not create/connect to the accounts database; "
                             "login pages will show an 'unavailable' message.")
    if app.config["DB_EPHEMERAL"]:
        logger.warning("DATABASE_URL is not set on Render: accounts use a local SQLite file "
                       "that is wiped on every deploy.")
