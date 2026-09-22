"""
Sector Backtest Runner
Loads each sector's trained model, generates Buy/Sell/Hold signals on that
sector's most-complete ticker, and runs the Backtester to compare against
Buy-and-Hold. Produces data/models/backtest_summary.csv for the README table.

XGBoost sectors run anywhere pandas/xgboost/sklearn are installed.
LSTM sectors additionally need torch installed (see requirements.txt).

Run: python examples/run_backtests.py
"""
import sys
sys.path.append('.')

import pickle
import numpy as np
import pandas as pd
from src.backtesting.backtester import Backtester

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

SEQ_LEN = 10

if HAS_TORCH:
    class StockLSTM(nn.Module):
        def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.3):
            super().__init__()
            self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim,
                                 num_layers=num_layers, batch_first=True, dropout=dropout)
            self.classifier = nn.Sequential(
                nn.Linear(hidden_dim, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 3)
            )

        def forward(self, x):
            lstm_out, _ = self.lstm(x)
            return self.classifier(lstm_out[:, -1, :])


LSTM_SECTORS = ['Hydro Power', 'Microfinance', 'Commercial Banks', 'Development Banks',
                'Finance', 'Life Insurance', 'Non Life Insurance']
XGB_SECTORS = ['Manufacturing And Processing']

drop_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume',
             'Trades', 'Turnover', 'Ticker', 'Label', 'Future_Return', 'Sector']

with open('data/processed/ticker_list.txt') as f:
    tickers = [t.strip() for t in f if t.strip()]

# Build sector -> ticker map, picking the ticker with the most rows per sector
sector_best_ticker = {}
sector_rows = {}
for t in tickers:
    try:
        df = pd.read_csv(f'data/processed/{t}_features.csv')
    except FileNotFoundError:
        continue
    if not len(df) or 'Sector' not in df.columns:
        continue
    sector = df['Sector'].iloc[0]
    if sector not in sector_rows or len(df) > sector_rows[sector]:
        sector_rows[sector] = len(df)
        sector_best_ticker[sector] = t

results = []
bt = Backtester(initial_capital=100000)

def run_xgb_sector(sector, ticker):
    sector_name = sector.replace(' ', '_').replace('/', '_')
    model_path = f"data/models/{sector_name}_xgb_model.pkl"
    with open(model_path, 'rb') as f:
        model = pickle.load(f)
    df = pd.read_csv(f'data/processed/{ticker}_features.csv', parse_dates=['Date'])
    cutoff = pd.Timestamp.today() - pd.DateOffset(years=2)
    df = df[df['Date'] >= cutoff].reset_index(drop=True)
    feature_cols = [c for c in df.columns if c not in drop_cols]
    df = df.dropna(subset=feature_cols).reset_index(drop=True)
    df['Signal'] = model.predict(df[feature_cols].values)
    res = bt.run(df[['Date', 'Close', 'Signal']])
    res.pop('df', None)
    return res

def run_lstm_sector(sector, ticker):
    sector_name = sector.replace(' ', '_').replace('/', '_')
    model_path = f"data/models/{sector_name}_lstm_model.pth"
    scaler_path = f"data/models/{sector_name}_scaler.pkl"
    df = pd.read_csv(f'data/processed/{ticker}_features.csv', parse_dates=['Date'])
    cutoff = pd.Timestamp.today() - pd.DateOffset(years=2)
    df = df[df['Date'] >= cutoff].reset_index(drop=True)
    feature_cols = [c for c in df.columns if c not in drop_cols]
    df = df.dropna(subset=feature_cols).reset_index(drop=True)

    with open(scaler_path, 'rb') as f:
        scaler = pickle.load(f)
    X_scaled = scaler.transform(df[feature_cols].values)

    model = StockLSTM(input_dim=X_scaled.shape[1])
    model.load_state_dict(torch.load(model_path, map_location='cpu'))
    model.eval()

    signals = [1] * SEQ_LEN  # Hold until we have enough history for a sequence
    with torch.no_grad():
        for i in range(SEQ_LEN, len(X_scaled)):
            seq = torch.FloatTensor(X_scaled[i-SEQ_LEN:i]).unsqueeze(0)
            pred = torch.argmax(model(seq), dim=1).item()
            signals.append(pred)
    df['Signal'] = signals
    res = bt.run(df[['Date', 'Close', 'Signal']])
    res.pop('df', None)
    return res


for sector in XGB_SECTORS:
    if sector not in sector_best_ticker:
        continue
    ticker = sector_best_ticker[sector]
    try:
        res = run_xgb_sector(sector, ticker)
        res.update({'sector': sector, 'model_type': 'XGBoost', 'ticker': ticker})
        results.append(res)
        print(f"{sector} ({ticker}): {res}")
    except Exception as e:
        print(f"{sector}: FAILED - {e}")

if HAS_TORCH:
    for sector in LSTM_SECTORS:
        if sector not in sector_best_ticker:
            continue
        ticker = sector_best_ticker[sector]
        try:
            res = run_lstm_sector(sector, ticker)
            res.update({'sector': sector, 'model_type': 'LSTM', 'ticker': ticker})
            results.append(res)
            print(f"{sector} ({ticker}): {res}")
        except Exception as e:
            print(f"{sector}: FAILED - {e}")
else:
    print("torch not installed - skipping LSTM sectors. Run this script again after "
          "installing torch (see requirements.txt) to backtest the other 7 sectors.")

if results:
    out = pd.DataFrame(results)
    cols = ['sector', 'model_type', 'ticker', 'ml_return_pct', 'bnh_return_pct',
            'sharpe_ratio', 'max_drawdown_pct', 'win_rate_pct', 'num_trades', 'final_value']
    out = out[cols]
    out.to_csv('data/models/backtest_summary.csv', index=False)
    print("\nSaved -> data/models/backtest_summary.csv")
    print(out.to_string(index=False))
