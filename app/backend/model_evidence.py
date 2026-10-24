"""How much to trust each sector model, judged from its latest holdout test.

The weekly retrain writes ``models/retrain_report.csv``: for every sector, how
the deployed model scored on a chronological holdout next to a naive
"always predict Hold" baseline. This module turns that into a plain-language
verdict the dashboard shows beside every Buy/Sell/Hold signal, so a "Hold"
that carries no information is not presented like a real call.

Three verdicts, from the model's own test results:

* ``no_edge``   -- it says Hold on almost every test sample, so its accuracy is
                   the always-Hold accuracy and a Hold from it tells you nothing.
* ``unproven``  -- it does call Buy/Sell, but is not meaningfully more accurate
                   than always guessing Hold.
* ``tested``    -- it beat always-Hold accuracy by a clear margin on the holdout.
                   One short window is still not proof, and the caveat says so.

``unknown`` is used when there is no report row for the sector. The scoring
function ``assess`` is pure (no Flask, no files) so it is easy to test.
"""
import csv
import os
from pathlib import Path

REPORT_NAME = "retrain_report.csv"

NO_EDGE_BELOW = 0.05   # under 5% Buy/Sell predictions counts as "always Hold"
EDGE_MARGIN = 0.02     # must beat always-Hold accuracy by 2 percentage points

_CACHE = {"key": None, "data": {}}


def _report_path():
    return Path(os.environ.get("DATA_DIR", "data")) / "models" / REPORT_NAME


def _num(row, name):
    try:
        return float(row[name])
    except (KeyError, TypeError, ValueError):
        return None


def load_evidence(path=None):
    """{sector: evidence} for the model currently deployed in each sector.

    A promoted candidate is the deployed model, so its ("new_") scores apply;
    when the current model was kept, the ("old_") scores apply. If the report
    holds several runs, the latest run per sector wins. Re-read when the file
    changes.
    """
    path = Path(path) if path else _report_path()
    if not path.exists():
        return {}
    key = (str(path), path.stat().st_mtime)
    if _CACHE["key"] == key:
        return _CACHE["data"]

    latest = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sector = (row.get("sector") or "").strip()
            if sector and (sector not in latest or (row.get("run_date") or "") >= (latest[sector].get("run_date") or "")):
                latest[sector] = row

    data = {}
    for sector, row in latest.items():
        side = "new" if (row.get("decision") or "").strip() == "promoted" else "old"
        ev = {
            "accuracy": _num(row, f"{side}_accuracy"),
            "macro_f1": _num(row, f"{side}_macro_f1"),
            "nonhold_share": _num(row, f"{side}_nonhold_share"),
            "baseline_accuracy": _num(row, "baseline_accuracy"),
            "baseline_macro_f1": _num(row, "baseline_macro_f1"),
            "holdout_rows": int(_num(row, "holdout_rows") or 0),
            "holdout_start": (row.get("holdout_start") or "").strip(),
            "run_date": (row.get("run_date") or "").strip(),
        }
        if None not in (ev["accuracy"], ev["nonhold_share"], ev["baseline_accuracy"]):
            data[sector] = ev
    _CACHE.update(key=key, data=data)
    return data


def for_sector(sector, path=None):
    return load_evidence(path).get(sector)


def _pct(x):
    return f"{x * 100:.0f}%"


def assess(ev):
    """Verdict for one sector's evidence dict (or None when there is none)."""
    if not ev:
        return {
            "level": "unknown", "label": "Unverified",
            "headline": "No test results are available for this sector's model.",
            "caveat": "Treat this signal as an experiment, not a recommendation.",
            "evidence": None,
        }

    acc, base = ev["accuracy"], ev["baseline_accuracy"]
    rows, start = ev["holdout_rows"], ev["holdout_start"] or "the holdout start"
    window = f"{rows:,} test samples since {start}" if rows else f"the holdout since {start}"
    evidence = {k: ev[k] for k in ("accuracy", "baseline_accuracy", "macro_f1", "baseline_macro_f1",
                                   "nonhold_share", "holdout_rows", "holdout_start", "run_date")}

    if ev["nonhold_share"] < NO_EDGE_BELOW:
        level, label = "no_edge", "No edge"
        headline = "This model almost always says Hold, so a Hold from it carries no information."
        caveat = (f"Over {window} it predicted Hold {(1 - ev['nonhold_share']) * 100:.1f}% of the time, "
                  f"so it scored {_pct(acc)} accuracy, the same as always guessing Hold ({_pct(base)}).")
    elif acc < base + EDGE_MARGIN:
        level, label = "unproven", "Unproven"
        headline = "This model does not beat always guessing Hold."
        caveat = (f"It does call Buy and Sell, but over {window} it was right {_pct(acc)} of the time, "
                  f"against {_pct(base)} for always guessing Hold. Treat the signal as an experiment.")
    else:
        level, label = "tested", "Some edge"
        headline = "This model beat always guessing Hold on its test window."
        caveat = (f"Over {window} it was right {_pct(acc)} of the time, against {_pct(base)} for always "
                  f"guessing Hold. One short window is not proof, and this is not financial advice.")
    return {"level": level, "label": label, "headline": headline, "caveat": caveat, "evidence": evidence}
