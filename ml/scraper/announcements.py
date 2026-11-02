"""Company announcements and market news headlines from ShareSansar.

ShareSansar's /announcement and /category/latest listing pages are server-
rendered and its robots.txt allows crawling. Only the headline, date and link
are stored -- never article text -- and every item links back to ShareSansar.
Items are tagged with a category by keyword rules and, where the headline
starts with (or names) a listed company we track, with its ticker.
"""
import re
import time
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urljoin

SOURCE_NAME = "ShareSansar"
SITE = "https://www.sharesansar.com"
ANNOUNCEMENTS_URL = "https://www.sharesansar.com/announcement"
NEWS_URL = "https://www.sharesansar.com/category/latest"
USER_AGENT = ("Mozilla/5.0 (compatible; NEPSE-Intelligence/1.0; educational research project; "
              "+https://github.com/roshanpandey-1/Nepal-Stock-Market-Predictor-Dashboard)")

# (key, label, pattern, note). First match wins, so the order matters.
CATEGORIES = [
    ("quarterly_result", "Quarterly result",
     r"quarter.*(net profit|net loss|company analysis|report)|(net profit|net loss).*quarter",
     "Quarterly figures are usually unaudited. Compare with the same quarter last year and with the sector before reading much into them."),
    ("book_closure", "Book closure",
     r"book clos",
     "Only shareholders on record before the book-closure date receive the announced benefit. After a bonus or right share, the price is adjusted on that date, so a mechanical drop is not a loss in value."),
    ("listing", "Listing",
     r"listed on nepse|\blisting\b|listed in nepse",
     "New shares (for example bonus shares or an IPO) start trading, increasing the number of shares available."),
    ("dividend", "Dividend / bonus",
     r"dividend|bonus share|cash bonus|stock dividend",
     "Proposed dividends and bonus shares still need approval at the company's general meeting."),
    ("right_share", "Right share",
     r"right share|rights share|right issue",
     "Existing shareholders may buy new shares at a fixed price. Not taking up rights dilutes your share of the company; the market price is adjusted after book closure."),
    ("agm", "General meeting",
     r"\b(agm|sgm)\b|general meeting",
     "Shareholders vote on items such as dividends, bonus shares, mergers and board appointments."),
    ("merger", "Merger / acquisition",
     r"merger|merge|acquisition|acquire",
     "If a listed company is involved, mergers change share swap ratios and can suspend trading for a period; check the swap ratio and dates."),
    ("ipo", "IPO / FPO / auction",
     r"\bipo\b|\bfpo\b|auction|debenture|public issue|issue of",
     "A new issue of shares or bonds; mostly relevant to people applying for it, not a signal for listed shares."),
    ("nav", "Mutual fund NAV",
     r"net assets? value|\bnav\b",
     "Net asset value of a mutual fund scheme, published monthly or weekly."),
    ("regulation", "Regulator / exchange",
     r"\bsebon\b|\bnrb\b|nepal rastra bank|\bcdsc\b|directive|circular"
     r"|\bnepse (has|issues|issued|notice|announces|to)\b",
     "Rules or notices from regulators and the exchange can affect whole sectors; read the original notice."),
    ("market", "Market update",
     r"\bnepse index\b|\ball index\b|sensitive index|\btop \d+ (companies|gainers|losers|turnover)"
     r"|trading session|market (closes|capitalization)|\bturnover\b",
     None),
]
OTHER = ("other", "Other", None, None)
_COMPILED = [(k, l, re.compile(p, re.I), n) for k, l, p, n in CATEGORIES]


def categorise(title):
    for key, label, rx, note in _COMPILED:
        if rx.search(title or ""):
            return {"category": key, "category_label": label, "note": note}
    return {"category": OTHER[0], "category_label": OTHER[1], "note": None}


