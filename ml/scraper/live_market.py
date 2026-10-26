"""
Live NEPSE market data.

Wraps NepseUnofficialApi (https://github.com/basic-bgnr/NepseUnofficialApi),
which implements NEPSE's token handshake against https://www.nepalstock.com.
NEPSE's JSON endpoints are not officially public and reject plain requests
without that handshake, so this is the piece that makes live data possible
at all.

Design constraints this module is built around:

1. **NEPSE may be unreachable.** Render's servers sit outside Nepal and
   nepalstock.com has a history of being slow or blocked from foreign IPs.
   Every function here degrades to "unavailable" instead of raising, so the
   dashboard renders identically whether or not live data is flowing.
2. **Never block a web request indefinitely.** The underlying library uses
   `requests` without timeouts, so calls run under a hard deadline in a
   worker thread. A hung NEPSE cannot tie up a gunicorn worker.
3. **Never hammer NEPSE.** A TTL cache means one fetch serves every visitor,
   and a circuit breaker stops retrying after repeated failures (important
   if the host is geo-blocked — otherwise every cache miss pays the full
   timeout).
4. **Live data is display-only.** These values are intraday and must not be
   fed to the Buy/Sell/Hold models, which were trained on completed daily
   candles. See README "Known limitation".
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# --- tunables ---------------------------------------------------------------
FETCH_TIMEOUT_SECONDS = 12      # hard deadline for most single NEPSE calls
# getLiveMarket returns every traded scrip (~330 rows) in one response --
# much heavier than the other endpoints, which are a handful of rows each.
# It was sharing the same 12s deadline and would intermittently time out
# under that budget (especially on Render's free tier), silently dropping
# every per-ticker live quote, Top Turnover and live breadth for that
# fetch cycle while the small getNepseIndex call kept succeeding -- which
# is why the navbar index could look live while a stock page still showed
# a stale end-of-day quote.
LIVE_MARKET_TIMEOUT_SECONDS = 30
CACHE_TTL_SECONDS = 60          # serve cached data for this long
CIRCUIT_FAILURE_THRESHOLD = 3   # consecutive failures before tripping
CIRCUIT_COOLDOWN_SECONDS = 600  # stop trying for this long once tripped

_client = None
_client_lock = threading.Lock()
# One worker per endpoint fetch_live_snapshot() makes (7), so all of them
# run concurrently instead of one slow call pushing the rest out serially.
_executor = ThreadPoolExecutor(max_workers=7, thread_name_prefix="nepse-live")

_cache = {"data": None, "ts": 0.0}
_circuit = {"failures": 0, "open_until": 0.0}
_last_error = {"kind": None, "detail": None}


def _parse_nepse_time(value):
    """Parse NEPSE's market-status "asOf" time, with or without fractional seconds.

    NEPSE now sends e.g. "2026-10-26T14:32:20.500719". NepseUnofficialApi parses it
    with "%Y-%m-%dT%H:%M:%S", which raises "ValueError: unconverted data remains"
    on the first request of each new day. That broke every call that needs a POST
    payload id -- getDailyNepseIndexGraph, so the dashboard's intraday chart
    disappeared -- until the server restarted.
    """
    text = str(value).strip().replace("Z", "")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.strptime(text.split(".")[0], "%Y-%m-%dT%H:%M:%S")


def _patch_nepse_time_parsing(manager_cls):
    """Make the library's dummy-id manager accept fractional seconds (see above)."""
    if hasattr(manager_cls, "convertToDateTime"):
        manager_cls.convertToDateTime = lambda self, date_time_str: _parse_nepse_time(date_time_str)


