"""
Phase A signal evaluation: do the deployed sector models carry information?

The monthly backtest (run_backtests_oos.py) looks at one ticker per sector, so
its numbers rest on 12 stocks and a handful of trades. This script scores
EVERY ticker in each sector on that sector model's own out-of-sample window
(dates on or after <Sector>_split_date.txt) and asks two questions:

1. Information: do the model's probabilities rank tomorrow's returns at all?
2. Tradability: after NEPSE trading costs, does acting on them beat a benchmark?

Pass criteria (fixed on 2026-10-24, before the first run):
  P1 information  -- pooled mean daily cross-sectional rank IC (score = P(Buy) - P(Sell)
                     against the model's own next-day target return; each sector weighted
                     equally) is > 0 and its 95% block-bootstrap CI excludes 0.
  P2 tradability  -- after costs, at least one strategy's pooled daily excess return over
                     its benchmark has a 95% block-bootstrap CI entirely above 0:
                       S1  deployed rule on every ticker (Buy -> long, Sell -> flat,
                           Hold -> keep position) vs buying and holding that ticker
                       S2  every 5 trading days hold the top 20% of the sector by score,
                           vs holding the sector's equal-weight basket
  Phase A passes only if P1 and P2 both pass.

Timing (no look-ahead):
  * The information test uses each model's own target: the return from close t to
    close t+1 for the row it was trained to label (LSTM: features up to t-1;
    XGBoost: features up to t).
  * The strategies are stricter: a decision made with information up to close k is
    traded at the NEXT close (k+1) and earns the return from k+1 to k+2.

Costs (100,000-rupee positions, checked 2026-10-24 against published broker schedules):
  brokerage 0.33% + SEBON 0.015% per side, Rs 25 DP charge per sale, and 10% tax on
  short-term capital gains (S1 and its benchmark; S2 is charged fees on turnover only,
  which can only flatter S2).

Run (each step fits in a short shell session):
  python scripts/evaluate_signals_oos.py predict --sectors "Hydro Power"
  python scripts/evaluate_signals_oos.py predict                 # all sectors
  python scripts/evaluate_signals_oos.py report
Outputs go to data/models/signal_eval/ (gitignored).
"""
import argparse
import json
import math
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append('.')
warnings.filterwarnings("ignore")

SEQ_LEN = 10
DROP_COLS = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume',
             'Trades', 'Turnover', 'Ticker', 'Label', 'Future_Return', 'Sector']
LSTM_SECTORS = ['Hydro Power', 'Microfinance', 'Commercial Banks', 'Development Banks',
                'Finance', 'Life Insurance', 'Non Life Insurance',
                'Hotels And Tourism', 'Investment', 'Others', 'Tradings']
XGB_SECTORS = ['Manufacturing And Processing']
ALL_SECTORS = XGB_SECTORS + LSTM_SECTORS

BROKER, SEBON = 0.0033, 0.00015
SIDE = BROKER + SEBON            # cost of one buy or one sell, as a share of the trade
DP_SELL = 25 / 100_000           # Rs 25 per sale on a 100,000-rupee position
CGT = 0.10                       # short-term capital gains tax (held 365 days or less)

BOOT_B, BOOT_BLOCK, SEED = 2000, 5, 7
REBAL_EVERY, TOP_FRAC, MIN_TICKERS = 5, 0.2, 5


# ----------------------------------------------------------------------------- statistics
def boot_ci(x, b=BOOT_B, block=BOOT_BLOCK, seed=SEED):
    """Mean and 95% moving-block bootstrap CI of a daily series (keeps autocorrelation)."""
    x = np.asarray(pd.Series(x, dtype=float).dropna(), dtype=float)
    n = len(x)
    if n < 2 * block:
        return (float(x.mean()) if n else float('nan'), float('nan'), float('nan'), n)
    rng = np.random.default_rng(seed)
    nb = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(b, nb))
    idx = (starts[:, :, None] + np.arange(block)).reshape(b, -1)[:, :n]
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(x.mean()), float(lo), float(hi), n


