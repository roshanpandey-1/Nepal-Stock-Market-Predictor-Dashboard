
import sys
sys.path.append('.')

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from src.models.classifier import SignalClassifier
from loguru import logger

# ── 1. Load & combine all stock data ────────────────────────
tickers = ['NABIL', 'NICA', 'NTC', 'HBL', 'GBIME',
           'ADBL', 'EBL', 'SCB', 'SBI', 'SANIMA']
dfs = []
for ticker in tickers:
    df = pd.read_csv(f'data/processed/{ticker}_features.csv')
    dfs.append(df)

data = pd.concat(dfs, ignore_index=True)
logger.info(f"Total rows loaded: {len(data)}")

# ── 2. Define features and target ───────────────────────────
drop_cols = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume',
             'Trades', 'Turnover', 'Ticker', 'Label', 'Future_Return']
feature_cols = [c for c in data.columns if c not in drop_cols]

data = data.dropna(subset=feature_cols + ['Label'])
X = data[feature_cols]
y = data['Label']

logger.info(f"Features: {len(feature_cols)}")
logger.info(f"Label distribution: {y.value_counts().to_dict()}")

# ── 3. Train/test split ──────────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
logger.info(f"Train: {len(X_train)} rows | Test: {len(X_test)} rows")

# ── 4. Tune with Optuna ──────────────────────────────────────
logger.info("Tuning with Optuna (30 trials)...")
clf = SignalClassifier(model_type="lightgbm")
best_params = clf.tune(X_train, y_train, n_trials=30)
logger.info(f"Best params: {best_params}")

# ── 5. Train with best params ────────────────────────────────
logger.info("Training with best params...")
clf.train(X_train, y_train, params=best_params)

# ── 6. Evaluate ──────────────────────────────────────────────
logger.info("Evaluating...")
clf.evaluate(X_test, y_test)

# ── 7. Save model ────────────────────────────────────────────
clf.save("data/models/lightgbm_classifier.pkl")
logger.info("Done!")