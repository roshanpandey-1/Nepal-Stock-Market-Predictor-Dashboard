"""Transactional email through Brevo's HTTPS API.

Plain SMTP is blocked on Render's free tier, so we call Brevo over HTTPS.
Configure with environment variables:
  BREVO_API_KEY      API key (Brevo -> SMTP & API -> API keys)
  MAIL_SENDER        a sender address you verified in Brevo (e.g. your Gmail)
  MAIL_SENDER_NAME   optional display name (default "NEPSE Intelligence")

Without BREVO_API_KEY nothing is sent; the message is logged instead so password
reset can still be tried locally.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)
API_URL = "https://api.brevo.com/v3/smtp/email"


def mail_configured():
    return bool(os.environ.get("BREVO_API_KEY") and os.environ.get("MAIL_SENDER"))


def send_email(to, subject, text, html=None):
    """Send one email. Returns True if the provider accepted it."""
    if not mail_configured():
        logger.warning("Email is not configured (BREVO_API_KEY / MAIL_SENDER). "
                       "Would have sent to %s: %s\n%s", to, subject, text)
        return False
    payload = {
        "sender": {"email": os.environ["MAIL_SENDER"],
                   "name": os.environ.get("MAIL_SENDER_NAME", "NEPSE Intelligence")},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        payload["htmlContent"] = html
    try:
        r = requests.post(API_URL, json=payload, timeout=10,
                          headers={"api-key": os.environ["BREVO_API_KEY"], "accept": "application/json"})
    except requests.RequestException:
        logger.exception("Could not reach the email provider")
        return False
    if r.status_code >= 300:
        logger.error("Email provider rejected the message (%s): %s", r.status_code, r.text[:300])
        return False
    return True