def _get_client():
    """Create the NEPSE client lazily.

    Never constructed at import time: if the library or the network is
    unavailable, importing this module (and therefore booting the Flask app)
    must still succeed.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        from nepse import Nepse  # imported lazily on purpose
        try:
            from nepse import DummyIDUtils
            _patch_nepse_time_parsing(DummyIDUtils._DummyIDManager)
        except Exception:  # pragma: no cover - other library versions
            logger.debug("NEPSE dummy-id time parser not patched; continuing")
        client = Nepse()
        # NEPSE's certificate chain is frequently misconfigured. The library
        # exposes this switch for that reason; it is scoped to this client
        # only and affects no other HTTP in the app.
        try:
            client.setTLSVerification(False)
        except Exception:  # pragma: no cover - older/newer lib versions
            logger.debug("setTLSVerification unavailable; continuing")
        _client = client
        return _client


def _circuit_open():
    return time.time() < _circuit["open_until"]


def _record_failure():
    _circuit["failures"] += 1
    if _circuit["failures"] >= CIRCUIT_FAILURE_THRESHOLD:
        _circuit["open_until"] = time.time() + CIRCUIT_COOLDOWN_SECONDS
        logger.warning(
            "NEPSE live data unreachable %d times; pausing for %ds",
            _circuit["failures"], CIRCUIT_COOLDOWN_SECONDS,
        )


def _record_success():
    _circuit["failures"] = 0
    _circuit["open_until"] = 0.0
    _last_error.update(kind=None, detail=None)


def _call(method_name, timeout=FETCH_TIMEOUT_SECONDS):
    """Call one client method under a hard deadline. Returns None on any failure."""
    if _circuit_open():
        return None
    try:
        future = _executor.submit(lambda: getattr(_get_client(), method_name)())
        result = future.result(timeout=timeout)
        _record_success()
        return result
    except FutureTimeout:
        logger.warning("NEPSE %s timed out after %ss", method_name, timeout)
        _last_error.update(kind="timeout", detail=f"{method_name} timed out")
        _record_failure()
    except ImportError as exc:
        # The wrong `nepse` package is installed. PyPI's `nepse` and
        # NepseUnofficialApi share an import name but have different APIs --
        # worth saying so explicitly rather than blaming the network.
        logger.warning("NEPSE client import failed: %s", exc)
        _last_error.update(kind="library", detail=str(exc))
        _record_failure()
    except Exception as exc:
        logger.warning("NEPSE %s failed: %s: %s", method_name, type(exc).__name__, exc)
        _last_error.update(kind="network", detail=f"{type(exc).__name__}: {exc}")
        _record_failure()
    return None


def _call_all(specs):
    """Call several client methods concurrently instead of one after another.

    `specs` is a list of (method_name, timeout) pairs. Every call is
    submitted to the executor up front, so a slow endpoint (getLiveMarket,
    with its ~330-row response) does not delay the others from starting --
    the old sequential version effectively summed every call's timeout in
    the worst case. Returns {method_name: result_or_None}, and records one
    success/failure against the circuit breaker for the whole batch (a
    partial fetch -- e.g. the index but not live quotes -- still counts as
    NEPSE being reachable).
    """
    if _circuit_open():
        return {name: None for name, _ in specs}

    futures = {
        name: _executor.submit(lambda n=name: getattr(_get_client(), n)())
        for name, _timeout in specs
    }
    results = {}
    any_success = False
    for name, timeout in specs:
        try:
            results[name] = futures[name].result(timeout=timeout)
            any_success = True
        except FutureTimeout:
            logger.warning("NEPSE %s timed out after %ss", name, timeout)
            _last_error.update(kind="timeout", detail=f"{name} timed out")
            results[name] = None
        except ImportError as exc:
            logger.warning("NEPSE client import failed: %s", exc)
            _last_error.update(kind="library", detail=str(exc))
            results[name] = None
        except Exception as exc:
            logger.warning("NEPSE %s failed: %s: %s", name, type(exc).__name__, exc)
            _last_error.update(kind="network", detail=f"{type(exc).__name__}: {exc}")
            results[name] = None

    if any_success:
        _record_success()
    else:
        _record_failure()
    return results


def _failure_reason():
    """Human-readable explanation of the most recent failure."""
    kind = _last_error["kind"]
    if kind == "library":
        return ("Live data needs NepseUnofficialApi "
                "(pip install git+https://github.com/basic-bgnr/NepseUnofficialApi) -- "
                "the PyPI `nepse` package has a different API")
    if kind == "timeout":
        return "NEPSE did not respond in time"
    if kind == "network":
        return "Could not reach NEPSE (it may block requests from outside Nepal)"
    return "Live data unavailable"


def _num(value):
    """Coerce to float, tolerating None/''/str -- NEPSE's JSON is inconsistent."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value):
    """Percent-change value rounded to 3 decimals (NEPSE sometimes sends
    unrounded floats like 5.850681981); None passes through."""
    n = _num(value)
    return None if n is None else round(n, 3)


