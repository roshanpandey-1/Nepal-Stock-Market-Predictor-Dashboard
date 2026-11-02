"""Build the daily market report (deploy_data/reports/market/<date>.json).

Run by .github/workflows/refresh-prices.yml right after the price refresh:

    python scripts/build_daily_report.py --data-dir deploy_data --capture-index

--capture-index tries to record the official NEPSE index close for the session
via NepseUnofficialApi (ml/scraper/live_market.py). It is best effort: NEPSE
often refuses connections from servers outside Nepal, and when it does the
report simply says the index was not captured. It never fails the job.
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.analysis import daily_report  # noqa: E402

KEEP_REPORTS = 120          # about six months of trading days
NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))
INDEX_FIELDS = ["date", "value", "change", "change_pct", "captured_at"]


def read_index(path):
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        out = {}
        for r in csv.DictReader(f):
            try:
                out[r["date"]] = {"date": r["date"], "value": float(r["value"]),
                                  "change": float(r["change"]) if r["change"] else None,
                                  "change_pct": float(r["change_pct"]) if r["change_pct"] else None,
                                  "captured_at": r.get("captured_at")}
            except (KeyError, ValueError):
                continue
        return out


def write_index(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k) for k in INDEX_FIELDS})


def capture_index(session_date, now=None, fetch=None):
    """The official NEPSE index close for `session_date`, or None.

    Only accepted when NEPSE reports the market closed and it is still the same
    calendar day in Nepal, so a value can never be filed under the wrong session.
    """
    now = now or datetime.now(NEPAL_TZ)
    if now.astimezone(NEPAL_TZ).date().isoformat() != session_date:
        print(f"index: not captured (Nepal date {now.astimezone(NEPAL_TZ).date()} != session {session_date})")
        return None
    try:
        if fetch is None:
            from ml.scraper.live_market import fetch_live_snapshot as fetch
        snap = fetch()
    except Exception as exc:  # missing library, network, anything
        print(f"index: not captured ({type(exc).__name__}: {exc})")
        return None
    idx = snap.get("index") if snap else None
    if not idx or snap.get("market_open") is not False:
        print(f"index: not captured (available={bool(idx)}, market_open={snap.get('market_open') if snap else None})")
        return None
    return {"date": session_date, "value": idx["value"], "change": idx.get("change"),
            "change_pct": idx.get("change_pct"), "captured_at": now.isoformat(timespec="seconds")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="deploy_data")
    ap.add_argument("--capture-index", action="store_true")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    out_dir = data_dir / "reports" / "market"
    index_path = data_dir / "reports" / "nepse_index.csv"
    index_rows = read_index(index_path)

    from ml.analysis import market
    session_date, _ = market.stock_table(data_dir)
    if args.capture_index and session_date:
        row = capture_index(session_date)
        if row:
            index_rows[session_date] = row
            write_index(index_path, index_rows)
            print(f"index: captured {row['value']} for {session_date}")

    report = daily_report.build(data_dir, index_row=index_rows.get(session_date))
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    (out_dir / f"{report['date']}.json").write_text(text, encoding="utf-8")
    (out_dir / "latest.json").write_text(text, encoding="utf-8")

    dated = sorted(p for p in out_dir.glob("????-??-??.json"))
    for old in dated[:-KEEP_REPORTS]:
        old.unlink()
    print(f"report: {report['date']} written ({len(dated[-KEEP_REPORTS:])} kept)")


if __name__ == "__main__":
    main()
