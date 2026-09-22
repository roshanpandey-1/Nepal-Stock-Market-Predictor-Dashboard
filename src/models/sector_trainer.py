"""
Sector-wise Model Trainer using LSTM + XGBoost
Trains one LSTM model per NEPSE sector (XGBoost for Manufacturing)
Run: python src/models/sector_trainer.py
"""
import sys
sys.path.append('.')

import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
from xgboost import XGBClassifier
import pickle
from loguru import logger

# ── LSTM Architecture ─────────────────────────────────────────
class StockLSTM(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.3):
        super(StockLSTM, self).__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout
        )
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 3)
        )

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        return self.classifier(lstm_out[:, -1, :])


# ── Helper functions ──────────────────────────────────────────
SEQ_LEN = 10

def create_sequences(X, y, seq_len):
    Xs, ys = [], []
    for i in range(len(X) - seq_len):
        Xs.append(X[i:i+seq_len])
        ys.append(y[i+seq_len])
    return np.array(Xs), np.array(ys)


def train_lstm(X_seq, y_seq, input_dim):
    X_train, X_test, y_train, y_test = train_test_split(
        X_seq, y_seq, test_size=0.2, random_state=42, stratify=y_seq
    )

    X_train_t = torch.FloatTensor(X_train)
    y_train_t = torch.LongTensor(y_train)
    X_test_t  = torch.FloatTensor(X_test)

    train_dl = DataLoader(
        TensorDataset(X_train_t, y_train_t),
        batch_size=128, shuffle=True
    )

    model = StockLSTM(input_dim=input_dim)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=100)

    patience = 30
    best_acc = 0
    best_weights = None
    no_improve = 0

    for epoch in range(1000):
        model.train()
        for X_batch, y_batch in train_dl:
            optimizer.zero_grad()
            loss = criterion(model(X_batch), y_batch)
            loss.backward()
            optimizer.step()
        scheduler.step()

        model.eval()
        with torch.no_grad():
            _, predicted = torch.max(model(X_test_t), 1)
            acc = accuracy_score(y_test, predicted.numpy())

        if acc > best_acc:
            best_acc = acc
            best_weights = {k: v.clone() for k, v in model.state_dict().items()}
            no_improve = 0
        else:
            no_improve += 1

        if no_improve >= patience:
            logger.info(f"Early stopping at epoch {epoch+1}")
            break

    model.load_state_dict(best_weights)
    model.eval()
    with torch.no_grad():
        _, predicted = torch.max(model(X_test_t), 1)
        preds = predicted.numpy()

    return model, best_acc, preds, y_test


def train_xgb(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    xgb = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric='mlogloss',
        verbosity=0
    )
    xgb.fit(X_train, y_train)
    preds = xgb.predict(X_test)
    acc = accuracy_score(y_test, preds)
    return xgb, acc, preds, y_test


# ── 1. Load ticker list ──────────────────────────────────────
with open('data/processed/ticker_list.txt', 'r') as f:
    tickers = [line.strip() for line in f.readlines()]
logger.info(f"Loaded {len(tickers)} tickers")

# ── 2. Load all data ─────────────────────────────────────────
dfs = []
for ticker in tickers:
    try:
        df = pd.read_csv(f'data/processed/{ticker}_features.csv')
        dfs.append(df)
    except FileNotFoundError:
        logger.warning(f"{ticker}: file not found, skipping")

data = pd.concat(dfs, ignore_index=True)
logger.info(f"Total rows loaded: {len(data)}")

# ── 3. Use only last 2 years of data ─────────────────────────
data['Date'] = pd.to_datetime(data['Date'])
cutoff = pd.Timestamp.today() - pd.DateOffset(years=2)
data = data[data['Date'] >= cutoff]
logger.info(f"After 2-year filter: {len(data)} rows")

# ── 4. Define feature columns ────────────────────────────────
drop_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume',
             'Trades', 'Turnover', 'Ticker', 'Label', 'Future_Return', 'Sector']
feature_cols = [c for c in data.columns if c not in drop_cols]

# ── 5. Define sectors ────────────────────────────────────────
lstm_sectors = [
    'Hydro Power',
    'Microfinance',
    'Commercial Banks',
    'Development Banks',
    'Finance',
    'Life Insurance',
    'Non Life Insurance',
]

xgb_sectors = [
    'Manufacturing And Processing',
]

# ── 6. Train models ──────────────────────────────────────────
results = {}
scaler = StandardScaler()

# Train LSTM sectors
for sector in lstm_sectors:
    logger.info(f"\n{'='*50}")
    logger.info(f"Training LSTM: {sector}")

    sector_data = data[data['Sector'] == sector].copy()
    sector_data = sector_data.dropna(subset=feature_cols + ['Label'])

    n_stocks = sector_data['Ticker'].nunique()
    n_rows = len(sector_data)
    logger.info(f"Stocks: {n_stocks} | Rows: {n_rows}")

    if n_rows < 500:
        logger.warning(f"Skipping {sector} — not enough data")
        continue

    X = sector_data[feature_cols].values
    y = sector_data['Label'].values

    X_scaled = scaler.fit_transform(X)
    X_seq, y_seq = create_sequences(X_scaled, y, SEQ_LEN)

    model, acc, preds, y_test = train_lstm(X_seq, y_seq, X_seq.shape[2])

    logger.info(f"\n{sector} Results:")
    print(classification_report(y_test, preds, target_names=['Sell', 'Hold', 'Buy']))

    sector_name = sector.replace(' ', '_').replace('/', '_')
    model_path = f"data/models/{sector_name}_lstm_model.pth"
    scaler_path = f"data/models/{sector_name}_scaler.pkl"

    torch.save(model.state_dict(), model_path)
    with open(scaler_path, 'wb') as f:
        pickle.dump(scaler, f)

    results[sector] = {
        'model_type': 'LSTM',
        'accuracy': round(acc, 4),
        'stocks': n_stocks,
        'rows': n_rows,
        'model_path': model_path
    }

# Train XGBoost sectors
for sector in xgb_sectors:
    logger.info(f"\n{'='*50}")
    logger.info(f"Training XGBoost: {sector}")

    sector_data = data[data['Sector'] == sector].copy()
    sector_data = sector_data.dropna(subset=feature_cols + ['Label'])

    n_stocks = sector_data['Ticker'].nunique()
    n_rows = len(sector_data)
    logger.info(f"Stocks: {n_stocks} | Rows: {n_rows}")

    if n_rows < 500:
        logger.warning(f"Skipping {sector} — not enough data")
        continue

    X = sector_data[feature_cols].values
    y = sector_data['Label'].values

    model, acc, preds, y_test = train_xgb(X, y)

    logger.info(f"\n{sector} Results:")
    print(classification_report(y_test, preds, target_names=['Sell', 'Hold', 'Buy']))

    sector_name = sector.replace(' ', '_').replace('/', '_')
    model_path = f"data/models/{sector_name}_xgb_model.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)

    results[sector] = {
        'model_type': 'XGBoost',
        'accuracy': round(acc, 4),
        'stocks': n_stocks,
        'rows': n_rows,
        'model_path': model_path
    }

# ── 7. Summary ────────────────────────────────────────────────
logger.info("\n" + "="*60)
logger.info("FINAL SECTOR MODEL SUMMARY")
logger.info("="*60)
for sector, res in results.items():
    logger.info(f"{sector:35} | {res['model_type']:10} | Acc: {res['accuracy']*100:.1f}% | Stocks: {res['stocks']}")