def rank_ic(scores, rets):
    s = pd.Series(scores, dtype=float)
    r = pd.Series(rets, dtype=float)
    ok = s.notna() & r.notna()
    s, r = s[ok], r[ok]
    if len(s) < MIN_TICKERS or s.nunique() < 2 or r.nunique() < 2:
        return float('nan')
    return float(s.rank().corr(r.rank()))


# ----------------------------------------------------------------------------- strategies
def simulate_rule(signals, rets, with_tax=True):
    """Deployed rule on one ticker: Buy -> long, Sell -> flat, Hold -> keep.

    signals[i] is decided before interval i; rets[i] is that interval's return.
    Returns (daily net returns, number of entries). Costs are charged on the day of
    the trade; tax on a profitable round trip is charged when it is sold. An open
    position is sold on the last day so every strategy ends in cash.
    """
    equity, pos, entry, trades, daily = 1.0, 0, 1.0, 0, []
    n = len(rets)
    for i in range(n):
        start = equity
        sig = signals[i]
        target = 1 if sig == 2 else (0 if sig == 0 else pos)
        if target != pos:
            if target == 1:
                equity *= 1 - SIDE
                entry, trades = equity, trades + 1
            else:
                gain = equity - entry
                equity *= 1 - SIDE - DP_SELL
                if with_tax and gain > 0:
                    equity -= CGT * gain
            pos = target
        equity *= 1 + pos * rets[i]
        if i == n - 1 and pos == 1:
            gain = equity - entry
            equity *= 1 - SIDE - DP_SELL
            if with_tax and gain > 0:
                equity -= CGT * gain
        daily.append(equity / start - 1)
    return daily, trades


def buy_and_hold(rets, with_tax=True):
    return simulate_rule([2] + [1] * (len(rets) - 1), rets, with_tax)[0]


# ----------------------------------------------------------------------------- prediction
def _sector_frames(data_dir, sector):
    frames = {}
    for f in sorted((data_dir / 'processed').glob('*_features.csv')):
        df = pd.read_csv(f, parse_dates=['Date'])
        if df.empty or 'Sector' not in df.columns or df['Sector'].iloc[0] != sector:
            continue
        frames[f.name[:-len('_features.csv')]] = df.sort_values('Date').reset_index(drop=True)
    return frames


def _load_model(data_dir, sector, n_features, model_dir=None):
    name = sector.replace(' ', '_').replace('/', '_')
    mdir = Path(model_dir) if model_dir else data_dir / 'models'
    split = pd.Timestamp((mdir / f'{name}_split_date.txt').read_text().strip())
    if sector in XGB_SECTORS:
        with open(mdir / f'{name}_xgb_model_oos.pkl', 'rb') as f:
            model = pickle.load(f)
        return 'xgb', model, None, split
    import torch
    import torch.nn as nn

    class StockLSTM(nn.Module):
        def __init__(self, input_dim, hidden_dim=128, num_layers=2, dropout=0.3):
            super().__init__()
            self.lstm = nn.LSTM(input_size=input_dim, hidden_size=hidden_dim,
                                num_layers=num_layers, batch_first=True, dropout=dropout)
            self.classifier = nn.Sequential(nn.Linear(hidden_dim, 64), nn.ReLU(),
                                            nn.Dropout(0.2), nn.Linear(64, 3))

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.classifier(out[:, -1, :])

    model = StockLSTM(n_features)
    model.load_state_dict(torch.load(mdir / f'{name}_lstm_model_oos.pth', map_location='cpu'))
    model.eval()
    with open(mdir / f'{name}_scaler_oos.pkl', 'rb') as f:
        scaler = pickle.load(f)
    return 'lstm', model, scaler, split


