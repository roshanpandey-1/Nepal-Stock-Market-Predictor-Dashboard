"""
Reconstructed v3 sector trainer -- chronological (out-of-sample) holdout version.

The original train_one_sector_v3.py / train_manufacturing_v3.py that produced the
project's deployed *_oos models are missing from the repo (only the consumer,
examples/run_backtests_oos.py, and the resulting model files survived). This
script is rebuilt to match exactly what run_backtests_oos.py expects to load:

  data/models/<Sector>_lstm_model_oos.pth   (or _xgb_model_oos.pkl)
  data/models/<Sector>_scaler_oos.pkl       (LSTM only)
  data/models/<Sector>_split_date.txt       (holdout start date)

Differences from the plain src/models/sector_trainer.py in this repo:
  - Holdout is CHRONOLOGICAL (last 3 months by date), not a random split.
  - Sequences for the LSTM are built PER TICKER before being pooled, so a
    sequence never spans the boundary between two different tickers'
    histories (sector_trainer.py concatenates tickers before sequencing,
    which can leak across tickers -- avoided here on purpose).
  - Only rows strictly BEFORE the holdout start are used for training/fitting
    the scaler, so nothing from the holdout window leaks into training.

This does NOT touch any existing sector's files -- it only ever writes to
paths named after the --sector argument.

Run:
    python train_one_sector_v3.py --sector "Hotels And Tourism" --type lstm
    python train_one_sector_v3.py --sector "Tradings" --type lstm
"""
import argparse
import pickle
import sys

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

sys.path.append('.')

SEQ_LEN = 10
DROP_COLS = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume',
             'Trades', 'Turnover', 'Ticker', 'Label', 'Future_Return', 'Sector']
HOLDOUT_MONTHS = 3
TRAIN_YEARS = 2


def load_sector_data(sector_name):
    with open('data/processed/ticker_list.txt') as f:
        tickers = [t.strip() for t in f if t.strip()]
    dfs = []
    for t in tickers:
        try:
            df = pd.read_csv(f'data/processed/{t}_features.csv', parse_dates=['Date'])
        except FileNotFoundError:
            continue
        if df.empty or 'Sector' not in df.columns:
            continue
        if df['Sector'].iloc[0] != sector_name:
            continue
        df = df.sort_values('Date').reset_index(drop=True)
        dfs.append(df)
    if not dfs:
        raise ValueError(f"No processed data found for sector {sector_name!r}")
    return dfs  # list of per-ticker dataframes, already sorted by Date


def create_sequences(X, y, seq_len):
    Xs, ys = [], []
    for i in range(len(X) - seq_len):
        Xs.append(X[i:i + seq_len])
        ys.append(y[i + seq_len])
    return np.array(Xs), np.array(ys)


def train_lstm(X_seq, y_seq, input_dim, class_weights=None, max_epochs=1000, patience=30):
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset

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

    X_train, X_test, y_train, y_test = train_test_split(
        X_seq, y_seq, test_size=0.2, random_state=42, stratify=y_seq
    )
    X_train_t = torch.FloatTensor(X_train)
    y_train_t = torch.LongTensor(y_train)
    X_test_t = torch.FloatTensor(X_test)

    train_dl = DataLoader(TensorDataset(X_train_t, y_train_t), batch_size=128, shuffle=True)

    model = StockLSTM(input_dim=input_dim)
    if class_weights is not None:
        criterion = nn.CrossEntropyLoss(weight=torch.FloatTensor(class_weights))
    else:
        criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=100)

    best_acc = 0
    best_weights = None
    no_improve = 0

    for epoch in range(max_epochs):
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
            logger.info(f"Early stopping at epoch {epoch + 1}")
            break

    model.load_state_dict(best_weights)
    model.eval()
    with torch.no_grad():
        _, predicted = torch.max(model(X_test_t), 1)
        preds = predicted.numpy()

    return model, best_acc, preds, y_test