def _pick(row, *keys):
    """First present, non-empty value among `keys` (field names vary by endpoint)."""
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _normalise_mover(row):
    """Flatten one live-market / top-mover row into the shape our UI expects.

    Field names differ between endpoints, which is why each value is looked
    up across several candidates:
      getTopGainers/Losers -> symbol, ltp, pointChange, percentageChange, securityName
      getLiveMarket        -> symbol, lastTradedPrice, percentageChange,
                              previousClose, totalTradeQuantity, securityName
    getLiveMarket has no pointChange, so the absolute change is derived from
    lastTradedPrice - previousClose when it's missing.
    """
    if not isinstance(row, dict):
        return None
    symbol = _pick(row, "symbol", "securitySymbol")
    ltp = _num(_pick(row, "lastTradedPrice", "ltp", "closePrice", "lastUpdatedPrice"))
    if not symbol or ltp is None:
        return None

    change = _num(_pick(row, "pointChange", "change", "schange"))
    if change is None:
        prev = _num(_pick(row, "previousClose", "cp"))
        if prev is not None:
            change = round(ltp - prev, 2)

    return {
        "ticker": str(symbol).strip().upper(),
        "name": (str(_pick(row, "securityName") or "").strip() or None),
        "ltp": round(ltp, 2),
        "change_pct": _pct(_pick(row, "percentageChange", "perChange", "percentChange")),
        "change": change,
        "volume": _num(_pick(row, "totalTradeQuantity", "totalTradedQuantity", "shareTraded")),
    }


def _normalise_index_history(rows):
    """Intraday NEPSE index series.

    getDailyNepseIndexGraph() returns [[unix_seconds, index_value], ...] --
    genuinely intraday (~one point every 30s through the trading session),
    which is what makes a ShareHub-style 1D chart possible rather than a
    one-point-per-day line.
    """
    if not isinstance(rows, list) or not rows:
        return []
    series = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        ts = _num(row[0])
        value = _num(row[1])
        if ts is None or value is None:
            continue
        series.append({"t": int(ts), "v": round(value, 2)})
    series.sort(key=lambda p: p["t"])
    return series


# NEPSE's sub-index names vs. the sector names our models are trained on.
# Only confident matches are listed -- Hotels, Trading, Others, Mutual Fund and
# the Sensitive/Float composites have no corresponding model.
_SUBINDEX_TO_MODEL_SECTOR = {
    "banking subindex": "Commercial Banks",
    "development bank index": "Development Banks",
    "finance index": "Finance",
    "hydropower index": "Hydro Power",
    "life insurance": "Life Insurance",
    "manufacturing and processing": "Manufacturing And Processing",
    "microfinance index": "Microfinance",
    "non life insurance": "Non Life Insurance",
    # Added for learning/coverage purposes. NOTE: these 4 models collapse to
    # "Hold" even more heavily than the original 8 (0 trades on the
    # chronological OOS holdout) -- see README Known Limitations. Confirmed
    # against a live payload: NEPSE returns these with an " Index" suffix.
    "hotels and tourism index": "Hotels And Tourism",
    "investment index": "Investment",
    "others index": "Others",
    "trading index": "Tradings",
}


def _normalise_subindices(rows):
    """NEPSE's sector sub-indices, live.

    Shape mirrors the main index endpoint:
      {id, index, change, perChange, currentValue}
    Each is flagged with the model sector it corresponds to (when there is
    one), so the dashboard can tie live sector moves back to the sector-wise
    Buy/Sell/Hold models.
    """
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _pick(row, "index", "indexName")
        value = _num(_pick(row, "currentValue", "close", "indexValue"))
        if not name or value is None:
            continue
        name = str(name).strip()
        out.append({
            "name": name,
            "value": round(value, 2),
            "change": _num(_pick(row, "change", "pointChange")),
            "change_pct": _pct(_pick(row, "perChange", "percentageChange")),
            "model_sector": _SUBINDEX_TO_MODEL_SECTOR.get(name.lower()),
        })
    out.sort(key=lambda r: (r["change_pct"] is None, -(r["change_pct"] or 0)))
    return out


