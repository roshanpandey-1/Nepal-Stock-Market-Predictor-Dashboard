"""
Phase B: walk-forward test of the sector models over six past quarters.

Phase A (evaluate_signals_oos.py) scored the deployed models on one holdout
window (Jun/Jul to Oct 2026) and found a small ranking signal (pooled IC +0.036)
that did not survive trading costs. Phase B asks whether that signal is stable:
for each quarter below, every sector model is retrained on ONLY the two years
before the quarter -- same recipe as the weekly retrain (train_one_sector_v3.py:
2-year window, LSTM for 11 sectors / XGBoost for Manufacturing, max 200 epochs) --
and then scored on that quarter with exactly the Phase A code and costs.

Quarters (all end before Phase A's window starts, so A and B never overlap):
  2024Q4 2025Q1 2025Q2 2025Q3 2025Q4 2026Q1

Decision rules (fixed on 2026-10-24, before the first run). Phase B counts as
better than Phase A only if ALL hold across the six quarters:
  B1  pooled IC > 0 with a 95% block-bootstrap CI excluding 0
  B2  pooled IC positive in at least 4 of the 6 quarters
  B3  after costs, S1 (deployed rule), S2-weekly or S2-monthly (top 20% of the sector,
      rebalanced every 5 or 20 trading days) has pooled daily excess return over its
      benchmark with a 95% CI entirely above 0
Otherwise Phase A's conclusion stands.

Run from the repo root (each step is resumable; finished quarters/sectors are skipped):
  python scripts/walkforward_signals.py train  [--windows 2025Q1 ...] [--sectors ...]
  python scripts/walkforward_signals.py score
  python scripts/walkforward_signals.py report
Models and results go to data/models/walkforward/ (gitignored).
"""
import argparse
import json
import pickle
import random
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append('.')
warnings.filterwarnings("ignore")

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("evaluate_signals_oos", Path(__file__).with_name("evaluate_signals_oos.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

WINDOWS = {  # name: (first test day, first day after the quarter)
    '2024Q4': ('2024-10-01', '2025-01-01'),
    '2025Q1': ('2025-01-01', '2025-04-01'),
    '2025Q2': ('2025-04-01', '2025-07-01'),
    '2025Q3': ('2025-07-01', '2025-10-01'),
    '2025Q4': ('2025-10-01', '2026-01-01'),
    '2026Q1': ('2026-01-01', '2026-04-01'),
}
TRAIN_YEARS = 2
MAX_EPOCHS = 200          # same cap the weekly retrain uses
SEED = 0
DATA_DIR = Path('data')   # full local history (deploy_data is trimmed to ~1 year)
OUT = Path('data/models/walkforward')


def _name(sector):
    return sector.replace(' ', '_').replace('/', '_')


def train_one(sector, window):
    """Train one sector model on the 2 years before the quarter starts."""
    from ml.models import train_one_sector_v3 as tr
    import torch
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    random.seed(SEED)
    torch.set_num_threads(2)

    start = pd.Timestamp(WINDOWS[window][0])
    cutoff = start - pd.DateOffset(years=TRAIN_YEARS)
    mdir = OUT / window / 'models'
    mdir.mkdir(parents=True, exist_ok=True)
    kind = 'xgb' if sector in ev.XGB_SECTORS else 'lstm'

    feature_cols, frames = None, []
    for df in tr.load_sector_data(sector):
        df = df[df['Date'] >= cutoff].reset_index(drop=True)
        if feature_cols is None:
            feature_cols = [c for c in df.columns if c not in tr.DROP_COLS]
        df = df.dropna(subset=feature_cols + ['Label']).reset_index(drop=True)
        df = df[df['Date'] < start].reset_index(drop=True)          # nothing from the test quarter
        df = df.iloc[:-1]   # the last pre-quarter label uses the quarter's first close, so drop it
        if len(df) > tr.SEQ_LEN:
            frames.append(df)
    if not frames:
        return {'sector': sector, 'window': window, 'status': 'no training data'}
    rows = sum(len(d) for d in frames)

    t0 = time.time()
    if kind == 'lstm':
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler().fit(pd.concat(frames)[feature_cols].values)
        xs, ys = [], []
        for df in frames:
            x, y = tr.create_sequences(scaler.transform(df[feature_cols].values), df['Label'].values, tr.SEQ_LEN)
            if len(x):
                xs.append(x)
                ys.append(y)
        X, y = np.concatenate(xs), np.concatenate(ys)
        model, acc, _, _ = tr.train_lstm(X, y, X.shape[2], max_epochs=MAX_EPOCHS)
        torch.save(model.state_dict(), mdir / f'{_name(sector)}_lstm_model_oos.pth')
        with open(mdir / f'{_name(sector)}_scaler_oos.pkl', 'wb') as f:
            pickle.dump(scaler, f)
        n_train = len(X)
    else:
        pooled = pd.concat(frames, ignore_index=True)
        model, acc, _, _ = tr.train_xgb(pooled[feature_cols].values, pooled['Label'].values)
        with open(mdir / f'{_name(sector)}_xgb_model_oos.pkl', 'wb') as f:
            pickle.dump(model, f)
        n_train = len(pooled)
    (mdir / f'{_name(sector)}_split_date.txt').write_text(str(start.date()))
    return {'sector': sector, 'window': window, 'status': 'ok', 'model': kind, 'train_rows': rows,
            'train_samples': n_train, 'val_acc': round(float(acc), 4), 'seconds': round(time.time() - t0, 1)}


def cmd_train(windows, sectors):
    log = OUT / 'train_log.jsonl'
    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if log.exists():
        for line in log.read_text().splitlines():
            r = json.loads(line)
            if r.get('status') == 'ok':
                done.add((r['window'], r['sector']))
    for w in windows:
        for s in sectors:
            if (w, s) in done:
                continue
            try:
                r = train_one(s, w)
            except Exception as e:  # keep going; the report lists what is missing
                r = {'sector': s, 'window': w, 'status': f'error: {e}'}
            with open(log, 'a') as f:
                f.write(json.dumps(r) + '\n')
            print(json.dumps(r), flush=True)


def cmd_score(windows, sectors):
    for s in sectors:
        frames = ev._sector_frames(DATA_DIR, s)
        for w in windows:
            out = OUT / w / f'preds_{_name(s)}.csv'
            mdir = OUT / w / 'models'
            if out.exists() or not (mdir / f'{_name(s)}_split_date.txt').exists():
                continue
            df = ev.predict_sector(DATA_DIR, s, model_dir=mdir, end=WINDOWS[w][1], frames=frames)
            df['window'] = w
            df.to_csv(out, index=False)
            print(f"{w} {s}: {len(df)} predictions, {df['ticker'].nunique() if len(df) else 0} tickers", flush=True)


def _pooled(by):
    by = {k: v for k, v in by.items() if len(v)}
    return pd.concat(by, axis=1).mean(axis=1).dropna() if by else pd.Series(dtype=float)


def _evaluate(P):
    """Phase A's statistics on a set of predictions (one quarter, or all of them)."""
    ic_by, s1_by, s2w_by, s2m_by, rows = {}, {}, {}, {}, []
    for sector, g in P.groupby('sector'):
        wk = ev._sector_report(g, rebal_every=5)
        mo = ev._sector_report(g, rebal_every=20)
        ic_by[sector], s1_by[sector] = wk['ic'], wk['s1_ex']
        s2w_by[sector], s2m_by[sector] = wk['s2_ex'], mo['s2_ex']
        rows.append({'sector': sector, **wk['row'], 's2_monthly_excess_daily_bp':
                     round(1e4 * mo['s2_ex'].mean(), 2) if len(mo['s2_ex']) else None})
    res = {}
    for key, by in (('ic', ic_by), ('s1', s1_by), ('s2w', s2w_by), ('s2m', s2m_by)):
        series = _pooled(by)
        m, lo, hi, n = ev.boot_ci(series)
        scale = 1 if key == 'ic' else 1e4
        res[key] = {'mean': round(scale * m, 4), 'ci95': [round(scale * lo, 4), round(scale * hi, 4)], 'days': n}
    return res, pd.DataFrame(rows)


def cmd_report():
    parts = [pd.read_csv(f, parse_dates=['label_date', 'decision_date', 'trade_date'])
             for f in sorted(OUT.glob('*/preds_*.csv'))]
    if not parts:
        sys.exit('no predictions -- run train and score first')
    P = pd.concat(parts, ignore_index=True)
    # Within one quarter dates are unique, so the pooled series are built per quarter
    # and then joined (quarters never overlap).
    per_window, tables = {}, []
    for w, g in P.groupby('window'):
        res, table = _evaluate(g)
        per_window[w] = res
        table.insert(0, 'window', w)
        tables.append(table)
    overall, _ = _evaluate(P)
    b1 = overall['ic']['mean'] > 0 and overall['ic']['ci95'][0] > 0
    pos_q = sum(1 for r in per_window.values() if r['ic']['mean'] > 0)
    b2 = pos_q >= 4
    b3 = any(overall[k]['ci95'][0] > 0 for k in ('s1', 's2w', 's2m'))
    summary = {
        'windows': sorted(per_window), 'predictions': int(len(P)), 'tickers': int(P['ticker'].nunique()),
        'overall': overall, 'per_window': per_window,
        'B1_pooled_ic_significant': bool(b1), 'B2_quarters_with_positive_ic': f'{pos_q} of {len(per_window)}',
        'B2_pass': bool(b2), 'B3_tradable_after_costs': bool(b3),
        'PHASE_B_BETTER_THAN_A': bool(b1 and b2 and b3),
    }
    pd.concat(tables).to_csv(OUT / 'sector_by_window.csv', index=False)
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['train', 'score', 'report'])
    ap.add_argument('--windows', nargs='*', default=list(WINDOWS))
    ap.add_argument('--sectors', nargs='*', default=ev.ALL_SECTORS)
    a = ap.parse_args()
    if a.step == 'train':
        cmd_train(a.windows, a.sectors)
    elif a.step == 'score':
        cmd_score(a.windows, a.sectors)
    else:
        cmd_report()


if __name__ == '__main__':
    main()
