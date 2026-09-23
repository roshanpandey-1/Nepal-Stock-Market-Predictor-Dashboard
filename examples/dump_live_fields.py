"""
Dump the exact field names NEPSE returns, so the dashboard's normalisation
can be written against reality rather than guesses.

Run from the repo root with your venv active:
    python examples/dump_live_fields.py
"""
import json

from nepse import Nepse


def main():
    client = Nepse()
    try:
        client.setTLSVerification(False)
    except Exception:
        pass

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
    g = client.getTopGainers()
    if g:
        print(json.dumps(g[0], indent=2, default=str))

    print()
    print("=" * 70)
    print("LIVE MARKET -- one full row")
    print("=" * 70)
    live = client.getLiveMarket()
    if live:
        print(json.dumps(live[0], indent=2, default=str))
        print(f"\n(total rows: {len(live)})")


if __name__ == "__main__":
    main()
