"""
Weekly sector retraining with a quality gate.

A freshly trained model only replaces the deployed one if it is NOT WORSE on the
same recent data. Retraining on a schedule without this check could silently
swap in a worse model (these models are already weak -- see README).

How the comparison stays fair: the candidate is trained exactly as
ml/models/train_one_sector_v3.py does (last 3 months held out). The deployed
("current") model was trained on an earlier cut-off, so it has never seen the
new holdout window either. Both are scored on that SAME window.

Gate (all must hold, otherwise the current model is kept):
  - at least --min-rows holdout rows (otherwise the result is too noisy to judge)
  - candidate macro-F1  >= current macro-F1  - --tol-f1   (guards against "Hold collapse":
    plain accuracy looks fine when a model predicts Hold for everything)
  - candidate accuracy  >= current accuracy  - --tol-acc

Subcommands:
  plan                              print the sector list as JSON (feeds the CI matrix)
  run --sector S --out-dir DIR      train + evaluate one sector; writes DIR/decision.json
                                    and, if promoted, the new files under DIR/files/
  publish --artifacts DIR           merge promoted files from all `run` outputs into
                                    --target and write retrain_report.csv
"""
import argparse
import csv
import json
import os
import pickle
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, recall_score

sys.path.append('.')
from ml.models.train_one_sector_v3 import (  # noqa: E402
    DROP_COLS, HOLDOUT_MONTHS, SEQ_LEN, load_sector_data,
)

LSTM_SECTORS = ['Hydro Power', 'Microfinance', 'Commercial Banks', 'Development Banks',
                'Finance', 'Life Insurance', 'Non Life Insurance',
                'Hotels And Tourism', 'Investment', 'Others', 'Tradings']
XGB_SECTORS = ['Manufacturing And Processing']

REPORT_COLS = ['run_date', 'sector', 'model_type', 'decision', 'reason',
               'old_accuracy', 'new_accuracy', 'old_macro_f1', 'new_macro_f1',
               'baseline_class', 'baseline_accuracy', 'baseline_macro_f1',
               'old_buy_recall', 'new_buy_recall', 'old_sell_recall', 'new_sell_recall',
               'old_nonhold_share', 'new_nonhold_share',
               'holdout_rows', 'holdout_start']


def stem(sector):
    return sector.replace(' ', '_').replace('/', '_')


def sector_type(sector):
    return 'xgb' if sector in XGB_SECTORS else 'lstm'


def model_files(sector, directory):
    s, d = stem(sector), Path(directory)
    if sector_type(sector) == 'lstm':
        return [d / f'{s}_lstm_model_oos.pth', d / f'{s}_scaler_oos.pkl', d / f'{s}_split_date.txt']
    return [d / f'{s}_xgb_model_oos.pkl', d / f'{s}_split_date.txt']


# ── evaluation ────────────────────────────────────────────────
def holdout_sets(sector):
    """Per-ticker (df, row positions in the holdout window) + feature columns + split date."""
    sector_dfs = load_sector_data(sector)
    max_date = pd.concat([d['Date'] for d in sector_dfs]).max()
    split = max_date - pd.DateOffset(months=HOLDOUT_MONTHS)
    feature_cols = [c for c in sector_dfs[0].columns if c not in DROP_COLS]
    sets = []
    for df in sector_dfs:
        df = df.dropna(subset=feature_cols + ['Label']).reset_index(drop=True)
        df = df[df['Date'] >= split - pd.Timedelta(days=60)].reset_index(drop=True)
        idx = [i for i in range(SEQ_LEN, len(df)) if df['Date'].iloc[i] >= split]
        if idx:
            sets.append((df, idx))
    return sets, feature_cols, split


def predict(sector, directory, sets, feature_cols):
    kind = sector_type(sector)
    files = model_files(sector, directory)
    y_true, y_pred = [], []
    if kind == 'xgb':
        with open(files[0], 'rb') as f:
            model = pickle.load(f)
        for df, idx in sets:
            X = df[feature_cols].values[idx]
            y_pred.extend(model.predict(X).tolist())
            y_true.extend(df['Label'].values[idx].astype(int).tolist())
    else:
        import torch
        import torch.nn as nn

        class StockLSTM(nn.Module):  # same architecture as the trainer / run_backtests_oos
            def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.3):
                super().__init__()
                self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim,
                                    num_layers=num_layers, batch_first=True, dropout=dropout)
                self.classifier = nn.Sequential(
                    nn.Linear(hidden_dim, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 3))

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.classifier(out[:, -1, :])

        with open(files[1], 'rb') as f:
            scaler = pickle.load(f)
        if scaler.n_features_in_ != len(feature_cols):
            raise ValueError(f"model expects {scaler.n_features_in_} features, data has {len(feature_cols)}")
        model = StockLSTM(len(feature_cols))
        model.load_state_dict(torch.load(files[0], map_location='cpu'))
        model.eval()
        for df, idx in sets:
            X = scaler.transform(df[feature_cols].values)
            seqs = np.stack([X[i - SEQ_LEN:i] for i in idx])
            with torch.no_grad():
                y_pred.extend(torch.argmax(model(torch.FloatTensor(seqs)), dim=1).tolist())
            y_true.extend(df['Label'].values[idx].astype(int).tolist())
    return np.array(y_true), np.array(y_pred)


