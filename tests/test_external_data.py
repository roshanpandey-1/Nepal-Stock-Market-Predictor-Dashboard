"""Parsers for external data (Merolagani fundamentals, ShareSansar listings),
tested against trimmed copies of the real pages in tests/fixtures."""
from pathlib import Path

from ml.scraper import announcements as A
from ml.scraper import fundamentals as F

FIX = Path(__file__).parent / "fixtures"


def test_parse_merolagani_company():
    d = F.parse_company((FIX / "merolagani_company.html").read_text(encoding="utf-8"))
    assert d["sector"] == "Commercial Banks"
    assert d["eps"] == 33.89 and d["eps_period"] == {"fiscal_year": "083-084", "quarter": 1}
    assert d["pe"] == 16.26 and d["book_value"] == 233.90 and d["pbv"] == 2.36
    assert d["cash_dividend_pct"] == 10.80 and d["cash_dividend_fy"] == "082-083"
    assert d["bonus_pct"] == 5.00 and d["bonus_fy"] == "082-083"
    assert d["market_cap"] == 156538256143.50 and d["shares_outstanding"] == 284098468.50
    assert (d["week52_high"], d["week52_low"]) == (581.0, 485.0)
    assert d["dividend_history"][:2] == [{"fiscal_year": "082-083", "value_pct": 10.8},
                                         {"fiscal_year": "081-082", "value_pct": 12.5}]
    assert d["bonus_history"] == []


def test_parse_company_without_table():
    assert F.parse_company("<html><body>Not found</body></html>") is None


def test_parse_sharesansar_listing():
    items, nxt = A.parse_listing((FIX / "sharesansar_listing.html").read_text(encoding="utf-8"))
    assert len(items) == 4
    assert items[0]["date"] == "2026-11-02" and items[-1]["date"] == "2026-11-01"
    assert items[0]["url"].startswith("https://www.sharesansar.com/announcementdetail/")
    assert items[2]["title"] == "Bonus Shares of Super Madi Hydropower Limited Listed on NEPSE"
    assert nxt.startswith("?cursor=")


def test_categories():
    c = lambda t: A.categorise(t)["category"]
    assert c("Excel Development Bank Limited has posted a net profit of Rs 4 million and published its 1st quarter company analysis") == "quarterly_result"
    assert c("Guardian Micro Life Insurance Limited has announced its SGM going to be held on 3rd Mangsir") == "agm"
    assert c("Bonus Shares of Super Madi Hydropower Limited Listed on NEPSE") == "listing"
    assert c("Nabil Bank proposes 10.8% cash dividend") == "dividend"
    assert c("XYZ Limited book closure for 5% bonus share") == "book_closure"
    assert c("ABC Limited to issue 1:1 right share") == "right_share"
    assert c("Him Parbat Hydropower Limited is closing its IPO shares") == "ipo"
    assert c("Citizens Super 30 Mutual Fund Net Assets Value (NAV) till Ashwin") == "nav"
    assert c("PM calls high level meeting") == "other"
    assert c("NEPSE Index Plummets by 32.65 Points, All Index Close at Red") == "market"
    assert c("Top 10 Companies Based on Highest Volume of Today's Trading Session") == "market"
    assert c("NEPSE issues a circular on margin lending") == "regulation"


def test_ticker_matching():
    names = {"EDBL": "Excel Development Bank Ltd.", "GMLI": "Guardian Micro Life Insurance Limited",
             "NABIL": "Nabil Bank Limited", "NBL": "Nepal Bank Limited"}
    idx = A.build_name_index(names)
    assert A.match_ticker("Excel Development Bank Limited has posted a net profit", idx) == "EDBL"
    assert A.match_ticker("Guardian Micro Life Insurance Limited has announced its SGM", idx) == "GMLI"
    assert A.match_ticker("Nepal Bank Limited has posted ...", idx) == "NBL"
    assert A.match_ticker("Profit of Nabil Bank Limited rises", idx) is None          # announcements: start only
    assert A.match_ticker("Profit of Nabil Bank Limited rises", idx, anywhere=True) == "NABIL"


