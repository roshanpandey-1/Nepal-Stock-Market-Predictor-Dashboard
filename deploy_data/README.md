# deploy_data/

A trimmed snapshot of `data/processed` and `data/models`, committed to git on purpose (unlike the full `data/`
folder, which is gitignored) so the live dashboard has something to serve on a host that only has what is in
this repo.

- `processed/`: the last ~260 rows per stock (enough for the 180-day price chart and the LSTM's 10-day window),
  not the full price history.
- `models/`: the deployed `*_oos` sector models with their scalers and split dates, `retrain_report.csv` (the
  holdout results behind the reliability tags), the 30-day price ranges (`forecast_summary.csv`,
  `forecast_daily.csv`), the one-stock backtest summary, the "Why this signal?" explanations
  (`explanations.json`, built by `scripts/build_explanations.py`), and the test results shown on the site
  (`signal_evidence.json`, `forecast_evidence.json`).

GitHub Actions keep this folder current. To rebuild it by hand from your full local `data/`:

    python scripts/build_deploy_snapshot.py

The app serves this folder by default (`python run.py`) and on Render (`DATA_DIR=deploy_data`). Set
`DATA_DIR=data` to use the full local dataset instead.