def _live_quotes_by_symbol(rows):
    """Map symbol -> full live quote, from the getLiveMarket payload.

    getLiveMarket returns every scrip in one response, so per-ticker lookups
    reuse the snapshot we already fetch for breadth rather than calling NEPSE
    again per page view.
    """
    if not isinstance(rows, list):
        return {}
    quotes = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        mover = _normalise_mover(row)
        if not mover:
            continue
        ltp = mover["ltp"]
        prev = _num(_pick(row, "previousClose"))
        quotes[mover["ticker"]] = {
            "ticker": mover["ticker"],
            "name": mover["name"],
            "ltp": ltp,
            "change": mover["change"],
            "change_pct": mover["change_pct"],
            "open": _num(_pick(row, "openPrice")),
            "high": _num(_pick(row, "highPrice")),
            "low": _num(_pick(row, "lowPrice")),
            "prev_close": prev,
            "volume": mover["volume"],
            "turnover": _num(_pick(row, "totalTradeValue")),
            "avg_price": _num(_pick(row, "averageTradedPrice")),
            "last_qty": _num(_pick(row, "lastTradedVolume")),
        }
    return quotes


def _quotes_from_price_volume(rows):
    """Per-symbol quote map from getPriceVolume -- NEPSE's end-of-day
    price/volume summary.

    Unlike getLiveMarket (which empties out once the market closes for the
    day -- confirmed 2026-09-23: getLiveMarket returned 0 rows with the
    market closed, while getPriceVolume still returned 278), this endpoint
    keeps serving today's close, previous close, % change and volume all
    day. It has no Open/High/Low/Turnover fields, so those stay None here;
    used only to fill in tickers getLiveMarket didn't cover, never to
    override a fuller getLiveMarket row.
    """
    if not isinstance(rows, list):
        return {}
    quotes = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _pick(row, "symbol")
        ltp = _num(_pick(row, "lastTradedPrice", "closePrice"))
        if not symbol or ltp is None:
            continue
        prev = _num(_pick(row, "previousClose"))
        change = round(ltp - prev, 2) if prev is not None else None
        quotes[str(symbol).strip().upper()] = {
            "ticker": str(symbol).strip().upper(),
            "name": (str(_pick(row, "securityName") or "").strip() or None),
            "ltp": round(ltp, 2),
            "change": change,
            "change_pct": _pct(_pick(row, "percentageChange")),
            "open": None,
            "high": None,
            "low": None,
            "prev_close": prev,
            "volume": _num(_pick(row, "totalTradeQuantity")),
            "turnover": None,
            "avg_price": None,
            "last_qty": None,
        }
    return quotes


_todays_price_cache = {"rows": None, "ts": 0.0}
TODAYS_PRICE_TTL_SECONDS = 600  # day's OHLC barely changes once the market is closed


def _fetch_todays_price():
    """NEPSE's per-security "today's price" table (open/high/low/close/
    turnover) for the latest trading day, or None.

    getLiveMarket (the only feed with open/high/low/turnover) empties out when
    the market closes, and getPriceVolume carries only close/volume -- so the
    stock page's Open/High/Low/Turnover tiles went blank after hours. This
    endpoint keeps the full day's figures. It takes a business date, so walk
    back from today (Nepal time) until a day returns rows -- weekends and
    holidays have none. Cached because it only changes once per session.
    """
    now = time.time()
    if _todays_price_cache["rows"] and (now - _todays_price_cache["ts"]) < TODAYS_PRICE_TTL_SECONDS:
        return _todays_price_cache["rows"]
    if _circuit_open():
        return _todays_price_cache["rows"]

    nepal_today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=45)).date()
    for days_back in range(0, 6):
        day = (nepal_today - timedelta(days=days_back)).isoformat()
        try:
            future = _executor.submit(lambda d=day: _get_client().getPriceVolumeHistory(d))
            data = future.result(timeout=FETCH_TIMEOUT_SECONDS)
        except Exception as exc:  # timeout, network, library -- degrade quietly
            logger.warning("NEPSE getPriceVolumeHistory(%s) failed: %s: %s",
                           day, type(exc).__name__, exc)
            return _todays_price_cache["rows"]
        rows = data.get("content") if isinstance(data, dict) else data
        if isinstance(rows, list) and rows:
            _todays_price_cache.update(rows=rows, ts=now)
            return rows
    return _todays_price_cache["rows"]


