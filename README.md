# 🇳🇵 NEPSE Intelligence Platform

**Sector-wise Buy/Sell/Hold models for the Nepal Stock Exchange, tested honestly and served through a live Flask dashboard.**

[![Live Demo](https://img.shields.io/badge/demo-live-16a34a?style=flat-square)](https://nepse-intelligence-albt.onrender.com)
[![Python](https://img.shields.io/badge/python-3.11-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.1-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PyTorch](https://img.shields.io/badge/pytorch-2.1-ee4c2c?style=flat-square&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Tests](https://img.shields.io/badge/tests-105%20passing-16a34a?style=flat-square)](tests/)

### 🔗 [**View the live dashboard →**](https://nepse-intelligence-albt.onrender.com)

> Hosted on Render's free tier. An UptimeRobot ping on `/healthz` every 5 minutes keeps it awake, but if it has been asleep the first request can take about 50 seconds.

![NEPSE Intelligence dashboard](app/frontend/static/images/dashboard_preview.png)

---

## Overview

NEPSE Intelligence is an end-to-end machine learning project on Nepal's stock market. It collects daily prices for **270 stocks in 12 sectors**, engineers technical indicators, trains a separate Buy/Sell/Hold model per sector, retrains them every week behind a quality gate, and serves everything through a dashboard with accounts, a watchlist and a portfolio.

The project's main point is honesty about what the models can and cannot do. Every result below comes from data the models never saw, against a simple baseline, with trading costs included. The short version: **the models find a small but real ability to rank stocks, not an ability to make money after NEPSE costs**, and the price forecasts do not beat assuming prices stay the same. The dashboard says exactly that next to every signal and every forecast.

## ✨ Features

| Feature | What it does |
|---|---|
| 🟢 **Sector signal models** | One Buy/Sell/Hold classifier per sector: a PyTorch LSTM for 11 sectors and XGBoost for Manufacturing & Processing |
| 🏷 **Reliability tag on every signal** | Each signal shows how its model did on unseen data against always guessing "Hold": **No edge**, **Unproven** or **Some edge** |
| 🔍 **Why this signal?** | A panel on each stock page showing which inputs pushed the model toward Buy or Sell today, computed live with SHAP-style attributions |
| 📊 **Honest backtest page** | Out-of-sample tests on every stock: signal strength with confidence ranges and trading results after NEPSE fees and tax |
| 📈 **30-day price range** | A Prophet range of likely prices, shown with its tested accuracy and clearly labelled as not a prediction |
| 👤 **Accounts** | Email/password or Google sign-in, password reset by email, watchlist, portfolio with live value and a sector breakdown, stocks-to-research ideas |
| ⚡ **Live market** | Live NEPSE index, market breadth, top gainers and losers, per-stock quotes and price charts |
| 🤖 **Automation** | GitHub Actions refresh prices daily and retrain the models and forecasts weekly; Render redeploys on every push |
| 🎨 **Themes** | Light, dark and system themes across every page and chart |

## 🛠 Tech Stack

**ML and data:** PyTorch · XGBoost · scikit-learn · Prophet · pandas · NumPy

**Web:** Flask · Flask-SQLAlchemy · Authlib (Google OAuth) · Gunicorn · Bootstrap 5 · Chart.js · Plotly

**Data collection:** NepseUnofficialApi (`nepse`) · Selenium · BeautifulSoup

**Infrastructure:** Render · PostgreSQL (Neon/Supabase) · Brevo (email) · GitHub Actions · UptimeRobot · pytest

## 🏗 How It Works

```
Collect prices ──▶ Features ──▶ Sector models ──▶ Quality gate ──▶ Dashboard
 NEPSE daily       23 technical   LSTM × 11         beat or match      Flask + Chart.js
 OHLCV, 270        indicators,    XGBoost × 1       the deployed       signals, reliability,
 stocks            next-day ±1%   (2-year window,   model on a         explanations, ranges,
                   labels         3-month holdout)  shared holdout     accounts
```

**Labels.** Each trading day is labelled from the next day's return: **Buy** above +1%, **Sell** below −1%, **Hold** in between (`ml/features/labeler.py`). Roughly 54% of days are Hold.

**Training and evaluation.** Each sector model is trained on a rolling 2-year window and checked on a **chronological holdout** (the last 3 months, never seen in training), not a random split. LSTM sequences (10 days) are built per stock, and scalers are fit on training data only.

**Weekly retraining.** Every Saturday a workflow retrains all 12 sectors and promotes a new model only if it is not worse than the deployed one on the same holdout (`scripts/retrain_with_gate.py`). It writes `retrain_report.csv`, which the dashboard reads to tag each signal.

## 📊 Results

### Holdout accuracy is mostly "always Hold"

Deployed models after the 24 Oct 2026 retrain, on the holdout since 16 Jul 2026 (`deploy_data/models/retrain_report.csv`):

| Sector | Model | Accuracy | Always-Hold accuracy | Buy/Sell calls | Buy recall | Sell recall | Tag |
|---|---|---|---|---|---|---|---|
| Tradings | LSTM | 75.0% | 75.0% | 0% | 0.00 | 0.00 | No edge |
| Commercial Banks | LSTM | 72.4% | 72.5% | 0% | 0.00 | 0.01 | No edge |
| Life Insurance | LSTM | 69.9% | 69.9% | 0% | 0.00 | 0.00 | No edge |
| Development Banks | LSTM | 62.8% | 62.8% | 22% | 0.10 | 0.32 | Unproven |
| Finance | LSTM | 61.9% | 62.8% | 2% | 0.02 | 0.01 | No edge |
| Investment | LSTM | 61.5% | 61.3% | 13% | 0.00 | 0.24 | Unproven |
| Non Life Insurance | LSTM | 60.6% | 60.7% | 4% | 0.00 | 0.05 | No edge |
| Microfinance | LSTM | 57.5% | 59.3% | 9% | 0.05 | 0.07 | Unproven |
| Hotels And Tourism | LSTM | 57.5% | 60.1% | 12% | 0.00 | 0.15 | Unproven |
| Hydro Power | LSTM | 53.9% | 54.5% | 21% | 0.03 | 0.28 | Unproven |
| Others | LSTM | 53.6% | 55.9% | 21% | 0.04 | 0.18 | Unproven |
| Manufacturing And Processing | XGBoost | 51.7% | 55.7% | 39% | 0.12 | 0.47 | Unproven |

No sector beats always guessing Hold. Most LSTMs collapse to predicting Hold almost every day, so their accuracy is just the share of Hold days. The dashboard therefore shows **"No signal"** for those sectors instead of a Hold badge (`app/backend/model_evidence.py`).

Things tried that did not fix it: removing noisy short-history stocks and unadjusted bonus/rights price jumps (moved accuracy by under 1%), percentile-based labels (fixed 4 of 8 sectors but lowered accuracy, reverted), and class-weighted training (real Buy/Sell calls and better macro-F1 in 9 of 12 sectors, but lost money in the backtest, so not adopted).

### Do the signals make money? No.

Accuracy is the wrong test for a trading signal, so two stricter tests were run, with pass rules fixed before running:

| Test | What it covers | Signal strength (rank IC) | Weekly top 20% vs sector, after costs |
|---|---|---|---|
| Deployed models (`scripts/evaluate_signals_oos.py`) | every stock, 16 Jul – 16 Oct 2026 (models deployed until 24 Oct) | **+0.036** (95% range +0.014 to +0.062) | −1.7 bp/day (−7.4 to +4.7) |
| Walk-forward (`scripts/walkforward_signals.py`) | retrained on the 2 years before each of 6 quarters, Oct 2024 – Mar 2026 | **+0.026** (+0.015 to +0.037), positive in 5 of 6 quarters | **−6.1 bp/day** (−9.0 to −2.5) |

The models can rank stocks a little better than chance, clearest in Manufacturing, Microfinance, Hydro Power and Non Life Insurance, but the edge is far too small to cover NEPSE costs (0.33% brokerage, 0.015% SEBON fee, Rs 25 DP charge, 10% capital gains tax). Following the Buy/Sell signals shows no reliable gain over simply holding the stock. A side test found XGBoost ranks slightly better than the LSTM in the other 11 sectors (+0.035 vs +0.020) but trades more and loses more to costs. All of this is shown on the `/backtest` page from `deploy_data/models/signal_evidence.json`.

### Price forecasts do not beat "no change"

`scripts/validate_forecasts.py` re-fitted Prophet from 5 past start dates on 260 stocks and compared it with simply assuming the price stays the same:

| 30 trading days ahead | Average error | Direction right | 80% range contains the real price |
|---|---|---|---|
| "No change" | **5.6%** | n/a | n/a |
| Original setup (full history since 2011, yearly seasonality) | 18.2% | 54% | 48% |
| **Deployed: last 2 years, started from the last close** | 7.3% | 43% | 73% |

The original setup also forecast a fake ~7% drop every Friday, because NEPSE traded Sunday to Thursday until April 2026. The deployed recipe fixes that and is far less wrong, but it still loses to "no change". So the dashboard shows it as a **30-day range of likely prices** with these numbers beside it, and the portfolio's Ideas tab does not use it.

### What was dropped

**News sentiment** (FinBERT on ShareSansar headlines) was removed from the site in October 2026: only about five weeks of market-wide headlines existed, far too little to train on or test against two-year models, and matching headlines to individual stocks was unreliable.

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/roshanpandey-1/Nepal-Stock-Market-Predictor-Dashboard.git
cd Nepal-Stock-Market-Predictor-Dashboard

# 2. Virtual environment
python -m venv env
env\Scripts\activate              # macOS/Linux: source env/bin/activate

# 3. Install
pip install -r requirements-web.txt   # dashboard only
# pip install -r requirements.txt     # full pipeline: scraping, training, forecasting, notebooks

# 4. Run the dashboard
python run.py                     # → http://localhost:5000
```

`python run.py` serves the committed `deploy_data/` snapshot, the same data and models as the live site, so no download is needed. Accounts use a local SQLite file (`instance/accounts.db`) unless `DATABASE_URL` is set. To use your full local dataset instead, set `DATA_DIR=data` (PowerShell: `$env:DATA_DIR="data"; python run.py`). See [`.env.example`](.env.example) for every setting.

### Pipeline scripts

All scripts run from the repo root.

| Command | Purpose |
|---|---|
| `python scripts/data_snapshot.py unpack` | Unpack the full price history (`data-snapshot.tar.gz`, from the `data-latest` GitHub release) into `data/` |
| `python scripts/fetch_historical_data.py` | Build the full history from scratch |
| `python scripts/fetch_incremental_data.py` | Add the latest trading days (used daily by GitHub Actions) |
| `python scripts/fetch_new_tickers.py` | Add newly listed stocks |
| `python scripts/retrain_with_gate.py plan` / `run` / `publish` | Weekly retrain with the quality gate |
| `python scripts/run_backtests_oos.py` | One-stock-per-sector demonstration backtest |
| `python scripts/build_forecasts.py` | Rebuild the Prophet price ranges |
| `python scripts/evaluate_signals_oos.py` | Test the deployed signals on every stock |
| `python scripts/walkforward_signals.py` | Walk-forward test over six past quarters |
| `python scripts/validate_forecasts.py` | Test the price forecasts against "no change" |
| `python scripts/build_deploy_snapshot.py` | Rebuild `deploy_data/` from `data/` |
| `pytest` | Run the test suite (105 tests) |

## 🤖 Automation (GitHub Actions)

| Workflow | Schedule | What it does |
|---|---|---|
| Refresh daily prices | Mon–Fri, after market close | Fetches new prices into the full-history release and refreshes `deploy_data/processed` |
| Weekly forecasts and retraining | Saturday | Rebuilds the price ranges, retrains every sector and promotes a model only if it passes the quality gate |
| Monthly backtest | 1st of each month | Re-runs the one-stock-per-sector backtest |
| Class-weight experiment | Manual | Compares class-weighted training with the deployed models; deploys nothing |

Every bot commit to `main` triggers a Render redeploy.

## 📁 Project Structure

```
.
├── app/                        # Web app
│   ├── __init__.py             # App factory, database setup, /healthz
│   ├── backend/                # Python server code
│   │   ├── routes.py           # Pages: dashboard, stock, backtest, privacy, terms
│   │   ├── api.py              # JSON API: signals, explanations, price ranges, live market
│   │   ├── accounts.py         # Sign-in, Google OAuth, password reset, watchlist, portfolio
│   │   ├── database.py         # Database tables (users, watchlist, holdings, searches)
│   │   ├── model_evidence.py   # Reliability tag for each sector model
│   │   ├── explain.py          # "Why this signal?" attributions
│   │   ├── insights.py         # Ideas to research, portfolio price ranges
│   │   ├── portfolio_utils.py  # Holding valuation
│   │   └── mailer.py           # Password-reset email (Brevo)
│   └── frontend/               # What the browser gets
│       ├── templates/          # Jinja2 pages
│       └── static/             # CSS, JavaScript, images
├── ml/                         # Machine learning code
│   ├── scraper/                # Live NEPSE market data
│   ├── features/               # Technical indicators and labels
│   ├── models/                 # Sector trainer (LSTM/XGBoost) and Prophet forecaster
│   └── backtesting/            # Strategy simulation and metrics
├── scripts/                    # Runnable pipeline and evaluation scripts (used by GitHub Actions)
├── notebooks/                  # Early experiments (kept as a record; may use older code)
├── tests/                      # pytest suite
├── data/                       # Full local dataset (gitignored)
├── deploy_data/                # Trimmed data and models the live site serves (committed)
├── .github/workflows/          # Scheduled data and model jobs
├── run.py                      # Entry point (python run.py, gunicorn run:app)
├── requirements-web.txt        # Dashboard dependencies (Render)
├── requirements.txt            # Full pipeline dependencies
├── render.yaml · Procfile      # Deployment config
└── DEPLOYMENT.md               # Deployment and account setup guide
```

## 🌐 Deployment

The dashboard runs on **Render** (`render.yaml`): it installs `requirements-web.txt` and starts `gunicorn run:app`. Because `data/` is gitignored, the live site reads `deploy_data/` (selected with `DATA_DIR=deploy_data`). Accounts live in a hosted PostgreSQL database so they survive redeploys, password-reset emails go through Brevo, and Google sign-in uses an OAuth client. Full setup in [`DEPLOYMENT.md`](DEPLOYMENT.md).

## 🗺 Status and next steps

- [x] Automated daily price refresh and weekly retraining with a quality gate
- [x] Reliability tags and SHAP-style explanations on every signal
- [x] Out-of-sample and walk-forward tests of the signals, after costs
- [x] Price forecast validation (and fixing the Friday dip)
- [x] Accounts with Google sign-in and password reset
- [ ] Re-test the five sector models replaced in the 24 Oct 2026 retrain
- [ ] Find features that carry more signal than price-based indicators (for example fundamentals or corporate actions)

## ⚠️ Disclaimer

This project is for **educational and research purposes only** and is not financial advice. As shown above, the models do not produce profitable trading signals and the price ranges are not predictions. Always consult a licensed financial advisor before investing. See the site's [Terms](https://nepse-intelligence-albt.onrender.com/terms) and [Privacy Policy](https://nepse-intelligence-albt.onrender.com/privacy).

## 👤 Author

**Roshan Pandey**

[Portfolio](https://roshanpandey-1.github.io) · [GitHub](https://github.com/roshanpandey-1)
