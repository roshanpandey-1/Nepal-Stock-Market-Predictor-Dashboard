"""
One-stop tool for poking NEPSE's live API client (the `nepse` package) and
printing back what it actually returns -- company list, live-market field
names, index history shape, or a quick reachability check.

Consolidates what used to be five separate single-purpose scripts
(dump_company_list.py, probe_company_list.py, dump_index_history.py,
dump_live_fields.py, check_live_nepse.py) written at different times to
answer different one-off questions about NEPSE's API surface. Their
findings are already baked into the real code (ml/scraper/live_market.py's
field-picking, scripts/fetch_new_tickers.py's ticker diff) -- this script
exists for the next time that surface needs re-checking (NEPSE changes a
field name, a new endpoint shows up, a reachability question comes up on a
new host), not as part of the regular data pipeline.

Run from the repo root with your venv active:
    python scripts/explore_nepse_api.py --check            # is NEPSE reachable from here?
    python scripts/explore_nepse_api.py --companies         # company list breakdown + CSV dump
    python scripts/explore_nepse_api.py --methods           # every client method, tried generically
    python scripts/explore_nepse_api.py --index-history     # intraday vs daily index/graph shape
    python scripts/explore_nepse_api.py --live-fields        # exact field names on live endpoints
    python scripts/explore_nepse_api.py --all               # run everything above
"""
import argparse
import csv
import json
import sys


def _client():
    from nepse import Nepse
    client = Nepse()
    try:
        client.setTLSVerification(False)
    except Exception:
        pass
    return client


def check_reachable():
    """Is live NEPSE data reachable from THIS machine right now?

    Run this from your own terminal (not inside Claude's sandbox, which is
    firewalled from nepalstock.com). Also worth running again on the
    deployed host (Render shell) -- a success on your laptop in Kathmandu
    says nothing about a server in Oregon.
    """
    print("1. Importing the nepse client...")
    try:
        from nepse import Nepse  # noqa: F401
    except ImportError as exc:
        print(f"   FAIL: {exc}")
        print("\n   The wrong `nepse` package is installed. PyPI's `nepse` and")
        print("   NepseUnofficialApi share an import name but differ completely.")
        print("   Fix:  pip uninstall -y nepse")
        print("         pip install git+https://github.com/basic-bgnr/NepseUnofficialApi")
        return 1
    print("   OK")

    print("2. Creating client...")
    client = _client()
    print("   OK")

    checks = [
        ("market status", "getMarketStatus"),
        ("NEPSE index", "getNepseIndex"),
        ("top gainers", "getTopGainers"),
        ("live market", "getLiveMarket"),
    ]

    failures = 0
    for label, method in checks:
        print(f"3. Fetching {label} ({method})...")
        try:
            data = getattr(client, method)()
        except Exception as exc:
            failures += 1
            print(f"   FAIL: {type(exc).__name__}: {str(exc)[:160]}")
            continue

        if isinstance(data, list):
            print(f"   OK: {len(data)} rows")
            if data and isinstance(data[0], dict):
                print(f"   sample keys: {list(data[0].keys())[:8]}")
                print(f"   sample row : {str(data[0])[:200]}")
        else:
            print(f"   OK: {str(data)[:200]}")

    print()
    if failures == 0:
        print("RESULT: live NEPSE data IS reachable from this machine.")
        print("The dashboard's Market Now panel will populate here.")
        return 0
    if failures == len(checks):
        print("RESULT: NEPSE is NOT reachable from this machine.")
        print("Could be the network, a geo-block, or NEPSE being down.")
        print("The dashboard still works -- it falls back to end-of-day data.")
        return 2
    print(f"RESULT: partial -- {failures}/{len(checks)} calls failed.")
    return 3


def dump_companies(out_csv="data/processed/nepse_live_company_list.csv"):
    """Breakdown of getCompanyList() by instrument type / status, and a CSV
    of active equities (symbol, companyName, sectorName, status,
    instrumentType) -- the authoritative source for diffing our dataset's
    ticker coverage against what NEPSE actually lists."""
    client = _client()
    companies = client.getCompanyList()
    print(f"Total entries: {len(companies)}")

    instrument_types = {}
    statuses = {}
    for comp in companies:
        t = comp.get("instrumentType", "Unknown")
        instrument_types[t] = instrument_types.get(t, 0) + 1
        s = comp.get("status", "Unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print("By instrumentType:", instrument_types)
    print("By status:", statuses)

    equity = [c for c in companies if c.get("instrumentType") == "Equity"]
    active_equity = [c for c in equity if c.get("status") == "A"]
    print(f"\nEquity instruments: {len(equity)}")
    print(f"Active equity instruments: {len(active_equity)}")

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "companyName", "sectorName", "status", "instrumentType"])
        for comp in active_equity:
            writer.writerow([
                comp.get("symbol"), comp.get("companyName"),
                comp.get("sectorName"), comp.get("status"), comp.get("instrumentType"),
            ])
    print(f"\nWrote {out_csv}")