def predict_sector(data_dir, sector, model_dir=None, end=None, frames=None):
    """Score every ticker from the model's split date (and before `end`, if given)."""
    frames = frames if frames is not None else _sector_frames(data_dir, sector)
    if not frames:
        return pd.DataFrame()
    first = next(iter(frames.values()))
    feature_cols = [c for c in first.columns if c not in DROP_COLS]
    kind, model, scaler, split = _load_model(data_dir, sector, len(feature_cols), model_dir)
    end = pd.Timestamp(end) if end is not None else None
    in_window = lambda d: d >= split and (end is None or d < end)
    rows = []
    for ticker, full in frames.items():
        close = full['Close'].astype(float).values
        dates = full['Date'].values
        pos_of = {d: i for i, d in enumerate(dates)}       # date -> row in the full history
        # infinite values (e.g. a volume change divided by zero) are treated like gaps
        clean = full.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols).reset_index(drop=True)
        if list(clean.columns) != list(first.columns):
            continue
        X = clean[feature_cols].astype(float).values
        cdates = clean['Date'].values
        if kind == 'lstm':
            import torch
            Xs = scaler.transform(X)
            label_idx = [t for t in range(SEQ_LEN, len(clean)) if in_window(cdates[t])]
            if not label_idx:
                continue
            seqs = np.stack([Xs[t - SEQ_LEN:t] for t in label_idx])
            with torch.no_grad():
                probs = torch.softmax(model(torch.FloatTensor(seqs)), dim=1).numpy()
            info_idx = [t - 1 for t in label_idx]               # last row the model saw
        else:
            label_idx = [t for t in range(len(clean)) if in_window(cdates[t])]
            if not label_idx:
                continue
            probs = model.predict_proba(X[label_idx])
            info_idx = label_idx
        for j, (t, k) in enumerate(zip(label_idx, info_idx)):
            it, ik = pos_of[cdates[t]], pos_of[cdates[k]]
            target = close[it + 1] / close[it] - 1 if it + 1 < len(close) else np.nan
            if ik + 2 < len(close):
                trade_date, tradable = dates[ik + 1], close[ik + 2] / close[ik + 1] - 1
            else:
                trade_date, tradable = pd.NaT, np.nan
            p = probs[j]
            rows.append({
                'sector': sector, 'ticker': ticker, 'model': kind,
                'label_date': cdates[t], 'decision_date': cdates[k], 'trade_date': trade_date,
                'p_sell': float(p[0]), 'p_hold': float(p[1]), 'p_buy': float(p[2]),
                'signal': int(np.argmax(p)), 'score': float(p[2] - p[0]),
                'target_ret': target, 'tradable_ret': tradable,
            })
    out = pd.DataFrame(rows)
    out.attrs['split'] = str(split.date())
    return out


