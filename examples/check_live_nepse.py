"""
Check whether live NEPSE data is reachable from THIS machine.

Run this from your own terminal (not inside Claude's sandbox, which is
firewalled from nepalstock.com):

    pip install git+https://github.com/basic-bgnr/NepseUnofficialApi
    python examples/check_live_nepse.py

Run it again on the deployed host (Render shell) if you want to know whether
the live panel will work in production -- a success on your laptop in
Kathmandu says nothing about a server in Oregon.
"""
import sys


def main():
    print("1. Importing the nepse client...")
    try:
        from nepse import Nepse
    except ImportError as exc:
        print(f"   FAIL: {exc}")
        print("\n   The wrong `nepse` package is installed. PyPI's `nepse` and")
        print("   NepseUnofficialApi share an import name but differ completely.")
        print("   Fix:  pip uninstall -y nepse")
        print("         pip install git+https://github.com/basic-bgnr/NepseUnofficialApi")
        return 1
    print("   OK")

    print("2. Creating client...")
    client = Nepse()
    try:
        client.setTLSVerification(False)
    except Exception:
        pass
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
            if data:
                first = data[0]
                if isinstance(first, dict):
                    keys = list(first.keys())[:8]
                    print(f"   sample keys: {keys}")
                    print(f"   sample row : {str(first)[:200]}")
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
    print("Some endpoints may have changed; paste the output back to Claude.")
    return 3


if __name__ == "__main__":
    sys.exit(main())
