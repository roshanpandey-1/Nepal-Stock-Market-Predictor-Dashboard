"""Check every active alert once and email the people whose alerts fired.

Called by scripts/run_alerts.py after the daily price refresh. It needs the database and the
mailer but not the web app, and it never writes email addresses or message text to the log.
"""
import json
import logging
from html import escape

from ml.analysis import alerts as alerts_engine
from ml.analysis import external, market

from . import mailer as default_mailer
from .database import AlertRule, User, db

logger = logging.getLogger(__name__)
DEFAULT_SITE = "https://nepse-intelligence-albt.onrender.com"


def build_email(name, session, fired, site_url=DEFAULT_SITE):
    """(subject, text, html) for one person. `fired` = [(ticker, description, [messages], [links])]."""
    subject = f"NEPSE Intelligence: {len(fired)} alert{'s' if len(fired) != 1 else ''} for the {session} session"
    text = [f"Hello {name},", "", f"These alerts you set up were triggered by the {session} session:", ""]
    html = [f"<p>Hello {escape(name)},</p>", f"<p>These alerts you set up were triggered by the {escape(session)} session:</p><ul>"]
    for ticker, desc, messages, links in fired:
        text.append(f"{ticker} ({desc})")
        html.append(f"<li><strong><a href=\"{escape(site_url)}/stock/{escape(ticker)}\">{escape(ticker)}</a></strong> ({escape(desc)})<ul>")
        for m in messages:
            text.append(f"  - {m}")
            html.append(f"<li>{escape(m)}</li>")
        for link in links:
            text.append(f"    {link}")
        text.append(f"  {site_url}/stock/{ticker}")
        text.append("")
        html.append("</ul></li>")
    footer = ("These checks use end-of-day data and run once a day. They are a reminder to look at a stock, not advice "
              f"to buy or sell. Manage or delete your alerts at {site_url}/alerts.")
    text += [footer]
    html += ["</ul>", f"<p style=\"color:#666;font-size:12px\">{escape(footer)}</p>"]
    return subject, "\n".join(text), "".join(html)


def run(data_dir, send=True, mail=default_mailer, site_url=DEFAULT_SITE):
    """Evaluate all active rules. Returns counts only. Rules change only after their email is accepted,
    so a failed send is retried at the next run instead of being lost."""
    session, table = market.stock_table(data_dir)
    by_ticker = {r["ticker"]: r for r in table}
    stats = {"session": session, "rules": 0, "skipped": 0, "fired": 0, "people": 0, "emails_sent": 0, "emails_failed": 0}
    if not session:
        return stats
    if send and not mail.mail_configured():
        stats["error"] = "email is not configured (BREVO_API_KEY / MAIL_SENDER); nothing was changed"
        return stats
    users = {u.id: u for u in User.query.join(AlertRule, AlertRule.user_id == User.id).filter(AlertRule.active.is_(True)).all()}
    for user in users.values():
        rules = AlertRule.query.filter_by(user_id=user.id, active=True).all()
        fired, updates = [], []
        for r in rules:
            stats["rules"] += 1
            items = external.announcements(data_dir, ticker=r.ticker, limit=200)["items"] if r.kind == "announcement" else ()
            out = alerts_engine.evaluate(
                {"kind": r.kind, "threshold": r.threshold, "category": r.category, "state": r.state, "seen": r.seen,
                 "created": r.created_at.date().isoformat(), "ticker": r.ticker},
                by_ticker.get(r.ticker), session, items)
            if out["skip"]:
                stats["skipped"] += 1
                continue
            updates.append((r, out))
            if out["fire"]:
                fired.append((r.ticker, alerts_engine.describe(r.kind, r.threshold, r.category), out["messages"], out.get("links", [])))
        ok = True
        if fired:
            stats["fired"] += len(fired)
            stats["people"] += 1
            if send:
                subject, text, html = build_email(user.display_name, session, fired, site_url)
                ok = bool(mail.send_email(user.email, subject, text, html))
                stats["emails_sent" if ok else "emails_failed"] += 1
        if not ok:
            db.session.rollback()
            continue
        for r, out in updates:
            r.state, r.last_checked = out["state"], session
            if out["fire"]:
                r.last_fired = session
                r.last_message = " | ".join(out["messages"])[:300]
            if "seen" in out:
                r.seen = json.dumps(out["seen"])
        db.session.commit()
    logger.info("alerts: %s", stats)
    return stats
