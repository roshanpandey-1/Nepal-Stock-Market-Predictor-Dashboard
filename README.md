# 🇳🇵 NEPSE Intelligence Platform

**Sector-wise Buy/Sell/Hold signal models and news-sentiment analysis for the Nepal Stock Exchange, served through a live Flask dashboard.**

[![Live Demo](https://img.shields.io/badge/demo-live-16a34a?style=flat-square)](https://nepse-intelligence-albt.onrender.com)
[![Python](https://img.shields.io/badge/python-3.10-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.0-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PyTorch](https://img.shields.io/badge/pytorch-2.1-ee4c2c?style=flat-square&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![Tests](https://img.shields.io/badge/tests-23%20passing-16a34a?style=flat-square)](tests/)

### 🔗 [**View the live dashboard →**](https://nepse-intelligence-albt.onrender.com)

> Hosted on Render's free tier, which sleeps after 15 minutes of inactivity — the first request may take ~50 seconds to wake the instance.

![NEPSE Intelligence dashboard](app/static/images/dashboard_preview.png)

---

## Overview

NEPSE Intelligence is an end-to-end machine learning pipeline built around Nepal's stock market: it scrapes daily price data and financial news, engineers technical indicators, trains a separate classifier per market sector, evaluates them on a true out-of-sample holdout, and serves the results through an interactive dashboard.

The project covers **270 tickers across 12 sectors**, and deliberately reports its results honestly — including [a significant limitation](#-known-limitation-majority-class-collapse) in the current models that most portfolio projects would quietly omit.

## ✨ Features

| Feature | Description |
|---|---|
| 🟢 **Signal Classification** | A Buy/Sell/Hold classifier per sector — PyTorch LSTM for 7 sectors, XGBoost for Manufacturing & Processing |
| 📊 **Out-of-Sample Backtesting** | Strategy simulation against a Buy-and-Hold benchmark on a chronological holdout, reporting return, Sharpe, max drawdown and win rate |
| 📰 **News Sentiment** | FinBERT (HuggingFace Transformers) scores NEPSE headlines scraped from Sharesansar, aggregated into a daily market sentiment index |
| 📈 **Market Dashboard** | Live ticker strip, market breadth, top gainers/losers, per-stock OHLCV detail pages and interactive Chart.js price history with crosshair hover |
| 🎨 **Light / Dark / System Themes** | Full theming across every page and chart, persisted per visitor |

## 🛠 Tech Stack

**ML & Data** — `PyTorch` · `XGBoost` · `scikit-learn` · `HuggingFace Transformers (FinBERT)` · `pandas` · `NumPy`

**Web** — `Flask` · `Gunicorn` · `Chart.js` · `Bootstrap 5`

**Data Collection** — `BeautifulSoup` · `Selenium` · `nepse`

**Infrastructure** — `Render` · `pytest`

## 🏗 How It Works

```
Scrape ──▶ Feature Engineering ──▶ Sector Training ──▶ Backtest ──▶ Dashboard
  │                │                      │                │            │
NEPSE OHLCV    23 technical          LSTM × 7         Chronological  Flask +
+ Sharesansar  indicators +          XGBoost × 1      holdout vs.    Chart.js
  headlines    forward-return        (per sector)     Buy & Hold
               labels
```

**Why sector-wise models?** NEPSE sectors behave very differently — hydropower is dominated by project-completion news, while commercial banks track interest-rate cycles. A single market-wide model blurs those regimes, so each sector gets its own classifier trained only on its own tickers.

**Evaluation methodology.** Models are trained on a rolling 2-year window and evaluated on a **chronological holdout** (the final 3 months, never seen during training) — not a random train/test split. LSTM sequences are built per-ticker to prevent cross-ticker leakage, and scalers are fit on training data only. This makes the reported numbers reflect genuine forward-looking performance rather than in-sample memorization.

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/roshanpandey-1/Nepal-Stock-Market-Predictor-Dashboard.git
cd Nepal-Stock-Market-Predictor-Dashboard

# 2. Virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt   # full pipeline (training + scraping)
# pip install -r requirements-web.txt   # dashboard only (lighter)

# 4. Fetch stock data
python examples/fetch_stock_data.py

# 5. Run the dashboard
python run.py                     # → http://localhost:5000
```

**Run the dashboard without the full dataset:** the repo ships a trimmed snapshot used by the live deployment.

```bash
DATA_DIR=deploy_data python run.py
```

### Other entry points

| Command | Purpose |
|---|---|
| `python src/models/sector_trainer.py` | Train all sector models |
| `python examples/run_backtests_oos.py` | Out-of-sample backtest across sectors |
| `python examples/sentiment_demo.py` | Scrape + score news sentiment |
| `python examples/build_deploy_snapshot.py` | Regenerate `deploy_data/` for deployment |
| `pytest` | Run the test suite (23 tests) |

## 📊 Results

Buy/Sell/Hold classifiers, one per NEPSE sector, trained on a rolling 2-year window ending September 2026. All figures below are from the **chronological holdout** (last 3 months, unseen during training).

| Sector | Model | Holdout Accuracy | Sell Recall | Buy Recall |
|---|---|---|---|---|
| Commercial Banks | LSTM | 71.3% | 0.00 | 0.00 |
| Life Insurance | LSTM | 69.6% | 0.01 | 0.00 |
| Development Banks | LSTM | 64.3% | 0.32 | 0.02 |
| Finance | LSTM | 60.2% | 0.01 | 0.00 |
| Manufacturing And Processing | XGBoost | 59.8% | 0.19 | 0.15 |
| Non Life Insurance | LSTM | 58.9% | 0.00 | 0.00 |
| Microfinance | LSTM | 57.7% | 0.04 | 0.00 |
| Hydro Power | LSTM | 53.6% | 0.00 | 0.00 |

### ⚠️ Known limitation: majority-class collapse

The accuracy column looks reasonable at a glance, but most of it comes from the model predicting **"Hold" for nearly every sample**. The label distribution is Hold-dominated, and without class weighting the model learns that always predicting Hold is the lowest-risk strategy.

**Most of the 12 sectors have near-zero Buy/Sell recall on the recent holdout** — they are not producing usable trading signals. On the deployed models, Tradings, Life Insurance and Non Life Insurance score exactly like an always-Hold predictor, and Commercial Banks, Microfinance and Finance are barely above it. Only Manufacturing & Processing and Development Banks meaningfully use all three classes. In the out-of-sample backtest, **11 of 12 sectors made zero trades**; several "beat buy-and-hold" only by staying in cash. Manufacturing (3 trades, +14.5% vs +13.4% buy-and-hold) is the only sector with real trading evidence.

Two remediations were attempted and neither resolved it:

- **Data-noise removal** — dropping short-history tickers and unadjusted bonus/rights-share price artifacts, using a NEPSE-rule-aware threshold (10% daily circuit limit before 20 Apr 2026, 15% after). Improved data quality, but moved holdout accuracy by **<1% in every sector**.
- **Percentile-based labeling** — assigning Sell/Hold/Buy by the 30th/70th percentile of each ticker's forward return instead of a fixed ±1% threshold. Fixed the collapse in 4 of 8 sectors but lowered overall accuracy and left the other 4 collapsed, so it was reverted.

Every weekly retrain now reports the **always-Hold baseline** (accuracy and macro-F1) and per-class Buy/Sell recall next to each model, so a model that only matches the baseline is visible at a glance.

**Class weighting in the training loss was tested and not adopted.** Training all 12 sectors with inverse-frequency class weights raised macro-F1 over the deployed models in 9 of 12 sectors (for example Non Life 0.25 to 0.41, Life Insurance 0.28 to 0.36) and produced real Buy/Sell predictions, at the cost of 5–12 points of accuracy. It did not turn into profit, though. In the out-of-sample backtest the class-weighted LSTM sectors made 12 trades and returned about −35 percentage points summed across the 11 LSTM sectors (the deployed models, being in cash, returned 0), and beat buy-and-hold in only 4 of 11 sectors. Results also varied by up to 0.08 macro-F1 between identical runs, so single-window comparisons are noisy. The deployed models and the weekly quality gate are unchanged. The manual **Class-weight experiment** workflow still trains and backtests the class-weighted candidates without changing any deployed model, and the sensible next step is a multi-window walk-forward backtest rather than more tuning on one 65-day window.

## 🤖 Automation (GitHub Actions)

| Workflow | Schedule | What it does |
|---|---|---|
| Refresh news sentiment | daily | Scrapes new headlines, scores them with FinBERT, commits `deploy_data/news` |
| Refresh daily prices | Mon–Fri | Fetches new prices into the full-history snapshot (release `data-latest`) and refreshes `deploy_data/processed` |
| Weekly forecasts and retraining | Saturday | Rebuilds Prophet forecasts; retrains each sector and promotes the new model only if it passes a quality gate |
| Monthly backtest | 1st of month | Re-runs the out-of-sample backtest |
| Class-weight experiment | manual | Compares class-weighted training against the deployed models; deploys nothing |

Render redeploys automatically on every push.

## 📁 Project Structure

```
.
├── app/                      # Flask dashboard
│   ├── routes.py             # Page routes, market movers, caching
│   ├── api.py                # JSON API — live model inference
│   ├── templates/            # Jinja2 pages
│   └── static/               # CSS, Chart.js logic
├── src/
│   ├── scraper/              # NEPSE price & news scrapers
│   ├── features/             # Technical indicators & labeling
│   ├── nlp/                  # FinBERT sentiment pipeline
│   ├── models/               # Sector trainer (LSTM / XGBoost)
│   └── backtesting/          # Strategy simulation & metrics
├── data/                     # Full dataset (gitignored)
│   ├── raw/  processed/  models/  news/
├── deploy_data/              # Trimmed snapshot committed for deployment
├── examples/                 # Runnable pipeline scripts
├── tests/                    # 23 unit tests
├── config/                   # YAML configuration
├── render.yaml               # Render Blueprint (deployment)
└── run.py                    # App entry point
```

## 🌐 Deployment

The dashboard is deployed on **Render** via a Blueprint (`render.yaml`), which builds from `requirements-web.txt` and serves with Gunicorn.

Because the full `data/` directory is gitignored, the app reads from `deploy_data/` in production — a trimmed snapshot (last ~260 rows per ticker plus the out-of-sample models) selected via the `DATA_DIR` environment variable. Regenerate it with `python examples/build_deploy_snapshot.py` after refreshing data or retraining.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full details.

## 🗺 Roadmap

- [ ] Class weighting in the training loss to address majority-class collapse
- [ ] Automated daily data refresh (scheduled scrape → retrain → redeploy)
- [ ] Per-ticker news sentiment (currently market-wide only)
- [ ] Validated price forecasting — Prophet/LSTM forecasting code exists in `src/models/` but has not been validated, so it is **not** wired into the dashboard

## ⚠️ Disclaimer

This project is for **educational and research purposes only** and does not constitute financial advice. As documented above, the current models do not produce reliable trading signals. Past performance does not guarantee future returns. Always consult a licensed financial advisor before making investment decisions.

## 👤 Author

**Roshan Pandey**

[Portfolio](https://roshanpandey-1.github.io) · [GitHub](https://github.com/roshanpandey-1)