def test_ticker_matching_tolerates_wording_and_spelling():
    names = {"CFCL": "Central Finance Co. Ltd.", "SIFC": "Shree Investment Finance Co. Ltd.",
             "JBBL": "Jyoti Bikas Bank Limited", "ACLBSL": "Aarambha Chautari Laghubitta Bittiya Sanstha Limited",
             "MAKAR": "Makar Jitumaya Suri Hydropower Limited", "MFIL": "Manjushree Finance Ltd."}
    idx = A.build_name_index(names)
    m = lambda t, **k: A.match_ticker(t, idx, **k)
    assert m("Central Finance Limited has posted a net profit of Rs 20.94 million") == "CFCL"
    assert m("Shree Investment and Finance Company Limited has posted a net profit") == "SIFC"
    assert m("Jyoti Bikash Bank Limited has posted a net profit") == "JBBL"        # Bikash / Bikas
    assert m("Makar Jitumaya Suri Hydropower Company Limited has posted") == "MAKAR"
    assert m("Aarambha Chautari Laghubitta Decides Not To Distribute Dividend", anywhere=True) == "ACLBSL"
    assert m("Manjushree Finance Limited has posted") == "MFIL"
    assert m("Shree Finance Limited has posted") is None                           # not confused with a different company
    assert m("Guheswori Merchant Banking & Finance Limited has posted") is None    # untracked company
    assert A.match_ticker("Profit of Jyoti Bikash Bank Limited rises", idx, anywhere=True) is None


def test_unrelated_news_is_dropped_but_announcements_stay():
    names = {"NABIL": "Nabil Bank Limited"}
    idx = A.build_name_index(names)
    raw = lambda t: {"title": t, "url": t, "date": "2026-11-02"}
    news = A.enrich([raw("Vivo Launches V80 in Nepal"), raw("Gold Price Rises by Rs. 2300 Per Tola"),
                     raw("NEPSE Index Plummets by 32.65 Points"), raw("Nabil Bank gets award")], "news", idx, "t")
    assert [n["title"] for n in news] == ["NEPSE Index Plummets by 32.65 Points", "Nabil Bank gets award"]
    foreign = A.enrich([raw("India's Largest IPO: Jio Platforms Shares Surge 21% on Listing"),
                        raw("Anthropic's IPO Could Become World's Largest IPO"),
                        raw("SEBON Introduces 6 Stage Classification for 117 Pending IPO Applications"),
                        raw("Him Parbat Hydropower Limited Closing 4,22,500 Units IPO Today")], "news", idx, "t")
    assert [n["title"][:9] for n in foreign] == ["SEBON Int", "Him Parba"]
    ann = A.enrich([raw("Some Unlisted Company has published a notice")], "announcement", idx, "t")
    assert len(ann) == 1


def test_reclassify_applies_new_rules_to_stored_items():
    idx = A.build_name_index({"NABIL": "Nabil Bank Limited"})
    old = [{"title": "Vivo Launches V80", "kind": "news", "ticker": None, "category": "other", "url": "1"},
           {"title": "Nabil Bank Limited has posted a net profit and 1st quarter company analysis", "kind": "announcement",
            "ticker": None, "category": "other", "url": "2"}]
    out = A.reclassify(old, idx)
    assert len(out) == 1 and out[0]["ticker"] == "NABIL" and out[0]["category"] == "quarterly_result"


def test_merge_dedupes_and_expires():
    old = [{"url": "a", "date": "2026-01-01", "title": "old"}, {"url": "b", "date": "2026-10-30", "title": "b1"}]
    new = [{"url": "b", "date": "2026-10-30", "title": "b2"}, {"url": "c", "date": "2026-11-02", "title": "c"}]
    out = A.merge(old, new, keep_days=120, today="2026-11-02")
    assert [i["url"] for i in out] == ["c", "b"] and out[1]["title"] == "b2"


# ----------------------------------------------------------------- loader + pages
import json
from datetime import datetime, timedelta, timezone

from ml.analysis import external


def _write_external(tmp_path, fetched_at=None):
    ext = tmp_path / "external"
    ext.mkdir(parents=True)
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    (ext / "fundamentals.json").write_text(json.dumps({
        "source": "Merolagani", "source_note": "note", "companies": {
            "NABIL": {"eps": 33.89, "pe": 16.26, "book_value": 233.9, "pbv": 2.36, "cash_dividend_pct": 10.8,
                      "eps_period": {"fiscal_year": "083-084", "quarter": 1}, "fetched_at": fetched_at,
                      "url": "https://merolagani.com/CompanyDetail.aspx?symbol=NABIL"},
            "LOSS": {"eps": -4.0, "book_value": 80.0, "fetched_at": fetched_at}}}))
    (ext / "announcements.json").write_text(json.dumps({"source": "ShareSansar", "updated_at": fetched_at, "items": [
        {"title": "Nabil Bank Limited has posted a net profit", "url": "https://www.sharesansar.com/u1", "date": "2026-11-02", "kind": "announcement",
         "ticker": "NABIL", "category": "quarterly_result", "category_label": "Quarterly result", "source": "ShareSansar"},
        {"title": "Market news", "url": "https://www.sharesansar.com/u2", "date": "2026-11-01", "kind": "news", "ticker": None,
         "category": "other", "category_label": "Other", "source": "ShareSansar"}]}))
    return tmp_path