def _quotes_from_todays_price(rows):
    """symbol -> {open, high, low, turnover, volume, ...} from the
    today's-price table. Field names vary a little, hence the _pick fallbacks."""
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _pick(row, "symbol", "securitySymbol")
        if not symbol:
            continue
        out[str(symbol).strip().upper()] = {
            "open": _num(_pick(row, "openPrice", "open")),
            "high": _num(_pick(row, "highPrice", "high")),
            "low": _num(_pick(row, "lowPrice", "low")),
            "ltp": _num(_pick(row, "closePrice", "lastTradedPrice", "close")),
            "prev_close": _num(_pick(row, "previousDayClosePrice", "previousClose")),
            "volume": _num(_pick(row, "totalTradedQuantity", "totalTradeQuantity")),
            "turnover": _num(_pick(row, "totalTradedValue", "totalTradeValue", "turnover")),
            "avg_price": _num(_pick(row, "averageTradedPrice")),
        }
    return out


def _live_breadth(rows):
    """Advancing / declining / unchanged across every live scrip.

    getLiveMarket returns the whole market (~333 rows), so this is the live
    counterpart to the dashboard's end-of-day breadth widget.
    """
    if not isinstance(rows, list) or not rows:
        return None
    adv = dec = unc = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        pct = _num(_pick(row, "percentageChange", "perChange"))
        if pct is None:
            continue
        if pct > 0:
            adv += 1
        elif pct < 0:
            dec += 1
        else:
            unc += 1
    if not (adv or dec or unc):
        return None
    return {"advancing": adv, "declining": dec, "unchanged": unc,
            "total": adv + dec + unc}


BREADTH_BUCKETS = ("advancing", "declining", "unchanged")


def _breadth_symbols(rows):
    """Symbols behind each breadth count, using exactly the rule _live_breadth
    uses, so a list's length always matches the number on its pill."""
    out = {b: [] for b in BREADTH_BUCKETS}
    if not isinstance(rows, list):
        return out
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        pct = _num(_pick(row, "percentageChange", "perChange"))
        symbol = _pick(row, "symbol", "securitySymbol")
        if pct is None or not symbol:
            continue
        symbol = str(symbol).strip().upper()
        if symbol in seen:
            continue
        seen.add(symbol)
        bucket = "advancing" if pct > 0 else "declining" if pct < 0 else "unchanged"
        out[bucket].append(symbol)
    return out


def _sort_breadth_rows(bucket, rows):
    """Biggest movers first; unchanged scrips by traded volume."""
    if bucket == "advancing":
        return sorted(rows, key=lambda q: -(q.get("change_pct") or 0))
    if bucket == "declining":
        return sorted(rows, key=lambda q: (q.get("change_pct") or 0))
    return sorted(rows, key=lambda q: -(q.get("volume") or 0))


def _normalise_index(payload):
    """NEPSE index -- the endpoint returns either a list of indices or a single dict."""
    row = None
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(_pick(item, "index", "indexName") or "")
            if "NEPSE" in name.upper():
                row = item
                break
        if row is None and payload and isinstance(payload[0], dict):
            row = payload[0]
    elif isinstance(payload, dict):
        row = payload
    if not row:
        return None
    value = _num(_pick(row, "currentValue", "close", "indexValue"))
    if value is None:
        return None
    return {
        "name": str(_pick(row, "index", "indexName") or "NEPSE Index"),
        "value": round(value, 2),
        "change": _num(_pick(row, "change", "pointChange")),
        "change_pct": _pct(_pick(row, "perChange", "percentageChange")),
    }


# getNepseIndex returns every index NEPSE tracks in one list -- the broad
# market indices *and* the same per-sector sub-indices that getNepseSubIndices
# also returns (and that the "Sector Indices" panel already renders further
# down the dashboard). Left unfiltered, each sector index showed up twice --
# once in the compact top strip, once in the Sector Indices panel. The strip
# is only meant for the broad, whole-market indices, so sector ones are kept
# out of it here.
_BROAD_MARKET_INDICES = {"nepse index", "sensitive index", "float index", "sensitive float index"}


def _normalise_all_indices(payload):
    """Broad market rows from getNepseIndex (NEPSE, Sensitive, Float,
    Sensitive Float) for the dashboard's compact "Indices" strip.

    getNepseIndex's payload also includes every per-sector sub-index, but
    those are deliberately excluded here -- they're already shown, once,
    in the "Sector Indices" panel (built from getNepseSubIndices).
    """
    if not isinstance(payload, list):
        return []
    out = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        name = str(_pick(row, "index", "indexName") or "Index")
        if name.strip().lower() not in _BROAD_MARKET_INDICES:
            continue
        value = _num(_pick(row, "currentValue", "close", "indexValue"))
        if value is None:
            continue
        out.append({
            "name": name,
            "value": round(value, 2),
            "change_pct": _pct(_pick(row, "perChange", "percentageChange")),
        })
    return out


