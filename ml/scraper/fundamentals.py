"""Company fundamentals from Merolagani's public company pages.

Merolagani (merolagani.com) shows each listed company's latest reported EPS
(with the fiscal year and quarter it comes from), P/E, book value per share,
price-to-book, cash dividend and bonus history and market capitalisation in
server-rendered HTML. This module only parses that page; it never computes or
estimates a financial figure. Values are stored exactly as published, together
with the source URL and the time they were collected, and the site labels them
"as reported by Merolagani". It is an unofficial source: figures come from the
companies' (usually unaudited) quarterly reports and can lag or contain errors.

Run weekly by scripts/fetch_fundamentals.py (GitHub Actions), slowly.
"""
import re
import time

SOURCE_NAME = "Merolagani"
URL = "https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
USER_AGENT = ("Mozilla/5.0 (compatible; NEPSE-Intelligence/1.0; educational research project; "
              "+https://github.com/roshanpandey-1/Nepal-Stock-Market-Predictor-Dashboard)")

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")
_FY = re.compile(r"FY\s*:?\s*(\d{3}-\d{3})", re.I)
_Q = re.compile(r"Q\s*:?\s*(\d)", re.I)


def _number(text):
    if not text:
        return None
    m = _NUM.search(text.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _period(text):
    fy, q = _FY.search(text or ""), _Q.search(text or "")
    return {"fiscal_year": fy.group(1) if fy else None, "quarter": int(q.group(1)) if q else None}


def parse_company(html):
    """Fields from a CompanyDetail page, or None if the page has no data table."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="accordion")
    if table is None:
        return None
    raw = {}
    for tr in table.find_all("tr"):
        th, td = tr.find("th", recursive=False), tr.find("td", recursive=False)
        if th is None or td is None:
            continue
        label = " ".join(th.get_text(" ").split()).rstrip(":").strip()
        if label and label not in raw:
            raw[label] = " ".join(td.get_text(" ").split())

    def history(panel_id):
        rows = []
        panel = table.find(id=panel_id)
        if panel is None:
            return rows
        for tr in panel.find_all("tr"):
            cells = [" ".join(td.get_text(" ").split()) for td in tr.find_all("td")]
            if len(cells) < 3:
                continue
            value = next((_number(c) for c in cells[1:] if "%" in c or re.fullmatch(r"[\d.,]+", c)), None)
            fy = next((_period(c)["fiscal_year"] for c in cells[1:] if _FY.search(c)), None)
            if value is not None and fy:
                rows.append({"fiscal_year": fy, "value_pct": value})
        return rows

    eps_text = raw.get("EPS", "")
    div_text, bonus_text = raw.get("% Dividend", ""), raw.get("% Bonus", "")
    hi_lo = raw.get("52 Weeks High - Low", "")
    hl = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", hi_lo)][:2]
    out = {
        "sector": raw.get("Sector") or None,
        "shares_outstanding": _number(raw.get("Shares Outstanding")),
        "market_price": _number(raw.get("Market Price")),
        "eps": _number(eps_text.split("(")[0]) if eps_text else None,
        "eps_period": _period(eps_text),
        "pe": _number(raw.get("P/E Ratio")),
        "book_value": _number(raw.get("Book Value")),
        "pbv": _number(raw.get("PBV")),
        "cash_dividend_pct": _number(div_text.split("(")[0]) if div_text else None,
        "cash_dividend_fy": _period(div_text)["fiscal_year"],
        "bonus_pct": _number(bonus_text.split("(")[0]) if bonus_text else None,
        "bonus_fy": _period(bonus_text)["fiscal_year"],
        "market_cap": _number(raw.get("Market Capitalization")),
        "week52_high": hl[0] if len(hl) == 2 else None,
        "week52_low": hl[1] if len(hl) == 2 else None,
        "dividend_history": history("dividend-panel"),
        "bonus_history": history("bonus-panel"),
    }
    if all(out[k] is None for k in ("eps", "pe", "book_value", "market_cap")):
        return None
    return out


def fetch_company(symbol, session, timeout=30, retries=2, pause=5.0):
    """(fields, error) for one symbol. Never raises."""
    url = URL.format(symbol=symbol)
    err = None
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                data = parse_company(r.text)
                return (data, None) if data else (None, "no data table on page")
            err = f"HTTP {r.status_code}"
            if r.status_code in (403, 429):
                time.sleep(pause * 6)
        except Exception as exc:  # network errors, parser errors
            err = f"{type(exc).__name__}: {exc}"
        time.sleep(pause * (attempt + 1))
    return None, err