def score(y_true, y_pred):
    rec = recall_score(y_true, y_pred, labels=[0, 1, 2], average=None, zero_division=0)
    return {'accuracy': round(float(accuracy_score(y_true, y_pred)), 4),
            'macro_f1': round(float(f1_score(y_true, y_pred, average='macro', labels=[0, 1, 2],
                                             zero_division=0)), 4),
            # recall per class: 0=Sell, 1=Hold, 2=Buy. Buy/Sell recall of 0 means the
            # model never calls that signal correctly (the "Hold collapse").
            'sell_recall': round(float(rec[0]), 4), 'hold_recall': round(float(rec[1]), 4),
            'buy_recall': round(float(rec[2]), 4),
            # how often the model says anything other than Hold
            'nonhold_share': round(float(np.mean(np.asarray(y_pred) != 1)), 4)}


def baseline(y_true):
    """Score of the dumbest possible model: always predict the most common class.
    A real model has to beat this on macro-F1 to be worth anything."""
    y_true = np.asarray(y_true)
    majority = int(np.bincount(y_true, minlength=3).argmax())
    out = score(y_true, np.full_like(y_true, majority))
    return {'baseline_class': ['Sell', 'Hold', 'Buy'][majority],
            'baseline_accuracy': out['accuracy'], 'baseline_macro_f1': out['macro_f1']}


def gate(old, new, n_rows, min_rows, tol_f1, tol_acc):
    """Return (promote, reason)."""
    if n_rows < min_rows:
        return False, f'only {n_rows} holdout rows (< {min_rows}); too few to judge'
    if old is None:
        return True, 'current model could not be evaluated; candidate adopted'
    if new['macro_f1'] < old['macro_f1'] - tol_f1:
        return False, f"macro-F1 {new['macro_f1']} < current {old['macro_f1']} - {tol_f1}"
    if new['accuracy'] < old['accuracy'] - tol_acc:
        return False, f"accuracy {new['accuracy']} < current {old['accuracy']} - {tol_acc}"
    return True, 'candidate not worse than current on the shared holdout'


# ── subcommands ───────────────────────────────────────────────
def cmd_plan(_):
    plan = [{'sector': s, 'stem': stem(s), 'type': sector_type(s)}
            for s in LSTM_SECTORS + XGB_SECTORS]
    print(json.dumps(plan))


def cmd_run(a):
    sector, kind = a.sector, sector_type(a.sector)
    out = Path(a.out_dir)
    cand_dir = out / 'candidate'
    cand_dir.mkdir(parents=True, exist_ok=True)
    decision = {'sector': sector, 'model_type': kind, 'run_date': date.today().isoformat()}
    try:
        cmd = [sys.executable, 'ml/models/train_one_sector_v3.py', '--sector', sector,
               '--type', kind, '--out-dir', str(cand_dir), '--max-epochs', str(a.max_epochs)]
        if a.class_weight and kind == 'lstm':
            cmd.append('--class-weight')  # weight the loss by inverse class frequency
        subprocess.run(cmd, check=True)

        sets, feature_cols, split = holdout_sets(sector)
        n_rows = sum(len(i) for _, i in sets)
        y_true_new, y_new = predict(sector, cand_dir, sets, feature_cols)
        new = score(y_true_new, y_new)

        old = None
        try:
            y_true_old, y_old = predict(sector, a.current_dir, sets, feature_cols)
            old = score(y_true_old, y_old)
        except Exception as e:  # missing/incompatible current model
            print(f'[{sector}] could not evaluate current model: {e}')

        promote, reason = gate(old, new, n_rows, a.min_rows, a.tol_f1, a.tol_acc)
        decision.update({
            'decision': 'promoted' if promote else 'kept_current', 'reason': reason,
            'old_accuracy': old and old['accuracy'], 'new_accuracy': new['accuracy'],
            'old_macro_f1': old and old['macro_f1'], 'new_macro_f1': new['macro_f1'],
            'old_buy_recall': old and old['buy_recall'], 'new_buy_recall': new['buy_recall'],
            'old_sell_recall': old and old['sell_recall'], 'new_sell_recall': new['sell_recall'],
            'old_nonhold_share': old and old['nonhold_share'], 'new_nonhold_share': new['nonhold_share'],
            'class_weight': bool(a.class_weight and kind == 'lstm'),
            'holdout_rows': n_rows, 'holdout_start': str(split.date()),
            **baseline(y_true_new),
        })
        if promote or a.keep_files:
            dest = out / 'files'
            dest.mkdir(exist_ok=True)
            for f in model_files(sector, cand_dir):
                shutil.copy(f, dest / f.name)
    except Exception as e:  # never let one sector break the weekly run
        decision.update({'decision': 'error', 'reason': f'{type(e).__name__}: {e}'})
    (out / 'decision.json').write_text(json.dumps(decision, indent=2))
    print(json.dumps(decision, indent=2))


