# deploy_data/

A trimmed snapshot of `data/processed`, `data/models`, and `data/news`,
committed to git on purpose (unlike the full `data/` directories, which are
gitignored) so the live dashboard has something to serve on a host that only
has what's in this repo.

- `processed/`: last ~260 rows per ticker (enough for the dashboard's 180-day
  price chart and the LSTM's 10-day lookback window), not the full price
  history back to each ticker's listing date.
- `models/`: only the `*_oos` models (the out-of-sample ones actually used by
  the dashboard's `/api/signal` endpoint) plus their scalers and split-date
  files -- not every experimental model version in `data/models/`.
- `news/`: the sentiment CSVs as-is (small enough not to need trimming).

Regenerate this folder any time the underlying data/models are refreshed:
    python examples/build_deploy_snapshot.py

This folder is served when the app is started with `DATA_DIR=deploy_data`
(see `render.yaml`); running `python run.py` locally with no env var set
still uses the full `data/` directory as before.
