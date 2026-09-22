# Deploying the dashboard live (Render)

This deploys `app/` (the Flask dashboard) as a public web service on
[Render](https://render.com)'s free tier.

## What's already set up in this repo

- `deploy_data/` — a trimmed, git-committed snapshot of the data/models the
  dashboard needs (see `deploy_data/README.md`). The full `data/` directory
  stays local and gitignored, as before.
- `requirements-web.txt` — slim dependency list for *serving* the dashboard
  (Flask, torch, scikit-learn, xgboost) — leaves out training-only packages
  (Prophet, Transformers, SHAP, Optuna, LightGBM, Selenium) that this process
  never imports.
- `render.yaml` — Render's service definition (build command, start command,
  the `DATA_DIR=deploy_data` environment variable that switches the app onto
  the trimmed snapshot instead of the full local `data/` folder).
- `Procfile` — same start command, for any host that reads a Procfile instead
  of `render.yaml` (Railway, Heroku-style hosts).

## Steps

1. **Push this repo to GitHub** (if you haven't already):
   ```
   git push origin main
   ```

2. **Create a Render account** at [render.com](https://render.com) (free,
   sign in with GitHub is easiest).

3. **New → Blueprint**, and point it at this GitHub repo. Render will read
   `render.yaml` automatically and set up the service with the right build
   command, start command, and `DATA_DIR` environment variable already
   filled in — you shouldn't need to configure anything by hand.

   (If you'd rather set it up manually instead of via the Blueprint: New →
   Web Service → select this repo → Runtime: Python 3 → Build Command:
   `pip install -r requirements-web.txt` → Start Command:
   `gunicorn run:app --bind 0.0.0.0:$PORT --timeout 120` → add an environment
   variable `DATA_DIR=deploy_data`.)

4. **Deploy.** First build will take a few minutes (torch is the slow part).
   Render gives you a URL like `https://nepse-intelligence.onrender.com`
   once it's live.

## Notes / known constraints

- **Free tier sleeps after inactivity.** The first request after a period of
  no traffic can take 30-60 seconds while the instance spins back up. This
  is a Render free-tier limitation, not a bug in the app.
- **Signals are illustrative, not advice.** The dashboard surfaces this
  directly (see the limitation banners on the Dashboard and Stock Detail
  pages) — 6 of 8 sector models default heavily to "Hold" on unseen data.
  See `README.md`'s Known Limitations section.
- **`/api/forecast/<ticker>` returns price history, not a forecast.** No
  forecasting model has been built/validated in this project yet, so the
  chart is honestly historical, not predictive.

## Keeping the live site's data current

The live site only sees `deploy_data/`, which is a snapshot. To refresh it
after retraining models or pulling new price data:
```
python examples/build_deploy_snapshot.py
git add deploy_data/
git commit -m "Refresh deploy_data snapshot"
git push origin main
```
Render redeploys automatically on every push to `main`.
