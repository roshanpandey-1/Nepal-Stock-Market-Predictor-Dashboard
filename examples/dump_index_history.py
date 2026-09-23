"""
Probe what index history NEPSE exposes, so the dashboard's index chart can be
built against real data.

Run from the repo root with your venv active, ideally while the market is open:
    python examples/dump_index_history.py

We specifically need to know whether any endpoint returns INTRADAY points
(minute-by-minute, like ShareHub's 1D view) or only one point per day.
"""
import json

from nepse import Nepse


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
            # Are the timestamps intraday or daily?
            first, last = data[0], data[-1]
            if isinstance(first, dict):
                for key in ("time", "businessDate", "generatedTime",
                            "lastUpdatedDateTime", "date", "timestamp"):
                    if key in first:
                        print(f"\ntime field '{key}': "
                              f"first={first.get(key)!r} last={last.get(key)!r}")
    elif isinstance(data, dict):
        print(json.dumps(data, indent=2, default=str)[:900])
    else:
        print(repr(data)[:400])


def main():
    client = Nepse()
    try:
        client.setTLSVerification(False)
    except Exception:
        pass

    describe("getDailyNepseIndexGraph()  <- is this intraday or one point per day?",
             client.getDailyNepseIndexGraph)

    describe("getNepseSubIndices()", client.getNepseSubIndices)

    # Per-scrip graph, for reference -- tells us the shape used for price charts
    try:
        describe("getDailyScripPriceGraph('NABIL')",
                 lambda: client.getDailyScripPriceGraph("NABIL"))
    except Exception as exc:
        print(f"\ngetDailyScripPriceGraph unavailable: {exc}")

    print()
    print("=" * 70)
    print("SUMMARY: if the time field above changes WITHIN a single day, we can")
    print("build a true ShareHub-style 1D intraday chart. If it only changes by")
    print("date, the 1D view has to be accumulated live instead.")
    print("=" * 70)


if __name__ == "__main__":
    main()