def _top_turnover(quotes_by_symbol, limit=5):
    """Top scrips by live turnover, from the same getLiveMarket call already
    made for breadth/quotes -- no extra NEPSE request.
    """
    if not quotes_by_symbol:
        return []
    rows = [q for q in quotes_by_symbol.values() if q.get("turnover")]
    rows.sort(key=lambda q: q["turnover"], reverse=True)
    return rows[:limit]


def _market_open(payload):
    """Market status endpoint returns e.g. {'isOpen': 'CLOSE'|'OPEN', ...}."""
    if not isinstance(payload, dict):
        return None
    raw = _pick(payload, "isOpen", "marketStatus")
    if raw is None:
        return None
    return str(raw).strip().upper() not in ("CLOSE", "CLOSED", "FALSE")


def fetch_live_snapshot():
    """Fetch a fresh snapshot directly from NEPSE (no caching). Never raises."""
    snapshot = {
        "available": False,
        "reason": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market_open": None,
        "index": None,
        "gainers": [],
        "losers": [],
        "breadth": None,
        "index_history": [],
        "subindices": [],
        "all_indices": [],
        "top_turnover": [],
        "_quotes": {},
        "_breadth_quotes": {},
    }

    if _circuit_open():
        snapshot["reason"] = "NEPSE unreachable recently; retrying later"
        return snapshot

    results = _call_all([
        ("getMarketStatus", FETCH_TIMEOUT_SECONDS),
        ("getNepseIndex", FETCH_TIMEOUT_SECONDS),
        ("getTopGainers", FETCH_TIMEOUT_SECONDS),
        ("getTopLosers", FETCH_TIMEOUT_SECONDS),
        ("getLiveMarket", LIVE_MARKET_TIMEOUT_SECONDS),
        ("getPriceVolume", FETCH_TIMEOUT_SECONDS),
        ("getDailyNepseIndexGraph", FETCH_TIMEOUT_SECONDS),
        ("getNepseSubIndices", FETCH_TIMEOUT_SECONDS),
    ])
    status = results["getMarketStatus"]
    index = results["getNepseIndex"]
    gainers = results["getTopGainers"]
    losers = results["getTopLosers"]
    live = results["getLiveMarket"]
    price_volume = results["getPriceVolume"]
    history = results["getDailyNepseIndexGraph"]
    subindices = results["getNepseSubIndices"]

    if all(x is None for x in results.values()):
        snapshot["reason"] = _failure_reason()
        return snapshot

    snapshot["market_open"] = _market_open(status)
    snapshot["index"] = _normalise_index(index)
    snapshot["all_indices"] = _normalise_all_indices(index)
    # getLiveMarket is a genuine tick feed -- NEPSE empties it out once the
    # market closes for the day (confirmed 2026-09-23: 0 rows with the
    # market closed). getPriceVolume keeps serving today's close/volume/%
    # change/previous-close all day, so it backs up both breadth and
    # per-ticker quotes whenever getLiveMarket has nothing.
    snapshot["breadth"] = _live_breadth(live) or _live_breadth(price_volume)

    quotes = _live_quotes_by_symbol(live)
    for ticker, q in _quotes_from_price_volume(price_volume).items():
        quotes.setdefault(ticker, q)
    # After hours getLiveMarket is empty, so quotes come from getPriceVolume
    # (no open/high/low/turnover). Fill those gaps from the day's final
    # today's-price table instead of leaving the stock page's tiles blank.
    if not live:
        day_rows = _quotes_from_todays_price(_fetch_todays_price())
        for ticker, q in quotes.items():
            extra = day_rows.get(ticker)
            if not extra:
                continue
            for field in ("open", "high", "low", "turnover", "avg_price"):
                if q.get(field) is None:
                    q[field] = extra.get(field)
    snapshot["_quotes"] = quotes
    # The full quote rows behind each breadth pill (same source as the counts).
    buckets = _breadth_symbols(live if _live_breadth(live) else price_volume)
    snapshot["_breadth_quotes"] = {
        b: _sort_breadth_rows(b, [quotes[sym] for sym in syms if sym in quotes])
        for b, syms in buckets.items()
    }

    snapshot["index_history"] = _normalise_index_history(history)
    snapshot["subindices"] = _normalise_subindices(subindices)
    snapshot["top_turnover"] = _top_turnover(snapshot["_quotes"])

    for key, payload in (("gainers", gainers), ("losers", losers)):
        rows = payload if isinstance(payload, list) else []
        cleaned = [m for m in (_normalise_mover(r) for r in rows) if m]
        snapshot[key] = cleaned[:10]

    # getTopGainers/getTopLosers cover every instrument NEPSE trades,
    # including debentures/mutual funds that getLiveMarket and getPriceVolume
    # don't carry a quote for -- which used to leave clicking one of those
    # movers on a dead "Not Found" page (stock_detail()'s intended live-only
    # fallback needs a quote to render). Fold the movers themselves in as a
    # last-resort quote source so every mover shown has somewhere to land.
    for payload in (snapshot["gainers"], snapshot["losers"]):
        for mover in payload:
            snapshot["_quotes"].setdefault(mover["ticker"], {
                "ticker": mover["ticker"],
                "name": mover["name"],
                "ltp": mover["ltp"],
                "change": mover["change"],
                "change_pct": mover["change_pct"],
                "open": None,
                "high": None,
                "low": None,
                "prev_close": None,
                "volume": mover["volume"],
                "turnover": None,
                "avg_price": None,
                "last_qty": None,
            })

    snapshot["available"] = bool(
        snapshot["index"] or snapshot["gainers"] or snapshot["losers"]
        or snapshot["breadth"] or snapshot["index_history"]
        or snapshot["subindices"] or snapshot["market_open"] is not None
    )
    if not snapshot["available"]:
        snapshot["reason"] = "NEPSE returned no usable data"
    return snapshot


