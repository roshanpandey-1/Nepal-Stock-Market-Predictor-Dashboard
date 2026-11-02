"""Collect recent ShareSansar announcements and news headlines.

    python scripts/fetch_announcements.py --data-dir deploy_data [--days 5]

Updates deploy_data/external/announcements.json (headline, date, link,
category, ticker -- never article text), keeping the last 120 days. Run daily
by .github/workflows/refresh-prices.yml. Never fails the job on a network
problem; it just keeps the previous file.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.scraper import announcements as A  # noqa: E402

KEEP_DAYS = 120


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="deploy_data")
    ap.add_argument("--days", type=int, default=5, help="how far back to read the listings")
    ap.add_argument("--max-pages", type=int, default=60, help="safety cap on listing pages per feed")
    args = ap.parse_args(argv)

    import requests

    data_dir = Path(args.data_dir)
    out_path = data_dir / "external" / "announcements.json"
    names = json.loads((data_dir / "processed" / "company_names.json").read_text(encoding="utf-8"))
    index = A.build_name_index(names)
    try:
        store = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        store = {"items": []}

    today = date.today().isoformat()
    since = (date.today() - timedelta(days=args.days)).isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session = requests.Session()
    new, errors = [], []
    for kind, url in (("announcement", A.ANNOUNCEMENTS_URL), ("news", A.NEWS_URL)):
        items, errs = A.fetch_listing(url, session, since, max_pages=args.max_pages)
        errors += errs
        new += A.enrich(items, kind, index, now)
        print(f"{kind}: {len(items)} items since {since}" + (f" ({'; '.join(errs)})" if errs else ""))

    store.update({
        "source": A.SOURCE_NAME,
        "source_note": "Headlines and links from ShareSansar. Open the link for the full announcement.",
        "updated_at": now if new else store.get("updated_at"),
        "items": A.merge(A.reclassify(store.get("items", []), index), new, KEEP_DAYS, today),
        "last_run": {"at": now, "new": len(new), "errors": errors},
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"announcements: {len(store['items'])} stored")


if __name__ == "__main__":
    main()