def _norm(name):
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"\bltd\b\.?", "limited", s)
    s = re.sub(r"\bco\b\.?", "company", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


# Words that differ between how a company writes its own name and how our list spells it.
_GENERIC = {"limited", "company", "and", "pvt", "private", "public", "bittiya", "sanstha"}


def _core(text):
    return [w for w in _norm(text).split() if w not in _GENERIC]


def build_name_index(company_names):
    """[(core words, ticker)] longest first, for matching headlines to tickers.

    The core of a name drops generic words (Limited, Company, Bittiya Sanstha, "and"),
    so "Central Finance Limited" matches "Central Finance Co. Ltd.". Names with fewer
    than two distinctive words are skipped: too ambiguous to match on.
    """
    idx = []
    for t, n in company_names.items():
        c = _core(n)
        if len(c) >= 2:
            idx.append((c, t))
    return sorted(idx, key=lambda x: -len(x[0]))


def match_ticker(title, name_index, anywhere=False):
    """Ticker of the company a headline is about, or None.

    Announcements start with the company name (anywhere=False). News may mention it
    anywhere. Only announcements also allow one small spelling difference (for
    example Bikash / Bikas) on names of three or more words, never for news.
    """
    words = _core(title)
    for core, ticker in name_index:
        n = len(core)
        if words[:n] == core:
            return ticker
        if anywhere and any(words[i:i + n] == core for i in range(len(words) - n + 1)):
            return ticker
    if not anywhere:
        best, best_ratio = None, 0.0
        for core, ticker in name_index:
            n = len(core)
            if n < 3 or len(words) < n:
                continue
            ratio = SequenceMatcher(None, " ".join(core), " ".join(words[:n])).ratio()
            if ratio >= 0.93 and ratio > best_ratio:
                best, best_ratio = ticker, ratio
        return best
    return None


_NEPAL_CUE = re.compile(r"nepal|sebon|nepse|hydropower|\bbank\b|finance|insurance|laghubitta|\bltd\b|limited|"
                        r"mangsir|kartik|poush|ashwin|rs\.? ?\d", re.I)


def relevant(rec):
    """News is kept only when it names a tracked company or fits a market category;
    phone launches, gold prices and politics are dropped, and so are IPO/listing stories
    with no Nepal cue (foreign IPOs). Announcements always stay."""
    if rec["kind"] == "announcement" or rec["ticker"] is not None:
        return True
    if rec["category"] == "other":
        return False
    if rec["category"] in ("ipo", "listing"):
        return bool(_NEPAL_CUE.search(rec["title"]))
    return True


def reclassify(items, name_index):
    """Re-apply the current rules to stored items so rule fixes also correct history."""
    out = []
    for it in items:
        rec = dict(it, ticker=match_ticker(it["title"], name_index, anywhere=(it.get("kind") == "news")))
        rec.update(categorise(it["title"]))
        if relevant(rec):
            out.append(rec)
    return out


def parse_listing(html):
    """[{title, url, date}] from an announcement or news listing page, plus the next-page cursor URL."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    items = []
    for box in soup.select(".featured-news-list"):
        h = box.find("h4")
        a = h.find_parent("a") if h else None
        if a is None or not a.get("href"):
            continue
        date_el = box.select_one(".text-org")
        date = None
        if date_el:
            txt = " ".join(date_el.get_text(" ").split())
            for fmt in ("%A, %B %d, %Y", "%B %d, %Y"):
                try:
                    date = datetime.strptime(txt, fmt).date().isoformat()
                    break
                except ValueError:
                    continue
        if date is None:
            m = re.search(r"(\d{4}-\d{2}-\d{2})$", a["href"].rstrip("/"))
            date = m.group(1) if m else None
        url = urljoin(SITE, a["href"].strip())
        if not url.startswith(SITE + "/"):        # keep only ShareSansar's own pages
            continue
        items.append({"title": " ".join(h.get_text(" ").split()), "url": url, "date": date})
    nxt = soup.find("a", rel="next")
    return items, (nxt.get("href") if nxt else None)


def fetch_listing(base_url, session, since, max_pages=60, pause=3.0, timeout=30):
    """Items newer than or equal to `since` (ISO date), following the cursor. Never raises."""
    out, url, errors = [], base_url, []
    for _ in range(max_pages):
        try:
            r = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                errors.append(f"HTTP {r.status_code} for {url}")
                break
            items, nxt = parse_listing(r.text)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            break
        if not items:
            break
        out.extend(i for i in items if i["date"] and i["date"] >= since)
        if not nxt or min((i["date"] or "9999") for i in items) < since:
            break
        url = base_url + nxt if nxt.startswith("?") else nxt
        time.sleep(pause)
    return out, errors


def enrich(items, kind, name_index, fetched_at):
    out = []
    for it in items:
        rec = dict(it, kind=kind, source=SOURCE_NAME, fetched_at=fetched_at,
                   ticker=match_ticker(it["title"], name_index, anywhere=(kind == "news")))
        rec.update(categorise(it["title"]))
        if relevant(rec):
            out.append(rec)
    return out


def merge(existing, new, keep_days, today):
    """Union by URL (new wins), newest first, dropping items older than keep_days."""
    from datetime import date, timedelta

    cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    by_url = {i["url"]: i for i in existing}
    for i in new:
        by_url[i["url"]] = i
    kept = [i for i in by_url.values() if (i.get("date") or "") >= cutoff]
    return sorted(kept, key=lambda i: (i.get("date") or "", i.get("fetched_at") or ""), reverse=True)
