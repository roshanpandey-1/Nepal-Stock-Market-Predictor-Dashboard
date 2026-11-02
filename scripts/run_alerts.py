"""Send the daily alert emails.

    python scripts/run_alerts.py --data-dir deploy_data [--dry-run]

Run by .github/workflows/refresh-prices.yml after the prices and announcements are refreshed.
Needs DATABASE_URL (the accounts database), BREVO_API_KEY and MAIL_SENDER as secrets, and
optionally SITE_URL. Prints counts only, never addresses or message text. With no DATABASE_URL
it does nothing and exits 0, so it can never stop the price refresh.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="deploy_data")
    ap.add_argument("--dry-run", action="store_true", help="evaluate and print counts; send nothing, change nothing")
    args = ap.parse_args(argv)

    if not os.environ.get("DATABASE_URL", "").strip():
        print("alerts: DATABASE_URL is not set; nothing to do")
        return 0

    from flask import Flask

    from app import _database_uri
    from app.backend import alert_runner
    from app.backend.database import db, ensure_schema

    app = Flask(__name__)
    uri, _ = _database_uri()
    app.config.update(SQLALCHEMY_DATABASE_URI=uri, SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        ensure_schema(db.engine)
        stats = alert_runner.run(args.data_dir, send=not args.dry_run,
                                 site_url=os.environ.get("SITE_URL", alert_runner.DEFAULT_SITE).rstrip("/"))
        if args.dry_run:
            db.session.rollback()
    print("alerts:", ", ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