def get_live_snapshot(ttl=CACHE_TTL_SECONDS, force=False):
    """Cached live snapshot.

    One fetch serves every visitor for `ttl` seconds -- the same pattern the
    large NEPSE portals use, scaled down. On failure the previous snapshot is
    returned (marked stale) rather than an error, so a transient outage does
    not blank the panel.
    """
    now = time.time()
    cached = _cache["data"]
    if not force and cached is not None and (now - _cache["ts"]) < ttl:
        return cached

    fresh = fetch_live_snapshot()

    if not fresh["available"] and cached is not None and cached.get("available"):
        stale = dict(cached)
        stale["stale"] = True
        stale["reason"] = fresh["reason"]
        return stale

    fresh["stale"] = False
    _cache["data"] = fresh
    _cache["ts"] = now
    return fresh


def reset_state():
    """Clear cache and circuit breaker -- used by tests."""
    _cache["data"] = None
    _cache["ts"] = 0.0
    _circuit["failures"] = 0
    _circuit["open_until"] = 0.0


def get_live_quote(ticker):
    """Live quote for one ticker, or None if unavailable.

    Reads from the same cached snapshot the dashboard uses, so calling this
    per page view costs nothing extra.
    """
    if not ticker:
        return None
    snapshot = get_live_snapshot()
    if not snapshot.get("available"):
        return None
    quote = (snapshot.get("_quotes") or {}).get(str(ticker).strip().upper())
    if not quote:
        return None
    result = dict(quote)
    result["market_open"] = snapshot.get("market_open")
    result["stale"] = snapshot.get("stale", False)
    return result


def get_breadth_list(bucket):
    """Every scrip behind one breadth pill ("advancing" / "declining" /
    "unchanged"), with its full live quote. Read from the same cached snapshot
    as the dashboard, so it costs no extra NEPSE call. Returns None for an
    unknown bucket."""
    if bucket not in BREADTH_BUCKETS:
        return None
    snapshot = get_live_snapshot()
    rows = (snapshot.get("_breadth_quotes") or {}).get(bucket, []) if snapshot.get("available") else []
    return {
        "available": bool(snapshot.get("available")),
        "bucket": bucket,
        "market_open": snapshot.get("market_open"),
        "stale": snapshot.get("stale", False),
        "fetched_at": snapshot.get("fetched_at"),
        "count": len(rows),
        "rows": rows,
    }