def test_company_fundamentals_and_recomputed_ratios(tmp_path):
    d = _write_external(tmp_path)
    f = external.company_fundamentals("nabil", d, price=549.2)
    assert f["eps"] == 33.89 and f["source"] == "Merolagani" and f["stale"] is False
    assert f["pe_at_close"] == round(549.2 / 33.89, 2) and f["pbv_at_close"] == round(549.2 / 233.9, 2)
    assert external.company_fundamentals("LOSS", d, price=100)["pe_at_close"] is None    # no P/E for a loss
    assert external.company_fundamentals("NOPE", d) is None


def test_old_fundamentals_flagged_stale(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(timespec="seconds")
    d = _write_external(tmp_path, fetched_at=old)
    assert external.company_fundamentals("NABIL", d)["stale"] is True


def test_announcement_filters(tmp_path):
    d = _write_external(tmp_path)
    assert external.announcements(d, ticker="nabil")["count"] == 1
    assert external.announcements(d, kind="news")["items"][0]["url"] == "https://www.sharesansar.com/u2"
    assert external.announcements(d, category="quarterly_result")["count"] == 1
    assert external.announcements(d, query="NABIL")["count"] == 1
    assert external.announcements(d, since="2026-11-02")["count"] == 1
    assert ("quarterly_result", "Quarterly result", 1) in external.categories(d)


def test_missing_files_are_empty_not_errors(tmp_path):
    assert external.company_fundamentals("NABIL", tmp_path) is None
    assert external.announcements(tmp_path)["items"] == []


def test_pages_render_with_external_data(tmp_path, monkeypatch):
    """News page and the stock page panels render real items (guards template bugs)."""
    import shutil
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    d = _write_external(tmp_path / "data")
    (d / "processed").mkdir()
    shutil.copy(Path("deploy_data/processed/NABIL_features.csv"), d / "processed")
    from app import create_app
    from app.backend import routes
    monkeypatch.setattr(routes, "DATA_DIR", d)
    monkeypatch.setattr(routes, "PROCESSED_DIR", d / "processed")
    monkeypatch.setattr(routes, "_live_quote_safe", lambda t: None)
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    html = c.get("/news").get_data(as_text=True)
    assert "Nabil Bank Limited has posted a net profit" in html and "Quarterly result" in html
    assert "Market news" not in c.get("/news?kind=announcement").get_data(as_text=True)
    page = c.get("/stock/NABIL").get_data(as_text=True)
    assert "Reported fundamentals" in page and "33.89" in page and "FY 083-084" in page
    assert "Nabil Bank Limited has posted a net profit" in page


def test_dividend_history_collapses_duplicate_years():
    h = [{"fiscal_year": "079-080", "value_pct": 11.0}, {"fiscal_year": "079-080", "value_pct": 0.0},
         {"fiscal_year": "078-079", "value_pct": 0.0}, {"fiscal_year": "077-078", "value_pct": 4.4}]
    out = external._collapse_years(h)
    assert out == [{"fiscal_year": "079-080", "value_pct": 11.0}, {"fiscal_year": "078-079", "value_pct": 0.0},
                   {"fiscal_year": "077-078", "value_pct": 4.4}]


def test_unsafe_links_are_never_shown(tmp_path):
    ext = tmp_path / "external"
    ext.mkdir()
    items = [{"url": "javascript:alert(1)", "title": "bad", "date": "2026-11-01", "ticker": "NABIL"},
             {"url": " JAVASCRIPT:x", "title": "bad2", "date": "2026-11-01", "ticker": "NABIL"},
             {"url": "https://www.sharesansar.com/a", "title": "good", "date": "2026-11-01", "ticker": "NABIL"}]
    (ext / "announcements.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    out = external.announcements(tmp_path)["items"]
    assert [i["title"] for i in out] == ["good"]
    assert external.safe_url("data:text/html,x") is None and external.safe_url("https://x.y/z") == "https://x.y/z"


def test_listing_parser_keeps_only_sharesansar_links():
    html = """<div class="featured-news-list"><a href="javascript:alert(1)"><h4>Evil</h4></a></div>
              <div class="featured-news-list"><a href="https://evil.example/x-2026-11-01"><h4>Elsewhere</h4></a></div>
              <div class="featured-news-list"><a href="/announcementdetail/ok-2026-11-01"><h4>Relative ok</h4></a></div>"""
    items, _ = A.parse_listing(html)
    assert [i["title"] for i in items] == ["Relative ok"]
    assert items[0]["url"] == "https://www.sharesansar.com/announcementdetail/ok-2026-11-01"
