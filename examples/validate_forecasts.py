"""
Step 5: how accurate are the Prophet price forecasts?

Rolling-origin backtest. For each origin date below and each stock, Prophet is
fitted on ONLY the prices before the origin, then asked for the price on each of the next
30 actual trading days. Those predictions are compared with what really
happened and with the simplest possible forecast, "no change" (tomorrow's and
next month's price = the last close).

Both the old setting (weekly_seasonality=True, still live) and the new one
(False) are tested, so the fix is measured too.

Round 1 (old, new) failed F1 badly: about 3x the error of "no change". Round 2
tests three alternatives, all fixed on 2026-10-24 before they were run:
  recent    train on the last 2 years only, no yearly or weekly seasonality
  flexible  as recent, but a 10x more flexible trend (changepoint_prior_scale 0.5)
  anchored  as recent, then the whole forecast (and range) is shifted so it starts
            from the last close instead of Prophet's fitted level
The same F1-F3 rules apply. A variant replaces the production setting only if it
passes F1 and F2; if several pass, the one with the lowest 30-day error wins.
Otherwise the forecasts are labelled as not predictive on the dashboard.

Outcome: none passed. "anchored" was the least wrong (30-day error 7.3% vs 5.6%
for "no change") and the only one with an honest 80% range, so it became the
production recipe (src/models/forecaster.py fit_and_forecast) and the dashboard
shows it as a range of likely prices, not a prediction. The "production" variant
runs that exact function, so re-running it checks the live recipe.

Decision rules (fixed on 2026-10-24, before the first run):
  F1 accuracy   at 5, 20 and 30 trading days ahead, Prophet's mean absolute
                percentage error is lower than "no change", with the 95% CI of
                the paired difference (bootstrap over stocks) entirely below 0.
  F2 direction  at 20 and 30 trading days ahead, Prophet calls up/down correctly
                more than 50% of the time, with the 95% CI lower bound above 50%.
  F3 ranges     the 80% forecast range contains the real 30-day price between
                70% and 90% of the time (otherwise the range is mis-stated).
The forecasts count as useful predictions only if F1 and F2 both pass.

Run from the repo root (needs prophet, like the weekly forecast job):
  python examples/validate_forecasts.py run [--variants recent anchored]   # resumable
  python examples/validate_forecasts.py report
Results go to data/models/forecast_eval/ (gitignored).
"""
import argparse
import json
import logging
import sys
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append('.')
warnings.filterwarnings('ignore')

ORIGINS = ['2025-10-20', '2025-12-21', '2026-02-20', '2026-04-20', '2026-06-21', '2026-08-20']
HORIZONS = [1, 5, 10, 20, 30]          # trading days ahead
MIN_TRAIN_ROWS = 100                    # same floor as build_forecasts.py
MAX_STALE_DAYS = 10                     # skip stocks that had not traded shortly before the origin
# Production settings at the time of round 1, kept fixed here so the round-1 and
# round-2 variants stay reproducible after production changed.
BASE_PARAMS = dict(daily_seasonality=False, weekly_seasonality=False,
                   yearly_seasonality=True, changepoint_prior_scale=0.05)
VARIANTS = {   # overrides on BASE_PARAMS; train_years None = full history
    'new': {},
    'old': {'weekly_seasonality': True},
    'recent': {'yearly_seasonality': False, 'train_years': 2},
    'flexible': {'yearly_seasonality': False, 'changepoint_prior_scale': 0.5, 'train_years': 2},
    'anchored': {'yearly_seasonality': False, 'train_years': 2, 'anchor': True},
    'production': {'production': True},   # src/models/forecaster.fit_and_forecast as deployed
}
OUT = Path('data/models/forecast_eval')
B = 2000


def _quiet():
    for name in ('cmdstanpy', 'prophet'):
        logging.getLogger(name).setLevel(logging.ERROR)


def _job(args):
    ticker, origin, variant = args
    _quiet()
    from prophet import Prophet
    df = pd.read_csv(f'data/raw/{ticker}.csv', usecols=['Date', 'Close'])
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.dropna().sort_values('Date').drop_duplicates('Date')
    o = pd.Timestamp(origin)
    train, future = df[df.Date < o], df[df.Date >= o].head(max(HORIZONS))
    if len(train) < MIN_TRAIN_ROWS or len(future) < max(HORIZONS) or (o - train.Date.iloc[-1]).days > MAX_STALE_DAYS:
        return []
    targets = future.iloc[[h - 1 for h in HORIZONS]]
    last = float(train.Close.iloc[-1])
    cfg = dict(VARIANTS[variant])
    if cfg.pop('production', False):
        from src.models.forecaster import fit_and_forecast
        fc = fit_and_forecast(train, targets.Date.values).reset_index(drop=True)
        return _rows(ticker, origin, variant, last, targets, fc)
    years, anchor = cfg.pop('train_years', None), cfg.pop('anchor', False)
    if years:
        train = train[train.Date >= o - pd.DateOffset(years=years)]
    m = Prophet(**dict(BASE_PARAMS, **cfg))
    m.fit(train.rename(columns={'Date': 'ds', 'Close': 'y'}))
    fc = m.predict(pd.DataFrame({'ds': targets.Date.values}))
    if anchor:   # start the forecast from the last close, keep Prophet's predicted path
        shift = last - float(m.predict(pd.DataFrame({'ds': [train.Date.iloc[-1]]})).yhat.iloc[0])
        fc[['yhat', 'yhat_lower', 'yhat_upper']] += shift
    return _rows(ticker, origin, variant, last, targets, fc)