def train_xgb(X, y):
    from xgboost import XGBClassifier
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    xgb = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, random_state=42,
        eval_metric='mlogloss', verbosity=0,
    )
    xgb.fit(X_train, y_train)
    preds = xgb.predict(X_test)
    acc = accuracy_score(y_test, preds)
    return xgb, acc, preds, y_test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sector', required=True)
    ap.add_argument('--type', choices=['lstm', 'xgb'], required=True)
    ap.add_argument('--out-dir', default='data/models')
    ap.add_argument('--class-weight', action='store_true',
                     help='Weight the training loss by inverse class frequency '
                          '(README roadmap item: addresses majority-class / Hold collapse).')
    ap.add_argument('--suffix', default='',
                     help='Extra suffix on output filenames, e.g. "_cw", so a '
                          'class-weighted run does not overwrite the unweighted one.')
    ap.add_argument('--max-epochs', type=int, default=1000,
                     help='Hard cap on LSTM training epochs, independent of early '
                          'stopping -- useful to bound wall-clock time on a big sector '
                          '(e.g. Hydro Power) in a resource-constrained environment.')
    args = ap.parse_args()

    sector_dfs = load_sector_data(args.sector)
    n_stocks = len(sector_dfs)
    all_dates = pd.concat([d['Date'] for d in sector_dfs])
    max_date = all_dates.max()
    cutoff_2y = max_date - pd.DateOffset(years=TRAIN_YEARS)
    split_date = max_date - pd.DateOffset(months=HOLDOUT_MONTHS)

    feature_cols = None
    train_frames = []
    for df in sector_dfs:
        df = df[df['Date'] >= cutoff_2y].reset_index(drop=True)
        if feature_cols is None:
            feature_cols = [c for c in df.columns if c not in DROP_COLS]
        df = df.dropna(subset=feature_cols + ['Label']).reset_index(drop=True)
        train_df = df[df['Date'] < split_date].reset_index(drop=True)
        if len(train_df) > SEQ_LEN:
            train_frames.append(train_df)

    total_rows = sum(len(d) for d in train_frames)
    logger.info(f"Sector: {args.sector} | tickers: {n_stocks} | "
                f"train rows (pre-holdout): {total_rows} | split_date: {split_date.date()}")

    if total_rows < 500:
        logger.warning(f"Only {total_rows} training rows for {args.sector} -- proceeding, "
                        f"but treat results with caution (below the 500-row bar used "
                        f"for the other sectors).")

    sector_name = args.sector.replace(' ', '_').replace('/', '_')

    if args.type == 'lstm':
        scaler = StandardScaler()
        # Fit scaler on ALL pre-holdout rows pooled across tickers.
        pooled = pd.concat(train_frames, ignore_index=True)
        scaler.fit(pooled[feature_cols].values)

        # Build sequences PER TICKER so none span a ticker boundary.
        X_seq_list, y_seq_list = [], []
        for df in train_frames:
            X = scaler.transform(df[feature_cols].values)
            y = df['Label'].values
            X_seq, y_seq = create_sequences(X, y, SEQ_LEN)
            if len(X_seq):
                X_seq_list.append(X_seq)
                y_seq_list.append(y_seq)
        X_seq = np.concatenate(X_seq_list, axis=0)
        y_seq = np.concatenate(y_seq_list, axis=0)
        logger.info(f"Training sequences: {X_seq.shape}")

        class_weights = None
        if args.class_weight:
            classes, counts = np.unique(y_seq, return_counts=True)
            # Inverse frequency, normalised so weights average to 1.
            inv = counts.sum() / (len(classes) * counts)
            class_weights = np.ones(3, dtype=np.float32)  # Sell=0, Hold=1, Buy=2
            for cls, w in zip(classes, inv):
                class_weights[int(cls)] = w
            logger.info(f"Class weights (Sell/Hold/Buy): {class_weights.round(3).tolist()} "
                        f"from counts {dict(zip(classes.tolist(), counts.tolist()))}")

        import torch
        model, acc, preds, y_test = train_lstm(X_seq, y_seq, X_seq.shape[2], class_weights=class_weights, max_epochs=args.max_epochs)
        print(classification_report(y_test, preds, target_names=['Sell', 'Hold', 'Buy']))

        model_path = f"{args.out_dir}/{sector_name}_lstm_model_oos{args.suffix}.pth"
        scaler_path = f"{args.out_dir}/{sector_name}_scaler_oos{args.suffix}.pkl"
        split_path = f"{args.out_dir}/{sector_name}_split_date{args.suffix}.txt"
        torch.save(model.state_dict(), model_path)
        with open(scaler_path, 'wb') as f:
            pickle.dump(scaler, f)
        with open(split_path, 'w') as f:
            f.write(str(split_date.date()))
        logger.info(f"Saved {model_path}, {scaler_path}, {split_path}")
        logger.info(f"Internal validation accuracy (random split, early-stop only): {acc:.4f}")

    else:  # xgb
        pooled = pd.concat(train_frames, ignore_index=True)
        X = pooled[feature_cols].values
        y = pooled['Label'].values
        model, acc, preds, y_test = train_xgb(X, y)
        print(classification_report(y_test, preds, target_names=['Sell', 'Hold', 'Buy']))

        model_path = f"{args.out_dir}/{sector_name}_xgb_model_oos.pkl"
        split_path = f"{args.out_dir}/{sector_name}_split_date.txt"
        with open(model_path, 'wb') as f:
            pickle.dump(model, f)
        with open(split_path, 'w') as f:
            f.write(str(split_date.date()))
        logger.info(f"Saved {model_path}, {split_path}")
        logger.info(f"Internal validation accuracy (random split, early-stop only): {acc:.4f}")


if __name__ == '__main__':
    main()