def probe_methods():
    """Try every public method on the client generically and print a
    sample of whatever each one returns -- useful when NEPSE adds an
    endpoint or `nepse`'s client wraps a new one and you want to see what's
    actually available without reading the library source."""
    client = _client()
    candidates = [m for m in dir(client) if not m.startswith("_")]
    print("ALL METHODS:")
    print(candidates)
    print()

    interesting = [
        "getCompanyList", "getCompanyListInfo", "getSectorScrips", "getCompanyDetails",
        "getCompany", "getListedCompanies", "getSecurityList", "getFloorsheet",
        "getSectorWiseSummary", "getSecurityDetails",
    ]
    for name in interesting:
        if not hasattr(client, name):
            continue
        try:
            result = getattr(client, name)()
            print(f"--- {name}() ---")
            if isinstance(result, list):
                print("length:", len(result))
                print("sample:", json.dumps(result[0], default=str, indent=2) if result else None)
            elif isinstance(result, dict):
                print("keys:", list(result.keys())[:10])
                first_key = next(iter(result), None)
                print("sample value:", json.dumps(result[first_key], default=str, indent=2) if first_key else None)
            else:
                print(type(result), str(result)[:300])
        except Exception as exc:
            print(f"--- {name}() FAILED: {exc} ---")
        print()


def dump_index_history():
    """Probe what index/price-graph history NEPSE exposes -- specifically
    whether any endpoint returns INTRADAY points (minute-by-minute, like
    ShareHub's 1D view) or only one point per day. Best run while the
    market is open."""
    client = _client()

    def describe(label, fetch):
        print()
        print("=" * 70)
        print(label)
        print("=" * 70)
        try:
            data = fetch()
        except Exception as exc:
            print(f"FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            return
        if isinstance(data, list):
            print(f"rows: {len(data)}")
            if data:
                print("\nFIRST row:")
                print(json.dumps(data[0], indent=2, default=str)[:600])
                print("\nLAST row:")
                print(json.dumps(data[-1], indent=2, default=str)[:600])
                first = data[0]
                if isinstance(first, dict):
                    for key in ("time", "businessDate", "generatedTime",
                                "lastUpdatedDateTime", "date", "timestamp"):
                        if key in first:
                            print(f"\ntime field '{key}': "
                                  f"first={first.get(key)!r} last={data[-1].get(key)!r}")
        elif isinstance(data, dict):
            print(json.dumps(data, indent=2, default=str)[:900])
        else:
            print(repr(data)[:400])

    describe("getDailyNepseIndexGraph()  <- is this intraday or one point per day?",
              client.getDailyNepseIndexGraph)
    describe("getNepseSubIndices()", client.getNepseSubIndices)
    try:
        describe("getDailyScripPriceGraph('NABIL')",
                  lambda: client.getDailyScripPriceGraph("NABIL"))
    except Exception as exc:
        print(f"\ngetDailyScripPriceGraph unavailable: {exc}")

    print()
    print("=" * 70)
    print("SUMMARY: if the time field above changes WITHIN a single day, a true")
    print("ShareHub-style 1D intraday chart is possible. If it only changes by")
    print("date, the 1D view has to be accumulated live instead.")
    print("=" * 70)


def dump_live_fields():
    """Dump the exact field names NEPSE's live endpoints return, so the
    dashboard's normalisation code (live_market.py's _pick() calls) can be
    written against reality rather than guesses."""
    client = _client()

    print("=" * 70)
    print("MARKET STATUS")
    print("=" * 70)
    print(json.dumps(client.getMarketStatus(), indent=2, default=str)[:400])

    print()
    print("=" * 70)
    print("NEPSE INDEX -- all rows, so we can see which one is the headline index")
    print("=" * 70)
    index = client.getNepseIndex()
    for row in (index if isinstance(index, list) else [index]):
        name = row.get("index") or row.get("indexName")
        print(f"\n--- {name} ---")
        print(json.dumps(row, indent=2, default=str))

    print()
    print("=" * 70)
    print("TOP GAINERS -- one full row")
    print("=" * 70)
    gainers = client.getTopGainers()
    if gainers:
        print(json.dumps(gainers[0], indent=2, default=str))

    print()
    print("=" * 70)
    print("LIVE MARKET -- one full row")
    print("=" * 70)
    live = client.getLiveMarket()
    if live:
        print(json.dumps(live[0], indent=2, default=str))
        print(f"\n(total rows: {len(live)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="Reachability check (is NEPSE reachable from here?)")
    ap.add_argument("--companies", action="store_true", help="Company list breakdown + CSV dump")
    ap.add_argument("--methods", action="store_true", help="Probe every client method generically")
    ap.add_argument("--index-history", action="store_true", help="Probe index/graph history shape (intraday vs daily)")
    ap.add_argument("--live-fields", action="store_true", help="Dump exact field names on live endpoints")
    ap.add_argument("--all", action="store_true", help="Run everything above")
    args = ap.parse_args()

    ran_anything = False
    if args.check or args.all:
        ran_anything = True
        rc = check_reachable()
        if rc != 0 and not args.all:
            return rc
    if args.companies or args.all:
        ran_anything = True
        dump_companies()
    if args.methods or args.all:
        ran_anything = True
        probe_methods()
    if args.index_history or args.all:
        ran_anything = True
        dump_index_history()
    if args.live_fields or args.all:
        ran_anything = True
        dump_live_fields()

    if not ran_anything:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
