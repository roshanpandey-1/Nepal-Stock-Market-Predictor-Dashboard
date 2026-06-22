# 🇳🇵 NEPSE Intelligence Platform

> An end-to-end Machine Learning platform for Nepal Stock Exchange (NEPSE) analysis — combining price forecasting, Buy/Sell/Hold signal classification, and financial news sentiment analysis in a single Flask web dashboard.

![Dashboard Preview](app/static/images/dashboard_preview.png)

## 🎯 What it does

| Feature | Description |
|---|---|
| 📈 Price Forecasting | Prophet + LSTM models predict next 7-day stock prices |
| 🟢 Signal Classification | XGBoost/LightGBM classify Buy / Sell / Hold signals |
| 📰 News Sentiment | NLP pipeline scores financial news from Sharesansar & OnlineKhabar |
| 💡 Explainability | SHAP values explain every prediction ("why Buy?") |
| 📊 Backtesting | Simulated trading vs. Buy-and-Hold benchmark |
| 🌐 Web Dashboard | Interactive Flask app with Chart.js visualizations |

## 🛠 Tech Stack

`Python` · `Flask` · `XGBoost` · `LightGBM` · `Prophet` · `TensorFlow/Keras` · `HuggingFace Transformers` · `SHAP` · `Optuna` · `BeautifulSoup` · `Chart.js` · `Bootstrap 5`

## 📁 Project Structure

```
nepse_intelligence/
├── config/                  # YAML configuration files
├── src/
│   ├── scraper/             # NEPSE & news web scrapers
│   ├── features/            # Technical indicators & labeling
│   ├── nlp/                 # Sentiment analysis pipeline
│   ├── models/              # Forecaster & classifier
│   └── backtesting/         # Strategy simulation
├── app/                     # Flask web application
│   ├── templates/           # HTML pages
│   └── static/              # CSS, JS, Chart.js
├── data/
│   ├── raw/                 # Scraped CSV files
│   ├── processed/           # Feature-engineered data
│   └── models/              # Saved model files
├── notebooks/               # EDA & modeling experiments
└── examples/                # Standalone usage scripts
```

## 🚀 Getting Started

```bash
# 1. Clone the repository
git clone https://github.com/roshanpandey-1/nepse-intelligence.git
cd nepse-intelligence

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Fetch stock data
python examples/fetch_stock_data.py

# 5. Run the web app
python run.py
# Open http://localhost:5000
```

## 📊 Model Performance

| Model | Task | Metric | Score |
|---|---|---|---|
| LightGBM | Buy/Sell/Hold | Accuracy | TBD |
| XGBoost | Buy/Sell/Hold | AUC | TBD |
| Prophet | Price Forecast | MAPE | TBD |
| LSTM | Price Forecast | RMSE | TBD |

## ⚠️ Disclaimer

This tool is for **educational purposes only** and does not constitute financial advice. Past model performance does not guarantee future returns. Always consult a licensed financial advisor before making investment decisions.

## 👤 Author

**Roshan Pandey** · [roshanpandey-1.github.io](https://roshanpandey-1.github.io) · [GitHub](https://github.com/roshanpandey-1)