def _rows(ticker, origin, variant, last, targets, fc):
    return [{'ticker': ticker, 'origin': origin, 'variant': variant, 'h': h, 'date': str(d.date()),
             'last_close': last, 'actual': float(a), 'yhat': float(y), 'lo': float(lo), 'hi': float(hi)}
            for h, d, a, y, lo, hi in zip(HORIZONS, targets.Date, targets.Close, fc.yhat, fc.yhat_lower, fc.yhat_upper)]


def cmd_run(workers, variants):
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / 'predictions.csv'
    done = set()
    if out.exists():
        p = pd.read_csv(out)
        done = set(zip(p.ticker, p.origin, p.variant))
    tickers = [t.strip() for t in open('data/processed/ticker_list.txt') if t.strip()]
    jobs = [(t, o, v) for v in variants for o in ORIGINS for t in tickers if (t, o, v) not in done]
    print(f'{len(jobs)} fits to run', flush=True)
    with Pool(workers) as pool:
        for i, rows in enumerate(pool.imap_unordered(_job, jobs, chunksize=4), 1):
            if rows:
                pd.DataFrame(rows).to_csv(out, mode='a', header=not out.exists(), index=False)
            if i % 100 == 0:
                print(f'  {i}/{len(jobs)}', flush=True)


def _cluster_ci(values, clusters, rng):
    """Mean and 95% CI, resampling whole stocks (a stock's errors are correlated)."""
    df = pd.DataFrame({'v': values, 'c': clusters})
    g = df.groupby('c')['v'].agg(['sum', 'count'])
    s, n = g['sum'].values, g['count'].values
    idx = rng.integers(0, len(g), size=(B, len(g)))
    boots = s[idx].sum(axis=1) / n[idx].sum(axis=1)
    return float(df.v.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def _r(x, k=2):
    return [round(v, k) for v in x]


def evaluate(p):
    rng = np.random.default_rng(0)
    p = p.copy()
    p['ape'] = (p.yhat - p.actual).abs() / p.actual * 100
    p['ape_naive'] = (p.last_close - p.actual).abs() / p.actual * 100
    p['move'] = np.sign(p.actual - p.last_close)
    p['call'] = np.sign(p.yhat - p.last_close)
    p['inside'] = (p.actual >= p.lo) & (p.actual <= p.hi)
    res = {}
    for h, g in p.groupby('h'):
        d = g[g.move != 0]
        res[int(h)] = {
            'n': int(len(g)),
            'prophet_mape': _r(_cluster_ci(g.ape, g.ticker, rng)),
            'naive_mape': _r(_cluster_ci(g.ape_naive, g.ticker, rng)),
            'diff_prophet_minus_naive': _r(_cluster_ci(g.ape - g.ape_naive, g.ticker, rng)),
            'prophet_median_ape': round(float(g.ape.median()), 2),
            'naive_median_ape': round(float(g.ape_naive.median()), 2),
            'share_prophet_closer': round(float((g.ape < g.ape_naive).mean() * 100), 1),
            'direction_hit_pct': _r([100 * x for x in _cluster_ci((d.call == d.move).astype(float), d.ticker, rng)], 1),
            'share_up_pct': round(float((d.move > 0).mean() * 100), 1),
            'range80_coverage_pct': round(float(g.inside.mean() * 100), 1),
            'over_50pct_error_share': round(float((g.ape > 50).mean() * 100), 1),
        }
    return res


def cmd_report():
    p = pd.read_csv(OUT / 'predictions.csv')
    summary = {'origins': ORIGINS, 'stocks': int(p.ticker.nunique())}
    for v, g in p.groupby('variant'):
        r = evaluate(g)
        f1 = all(r[h]['diff_prophet_minus_naive'][2] < 0 for h in (5, 20, 30))
        f2 = all(r[h]['direction_hit_pct'][1] > 50 for h in (20, 30))
        f3 = 70 <= r[30]['range80_coverage_pct'] <= 90
        by_origin = {o: round(float(((gg.yhat - gg.actual).abs() / gg.actual * 100).mean()
                                    - ((gg.last_close - gg.actual).abs() / gg.actual * 100).mean()), 2)
                     for o, gg in g[g.h == 30].groupby('origin')}
        summary[v] = {'fits': int(g.groupby(['ticker', 'origin']).ngroups), 'by_horizon': r,
                      'h30_mape_diff_by_origin': by_origin,
                      'F1_accuracy_pass': f1, 'F2_direction_pass': f2, 'F3_range_pass': f3,
                      'USEFUL_PREDICTIONS': bool(f1 and f2)}
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['run', 'report'])
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--variants', nargs='*', default=list(VARIANTS))
    a = ap.parse_args()
    cmd_run(a.workers, a.variants) if a.step == 'run' else cmd_report()


if __name__ == '__main__':
    main()
