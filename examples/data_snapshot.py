"""
Pack / unpack the full price history so scheduled GitHub Actions jobs can use it.

data/raw and data/processed (~350 MB) are gitignored, so a fresh CI checkout has
no history to update, forecast from, or retrain on. This script bundles them
into one compressed archive, data-snapshot.tar.gz (~100 MB), which lives as an
asset on a GitHub release tagged `data-latest` instead of inside git history.

    python examples/data_snapshot.py pack      # data/ -> data-snapshot.tar.gz
    python examples/data_snapshot.py unpack    # data-snapshot.tar.gz -> data/
    python examples/data_snapshot.py check     # fail if the newest price row is too old

First-time setup (once, from your machine): run `pack`, then create a GitHub
release with tag `data-latest` and attach data-snapshot.tar.gz (web UI:
Releases -> Draft a new release; or `gh release create data-latest
data-snapshot.tar.gz`). The daily workflow downloads, updates and re-uploads it.
"""
import argparse
import sys
import tarfile
from datetime import date, datetime
from pathlib import Path

ARCHIVE = Path("data-snapshot.tar.gz")
INCLUDE_DIRS = ["data/raw", "data/processed"]
# Transient resume logs -- must not travel with the snapshot, or the next run
# would think every ticker was already updated.
EXCLUDE_NAMES = {"incremental_done.txt", "historical_done.txt"}


def pack(archive: Path = ARCHIVE):
    n = 0
    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for d in INCLUDE_DIRS:
            for p in sorted(Path(d).rglob("*")):
                if p.is_file() and p.name not in EXCLUDE_NAMES:
                    tar.add(p, arcname=p.as_posix())
                    n += 1
    print(f"Packed {n} files -> {archive} ({archive.stat().st_size / 1e6:.1f} MB)")


def unpack(archive: Path = ARCHIVE):
    if not archive.exists():
        sys.exit(f"{archive} not found -- download it from the `data-latest` release first.")
    with tarfile.open(archive, "r:gz") as tar:
        # Refuse absolute paths / path traversal before extracting.
        for m in tar.getmembers():
            if m.name.startswith(("/", "..")) or ".." in Path(m.name).parts:
                sys.exit(f"Unsafe path in archive: {m.name}")
        tar.extractall(".")
    print(f"Unpacked {archive} into ./data")


def check(max_age_days: int):
    """Exit non-zero if no ticker has a price row newer than max_age_days.

    A scrape that is silently blocked looks identical to "no new rows today",
    so the scheduled job calls this to turn staleness into a visible failure.
    The default allows for NEPSE's long Dashain/Tihar closures.
    """
    newest = None
    for p in Path("data/raw").glob("*.csv"):
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - 600, 0))
            last = f.read().decode("utf-8", "ignore").strip().splitlines()[-1]
        try:
            d = datetime.strptime(last.split(",")[0][:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        newest = d if newest is None or d > newest else newest
    if newest is None:
        sys.exit("Freshness check: could not read any dates from data/raw")
    age = (date.today() - newest).days
    print(f"Newest price row: {newest} ({age} days ago, limit {max_age_days})")
    if age > max_age_days:
        sys.exit(f"STALE: newest price row is {age} days old -- the scrape probably "
                 f"failed or was blocked.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["pack", "unpack", "check"])
    ap.add_argument("--archive", default=str(ARCHIVE))
    ap.add_argument("--max-age-days", type=int, default=12)
    a = ap.parse_args()
    if a.action == "check":
        check(a.max_age_days)
    else:
        (pack if a.action == "pack" else unpack)(Path(a.archive))