# ----------------------------------------------------------------------------- report
def _sector_report(g, rebal_every=REBAL_EVERY):
    g = g.copy()
    # information: daily cross-sectional rank IC on the model's own target
    ic = g.groupby('label_date').apply(lambda d: rank_ic(d['score'], d['target_ret'])).dropna()
    ic_m, ic_lo, ic_hi, ic_n = boot_ci(ic)
    valid = g.dropna(subset=['target_ret'])
    base = valid['target_ret'].mean()
    buy, sell = valid[valid.signal == 2], valid[valid.signal == 0]

    # S1: deployed rule per ticker, and buy-and-hold, on the tradable timing
    s1_days, bnh_days, trades, s1_tot, bnh_tot, traded = [], [], 0, [], [], []
    for _, t in g.dropna(subset=['tradable_ret']).sort_values('trade_date').groupby('ticker'):
        rets, sigs = t['tradable_ret'].tolist(), t['signal'].tolist()
        d1, n1 = simulate_rule(sigs, rets)
        d0 = buy_and_hold(rets)
        trades += n1
        traded.append(n1 > 0)
        s1_days.append(pd.Series(d1, index=t['trade_date'].values))
        bnh_days.append(pd.Series(d0, index=t['trade_date'].values))
        s1_tot.append(np.prod([1 + x for x in d1]) - 1)
        bnh_tot.append(np.prod([1 + x for x in d0]) - 1)
    s1 = pd.concat(s1_days, axis=1).mean(axis=1) if s1_days else pd.Series(dtype=float)
    bnh = pd.concat(bnh_days, axis=1).mean(axis=1) if bnh_days else pd.Series(dtype=float)
    s1_ex = (s1 - bnh).dropna()

    # S2: weekly top-20% by score vs the sector's equal-weight basket
    s2_ex = pd.Series(dtype=float)
    s2_gross_ex = pd.Series(dtype=float)
    n_tick = g['ticker'].nunique()
    if n_tick >= MIN_TICKERS:
        tr = g.dropna(subset=['tradable_ret'])
        dec_dates = sorted(tr['decision_date'].unique())
        rebal = dec_dates[::rebal_every]
        net, gross, bench, bench_gross, rebal_trade = {}, {}, {}, {}, {}
        for r in rebal:
            snap = tr[tr.decision_date == r]
            if snap.empty:
                continue
            k = max(1, math.ceil(TOP_FRAC * snap['ticker'].nunique()))
            top = snap.sort_values('score', ascending=False)['ticker'].head(k).tolist()
            rebal_trade[snap['trade_date'].iloc[0]] = top
        trade_dates = sorted(tr['trade_date'].unique())
        current, prev_w = None, {}
        by_date = {d: x.set_index('ticker')['tradable_ret'] for d, x in tr.groupby('trade_date')}
        for i, d in enumerate(trade_dates):
            if d in rebal_trade:
                current = rebal_trade[d]
            if current is None:
                continue
            day = by_date[d]
            w = {t: 1 / len(current) for t in current}
            turnover = sum(abs(w.get(t, 0) - prev_w.get(t, 0)) for t in set(w) | set(prev_w))
            prev_w = w
            port = float(np.mean([day[t] for t in current if t in day.index] or [np.nan]))
            cost = turnover * SIDE
            if i == len(trade_dates) - 1:
                cost += SIDE                                    # sell out at the end
            b = float(day.mean())
            bcost = SIDE if i == 0 else (SIDE if i == len(trade_dates) - 1 else 0.0)
            gross[d], net[d] = port, port - cost
            bench[d], bench_gross[d] = b - bcost, b
        if net:
            net, gross = pd.Series(net), pd.Series(gross)
            bench, bench_gross = pd.Series(bench), pd.Series(bench_gross)
            s2_ex = (net - bench).dropna()
            s2_gross_ex = (gross - bench_gross).dropna()

    return {
        'ic': ic, 's1_ex': s1_ex, 's2_ex': s2_ex, 's2_gross_ex': s2_gross_ex,
        'row': {
            'tickers': n_tick, 'days': int(g['label_date'].nunique()),
            'holdout_from': str(pd.Timestamp(g['label_date'].min()).date()),
            'non_hold_share': round(float((g.signal != 1).mean()), 3),
            'buy_calls': int(len(buy)), 'sell_calls': int(len(sell)),
            'mean_ret_all_pct': round(base * 100, 3),
            'mean_ret_after_buy_pct': round(buy['target_ret'].mean() * 100, 3) if len(buy) else None,
            'mean_ret_after_sell_pct': round(sell['target_ret'].mean() * 100, 3) if len(sell) else None,
            'ic_mean': round(ic_m, 4), 'ic_lo': round(ic_lo, 4), 'ic_hi': round(ic_hi, 4), 'ic_days': ic_n,
            's1_trades': trades,
            's1_tickers_traded_pct': round(100 * float(np.mean(traded)), 1) if traded else None,
            's1_mean_total_ret_pct': round(100 * float(np.mean(s1_tot)), 2) if s1_tot else None,
            'bnh_mean_total_ret_pct': round(100 * float(np.mean(bnh_tot)), 2) if bnh_tot else None,
            's1_excess_daily_bp': round(1e4 * s1_ex.mean(), 2) if len(s1_ex) else None,
            's2_excess_daily_bp': round(1e4 * s2_ex.mean(), 2) if len(s2_ex) else None,
            's2_gross_excess_daily_bp': round(1e4 * s2_gross_ex.mean(), 2) if len(s2_gross_ex) else None,
        },
    }


