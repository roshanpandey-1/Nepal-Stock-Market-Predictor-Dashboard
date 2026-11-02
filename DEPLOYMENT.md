# Deploying the dashboard (Render)

The live site runs the Flask app in `app/` as a web service on [Render](https://render.com)'s free tier:
https://nepse-intelligence-albt.onrender.com

## What the repo provides

- `run.py` creates the app; Render starts it with `gunicorn run:app`.
- `requirements-web.txt` is the slim dependency list for serving the dashboard (Flask, PyTorch, scikit-learn,
  XGBoost, accounts and live-market packages). Training-only packages (Prophet, Selenium, notebooks) are left out.
- `deploy_data/` is a trimmed, committed snapshot of the data and models the site needs (see
  `deploy_data/README.md`). The full `data/` folder stays local and gitignored.
- `render.yaml` defines the service: build command, start command, `/healthz` health check and the environment
  variables. `Procfile` has the same start command for hosts that read a Procfile.

## First deploy

1. Push the repo to GitHub.
2. On Render: **New → Blueprint**, pick this repo. Render reads `render.yaml` and sets up the build
   (`pip install -r requirements-web.txt`), the start command (`gunicorn run:app --bind 0.0.0.0:$PORT --timeout 120`)
   and `DATA_DIR=deploy_data`.

   Manual alternative: **New → Web Service**, Python 3, same build and start commands, and set
   `DATA_DIR=deploy_data` and `PYTHON_VERSION=3.11.9`.
3. Set the remaining environment variables below, then deploy. The first build takes a few minutes (PyTorch is
   the slow part).

## Environment variables

| Variable | Needed for | Notes |
|---|---|---|
| `DATA_DIR` | everything | `deploy_data` on Render |
| `PYTHON_VERSION` | build | `3.11.9` |
| `SECRET_KEY` | sign-in sessions | `render.yaml` generates one; keep it stable, changing it logs everyone out |
| `DATABASE_URL` | accounts | PostgreSQL connection string (Neon or Supabase). Without it accounts use a local SQLite file that Render wipes on every deploy |
| `BREVO_API_KEY`, `MAIL_SENDER` | password-reset email | `MAIL_SENDER_NAME` is optional |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google sign-in | the Google button stays disabled until both are set |

### Database

Create a free PostgreSQL database on [Neon](https://neon.tech) or [Supabase](https://supabase.com) and set its
connection string (`postgresql://user:pass@host/dbname?sslmode=require`) as `DATABASE_URL`. Tables are created
automatically on first start.

### Password-reset email (Brevo)

Render's free tier blocks SMTP, so emails go through Brevo's HTTPS API (free, about 300 emails a day):

1. Sign up at [brevo.com](https://www.brevo.com) and, under **Senders, Domains & Dedicated IPs → Senders**, add
   and verify a sender address (a Gmail address works).
2. **SMTP & API → API keys**: create a key.
3. On Render set `BREVO_API_KEY` and `MAIL_SENDER` (the verified address).

Without these the site still works but sends no email; the reset link is only written to the server log, which
is handy locally. Emails from a free Gmail sender can land in spam.

### Google sign-in

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and open **Google Auth Platform**.
2. **Branding**: app name, support email, home page `https://nepse-intelligence-albt.onrender.com`, privacy policy
   `https://nepse-intelligence-albt.onrender.com/privacy`, terms `https://nepse-intelligence-albt.onrender.com/terms`,
   authorised domain `nepse-intelligence-albt.onrender.com` (no `https://`), developer contact email. Do not upload
   a logo, which would require Google's review.
3. **Audience**: External, then **Publish app** so any Google account can sign in. The app only asks for name and
   email, so no verification is needed.
4. **Clients → Create client**: Web application, authorised JavaScript origin
   `https://nepse-intelligence-albt.onrender.com`, authorised redirect URI
   `https://nepse-intelligence-albt.onrender.com/auth/google/callback`.
5. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on Render and redeploy.

A Google account with the same email as an existing account is linked to it.

## Alert emails

Alerts are set on the website (`/alerts`) and checked by the daily GitHub workflow, because Render's free tier
sleeps and has no scheduler. The workflow step "Send alert emails" reads the accounts database directly, so add
these as **repository secrets** (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `DATABASE_URL` | The same PostgreSQL connection string Render uses |
| `BREVO_API_KEY` | The same Brevo API key as the password-reset emails |
| `MAIL_SENDER` | The same verified sender address |
| `SITE_URL` | Optional: the site address used in the email links (defaults to the Render URL) |

Without `DATABASE_URL` the step does nothing, and it can never stop the price refresh (it is `continue-on-error`).
Secrets are encrypted by GitHub and are never in the code or the browser. The script prints counts only, never
addresses or message text, and each email contains only that person's own alerts. A rule fires when its condition
turns from false to true; if an email is not accepted by Brevo the rule is left unchanged and retried the next day.
Try it without sending anything: `DATABASE_URL=... python scripts/run_alerts.py --dry-run`.

## Keeping it awake

The free tier sleeps after 15 minutes without traffic. An [UptimeRobot](https://uptimerobot.com) HTTP monitor on
`https://nepse-intelligence-albt.onrender.com/healthz` every 5 minutes keeps it awake; `/healthz` is a lightweight
endpoint made for this.

## Keeping the data current

GitHub Actions update `deploy_data/` automatically (daily prices, weekly models and price ranges) and push to
`main`, and Render redeploys on every push. To refresh it by hand from your full local `data/`:

```
python scripts/build_deploy_snapshot.py
git add deploy_data/
git commit -m "Refresh deploy_data snapshot"
git push origin main
```

## Known constraints

- **Signals are illustrative, not advice.** Every signal carries a reliability tag, and the Backtest page shows
  that the models do not make money after trading costs.
- **The 30-day price range is not a prediction.** It did not beat "no change" in testing, and the page says so.
- **Portfolio profit and loss is gross.** Brokerage, SEBON, DP charges and capital gains tax are not deducted,
  and it is only shown for holdings where the user entered a buy price.
- **Market totals are for tracked stocks only.** The daily report and market views add up the ~270 stocks we track;
  they are not the official NEPSE index or NEPSE's published totals. The official index close is captured on a
  best-effort basis and the report says when it is missing.
- **Fundamentals are as reported on Merolagani.** It is an unofficial source and quarterly figures are mostly
  unaudited; every figure shows its source and collection date and is flagged when more than three weeks old.
  If Merolagani or ShareSansar change their page layout, the collectors fail loudly rather than store bad data.
- **Alerts use end-of-day data** and run once a day after the refresh, so they are not intraday price alerts.
- **First load after a restart.** Building the market table reads all ~270 stock files (about 1 s on a laptop,
  several seconds on the free tier). On Render the app starts this in the background at start-up, so visitors
  rarely wait for it.
