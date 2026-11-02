"""Collect company fundamentals (as reported on Merolagani) for every tracked ticker.

    python scripts/fetch_fundamentals.py --data-dir deploy_data [--only NABIL,NICA] [--pause 3]

Writes deploy_data/external/fundamentals.json. Run weekly by
.github/workflows/weekly-fundamentals.yml. It is deliberately slow (one page
every few seconds). A company whose page fails keeps its previous values with
their original collection date, so nothing is silently replaced by a blank.
The job fails only if most pages fail (a sign the site changed or blocks us).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.scraper import fundamentals as F  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="deploy_data")
    ap.add_argument("--only", default="")
    ap.add_argument("--pause", type=float, default=3.0)
    args = ap.parse_args(argv)

    import requests

    data_dir = Path(args.data_dir)
    out_path = data_dir / "external" / "fundamentals.json"
    tickers = [t.strip().upper() for t in (data_dir / "processed" / "ticker_list.txt").read_text().splitlines() if t.strip()]
    if args.only:
        tickers = [t.strip().upper() for t in args.only.split(",") if t.strip()]

    try:
        store = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        store = {"companies": {}}
    companies = store.get("companies", {})

    session = requests.Session()
    ok, failed = 0, {}
    for i, t in enumerate(tickers, 1):
        data, err = F.fetch_company(t, session, pause=args.pause)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if data:
            companies[t] = dict(data, fetched_at=now, url=F.URL.format(symbol=t))
            ok += 1
        else:
            failed[t] = err
        if i % 25 == 0:
            print(f"{i}/{len(tickers)} done, {ok} ok, {len(failed)} failed", flush=True)
        time.sleep(args.pause)

    store.update({
        "source": F.SOURCE_NAME,
        "source_note": ("Figures as published on Merolagani company pages, taken from companies' reports "
                        "(quarterly figures are usually unaudited). Not checked against the original filings."),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "companies": companies,
        "last_run": {"requested": len(tickers), "ok": ok, "failed": failed},
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"fundamentals: {ok}/{len(tickers)} collected, {len(failed)} failed")
    if tickers and ok < len(tickers) * 0.5:
        sys.exit("More than half of the pages failed; the site may have changed or be blocking requests.")


if __name__ == "__main__":
    main()