def report(out_dir):
    parts = [pd.read_csv(f, parse_dates=['label_date', 'decision_date', 'trade_date'])
             for f in sorted(out_dir.glob('preds_*.csv'))]
    if not parts:
        sys.exit('no predictions found -- run the predict step first')
    P = pd.concat(parts, ignore_index=True)
    rows, ic_by, s1_by, s2_by, s2g_by = [], {}, {}, {}, {}
    for sector, g in P.groupby('sector'):
        r = _sector_report(g)
        rows.append({'sector': sector, **r['row']})
        ic_by[sector], s1_by[sector], s2_by[sector] = r['ic'], r['s1_ex'], r['s2_ex']
        s2g_by[sector] = r['s2_gross_ex']

    def pooled(by):
        frame = pd.concat({k: v for k, v in by.items() if len(v)}, axis=1)
        return frame.mean(axis=1).dropna()          # each sector weighted equally per day

    ic_p, s1_p, s2_p = pooled(ic_by), pooled(s1_by), pooled(s2_by)
    ic_m, ic_lo, ic_hi, ic_n = boot_ci(ic_p)
    s1_m, s1_lo, s1_hi, s1_n = boot_ci(s1_p)
    s2_m, s2_lo, s2_hi, s2_n = boot_ci(s2_p)
    s2g_p = pooled(s2g_by)
    s2g_m, s2g_lo, s2g_hi, _ = boot_ci(s2g_p)
    p1 = ic_m > 0 and ic_lo > 0
    p2 = (s1_lo > 0) or (s2_lo > 0)
    summary = {
        'predictions': int(len(P)), 'tickers': int(P['ticker'].nunique()), 'sectors': int(P['sector'].nunique()),
        'P1_information': {'pooled_ic': round(ic_m, 4), 'ci95': [round(ic_lo, 4), round(ic_hi, 4)],
                           'days': ic_n, 'pass': bool(p1)},
        'P2_tradability': {
            'S1_rule_excess_daily_bp': round(1e4 * s1_m, 2), 'S1_ci95_bp': [round(1e4 * s1_lo, 2), round(1e4 * s1_hi, 2)],
            'S1_excess_total_pct': round(100 * ((1 + s1_p).prod() - 1), 2), 'S1_days': s1_n,
            'S2_top20_excess_daily_bp': round(1e4 * s2_m, 2), 'S2_ci95_bp': [round(1e4 * s2_lo, 2), round(1e4 * s2_hi, 2)],
            'S2_excess_total_pct': round(100 * ((1 + s2_p).prod() - 1), 2), 'S2_days': s2_n,
            'S2_before_costs_excess_daily_bp': round(1e4 * s2g_m, 2),
            'S2_before_costs_ci95_bp': [round(1e4 * s2g_lo, 2), round(1e4 * s2g_hi, 2)],
            'pass': bool(p2)},
        'PHASE_A_PASS': bool(p1 and p2),
    }
    table = pd.DataFrame(rows).sort_values('tickers', ascending=False)
    table.to_csv(out_dir / 'sector_summary.csv', index=False)
    (out_dir / 'summary.json').write_text(json.dumps(summary, indent=2))
    pd.DataFrame({'pooled_ic': ic_p}).to_csv(out_dir / 'pooled_daily_ic.csv')
    return summary, table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['predict', 'report'])
    ap.add_argument('--sectors', nargs='*', default=None)
    ap.add_argument('--data-dir', default='deploy_data')
    ap.add_argument('--out-dir', default='data/models/signal_eval')
    a = ap.parse_args()
    data_dir, out_dir = Path(a.data_dir), Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.step == 'predict':
        for sector in (a.sectors or ALL_SECTORS):
            df = predict_sector(data_dir, sector)
            name = sector.replace(' ', '_')
            df.to_csv(out_dir / f'preds_{name}.csv', index=False)
            print(f"{sector}: {len(df)} predictions, {df['ticker'].nunique() if len(df) else 0} tickers, "
                  f"holdout from {df.attrs.get('split')}")
    else:
        summary, table = report(out_dir)
        pd.set_option('display.width', 250)
        pd.set_option('display.max_columns', 30)
        print(table.to_string(index=False))
        print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