def summary_table(rows):
    """Markdown table for the CI job summary: how each model compares with the
    always-predict-the-majority baseline, and whether it ever calls Buy/Sell."""
    out = ['| sector | decision | current F1 | new F1 | always-Hold F1 | new Buy / Sell recall | new non-Hold share | reason |',
           '|---|---|---|---|---|---|---|---|']
    for r in rows:
        out.append(f"| {r['sector']} | {r['decision']} | {r.get('old_macro_f1')} | {r.get('new_macro_f1')} | "
                   f"{r.get('baseline_macro_f1')} | {r.get('new_buy_recall')} / {r.get('new_sell_recall')} | "
                   f"{r.get('new_nonhold_share')} | {r['reason']} |")
    return '\n'.join(out) + '\n'


def load_decisions(artifacts):
    seen = {}
    for dj in sorted(Path(artifacts).rglob('decision.json')):
        d = json.loads(dj.read_text())
        seen[d['sector']] = d
    return [seen.get(s) or {'sector': s, 'decision': 'no_result', 'reason': 'no output'}
            for s in LSTM_SECTORS + XGB_SECTORS]


def cmd_report(a):
    """Print the comparison table for a set of `run` outputs. Writes nothing to the repo --
    used by the class-weight experiment workflow, which must never change deployed models."""
    table = summary_table(load_decisions(a.artifacts))
    print(table)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(table)


def cmd_publish(a):
    target = Path(a.target)
    seen = {}
    for dj in sorted(Path(a.artifacts).rglob('decision.json')):
        d = json.loads(dj.read_text())
        seen[d['sector']] = d
        if d['decision'] == 'promoted':
            for f in (dj.parent / 'files').iterdir():
                shutil.copy(f, target / f.name)
    rows = []
    for s in LSTM_SECTORS + XGB_SECTORS:
        d = seen.get(s) or {'sector': s, 'model_type': sector_type(s),
                            'run_date': date.today().isoformat(),
                            'decision': 'no_result', 'reason': 'training job produced no output'}
        rows.append(d)
    with open(target / 'retrain_report.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=REPORT_COLS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    promoted = [r['sector'] for r in rows if r['decision'] == 'promoted']
    summary = (f"{len(promoted)} of {len(rows)} sector models updated"
               + (f": {', '.join(promoted)}" if promoted else ''))
    print(summary)
    Path(a.summary_file).write_text(summary + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(summary_table(rows))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('plan').set_defaults(fn=cmd_plan)

    r = sub.add_parser('run')
    r.add_argument('--sector', required=True)
    r.add_argument('--out-dir', required=True)
    r.add_argument('--current-dir', default='deploy_data/models')
    r.add_argument('--max-epochs', type=int, default=200)
    r.add_argument('--min-rows', type=int, default=100)
    r.add_argument('--tol-f1', type=float, default=0.01)
    r.add_argument('--tol-acc', type=float, default=0.02)
    r.add_argument('--class-weight', action='store_true',
                   help='train LSTMs with inverse-frequency class weights (experiment; ignored for XGBoost)')
    r.add_argument('--keep-files', action='store_true',
                   help='save the candidate model files even when not promoted (for backtesting an experiment)')
    r.set_defaults(fn=cmd_run)

    rp = sub.add_parser('report')
    rp.add_argument('--artifacts', required=True)
    rp.set_defaults(fn=cmd_report)

    p = sub.add_parser('publish')
    p.add_argument('--artifacts', required=True)
    p.add_argument('--target', default='deploy_data/models')
    p.add_argument('--summary-file', default='retrain_summary.txt')
    p.set_defaults(fn=cmd_publish)

    args = ap.parse_args()
    args.fn(args)
