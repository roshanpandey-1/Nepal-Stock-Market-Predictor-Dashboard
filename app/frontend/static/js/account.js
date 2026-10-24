// Watchlist + portfolio pages and the "Watch" button on stock pages.
// Everything here talks to the logged-in /api/me/* endpoints. Public pages
// never load this code's data paths unless the visitor is signed in.

const _csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
const _signedIn = () => (document.querySelector('meta[name="signed-in"]') || {}).content === "1";

async function acctApi(path, { method = "GET", body } = {}) {
  const opts = { method, headers: { "X-CSRF-Token": _csrf() }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
  if (res.status === 401) {
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
    throw new Error("Not signed in");
  }
  if (!res.ok || data.ok === false) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

const _esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Nepali-style digit grouping (12,34,567.00), the way Meroshare / TMS show it.
const _rs = (v, d = 2) => v == null || isNaN(v) ? "—"
  : Number(v).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const _signCls = (v) => v == null || v === 0 ? "" : v > 0 ? "pos" : "neg";
const _signed = (v, d = 2) => v == null ? "—" : `${v > 0 ? "+" : ""}${_rs(v, d)}`;
const _signedPct = (v) => v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`;

// --- model signal badges (lazy, one request per symbol) -----------------------
const _signalCache = {};
async function _loadSignal(ticker) {
  if (!(ticker in _signalCache)) {
    _signalCache[ticker] = fetch(`/api/signal/${encodeURIComponent(ticker)}`)
      .then(r => r.json()).catch(() => ({ signal: null }));
  }
  return _signalCache[ticker];
}
async function _fillSignals(root) {
  const cells = root.querySelectorAll("[data-signal-for]");
  await Promise.all([...cells].map(async (el) => {
    const d = await _loadSignal(el.dataset.signalFor);
    if (!d || !d.signal) { el.innerHTML = `<span class="text-dim">—</span>`; return; }
    const rel = d.reliability || null;
    const tip = rel ? _esc(`${rel.label}: ${rel.headline} ${rel.caveat}`) : `Confidence ${(d.confidence * 100).toFixed(0)}%`;
    // A model that says Hold almost every day gives no information, so show "No signal", not a Hold badge.
    if (rel && rel.level === "no_edge") { el.innerHTML = `<span class="text-dim rel-none" title="${tip}">No signal</span>`; return; }
    const cls = { Buy: "badge-buy", Sell: "badge-sell", Hold: "badge-hold" }[d.signal] || "badge-hold";
    const flag = rel && rel.level !== "tested" ? ` <span class="rel-q" title="${tip}">?</span>` : "";
    el.innerHTML = `<span class="badge-pill sm ${cls}" title="${tip}">${_esc(d.signal)}</span>${flag}`;
  }));
}

// Symbol pickers on the watchlist and portfolio pages reuse the navbar's
// autocomplete (attachTickerSearch in charts.js) instead of a <datalist>,
// which dumped every ticker at once.
function _wirePicker(inputId, boxId, onPick) {
  const input = document.getElementById(inputId), box = document.getElementById(boxId);
  if (input && box && window.attachTickerSearch) attachTickerSearch(input, box, { onPick });
}

// The picker field may hold "NABIL" or a typed company name; resolve to a symbol.
async function _resolveSymbol(text) {
  const v = String(text || "").trim();
  if (!v) return "";
  if (window._loadTickerIndex) {
    await _loadTickerIndex();
    const best = _matchTickers(v)[0];
    if (best && (best.t.toLowerCase() === v.toLowerCase() || !/^[A-Za-z0-9]{1,15}$/.test(v))) return best.t;
  }
  return v.toUpperCase();
}

// --- watch button on stock pages --------------------------------------------------
async function initWatchButton() {
  const btn = document.getElementById("watch-btn");
  if (!btn) return;
  const ticker = btn.dataset.ticker;
  const paint = (on) => {
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.textContent = on ? "★ Watching" : "☆ Watch";
  };
  let watching = false;
  if (_signedIn()) {
    try { watching = (await acctApi(`/api/me/watchlist/status/${encodeURIComponent(ticker)}`)).watching; } catch (e) { /* keep default */ }
  }
  paint(watching);
  btn.addEventListener("click", async () => {
    if (!_signedIn()) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    btn.disabled = true;
    try {
      const d = watching
        ? await acctApi(`/api/me/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" })
        : await acctApi("/api/me/watchlist", { method: "POST", body: { ticker } });
      watching = d.watching;
      paint(watching);
    } catch (e) {
      btn.title = e.message;
    } finally {
      btn.disabled = false;
    }
  });
}

// --- watchlist page ---------------------------------------------------------------
async function initWatchlistPage() {
  const body = document.getElementById("watchlist-body");
  if (!body) return;
  const msg = document.getElementById("watch-add-msg");
  _wirePicker("watch-add-input", "watch-add-results", (row) => {
    const input = document.getElementById("watch-add-input");
    input.value = row.t;
    document.getElementById("watch-add-form").requestSubmit();
  });

  async function load() {
    try {
      const { items } = await acctApi("/api/me/watchlist");
      if (!items.length) {
        body.innerHTML = `<p class="text-dim mb-0">Nothing here yet. Add a symbol above, or press <strong>☆ Watch</strong> on any stock page.</p>`;
        return;
      }
      body.innerHTML = `<div class="table-responsive"><table class="data-table">
        <thead><tr><th>Symbol</th><th>Company</th><th>Sector</th><th class="num">LTP</th><th class="num">Change</th><th>Signal</th><th></th></tr></thead>
        <tbody>${items.map(r => `<tr>
          <td><a href="/stock/${encodeURIComponent(r.ticker)}">${_esc(r.ticker)}</a></td>
          <td>${_esc(r.name)}</td>
          <td class="text-dim">${_esc(r.sector || "—")}</td>
          <td class="num">${_rs(r.ltp)}</td>
          <td class="num ${_signCls(r.change_pct)}">${r.change_pct == null ? "—" : `${_signed(r.change)} (${_signedPct(r.change_pct)})`}</td>
          <td data-signal-for="${_esc(r.ticker)}"><span class="text-dim">…</span></td>
          <td class="num"><button class="btn-x" data-remove="${_esc(r.ticker)}" title="Remove ${_esc(r.ticker)}" aria-label="Remove ${_esc(r.ticker)}">✕</button></td>
        </tr>`).join("")}</tbody></table></div>`;
      _fillSignals(body);
    } catch (e) {
      body.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
    }
  }

  body.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b) return;
    b.disabled = true;
    try {
      await acctApi(`/api/me/watchlist/${encodeURIComponent(b.dataset.remove)}`, { method: "DELETE" });
      await load();
    } catch (err) { msg.textContent = err.message; msg.className = "form-msg error"; b.disabled = false; }
  });

  document.getElementById("watch-add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("watch-add-input");
    const ticker = await _resolveSymbol(input.value);
    if (!ticker) return;
    msg.textContent = ""; msg.className = "form-msg";
    try {
      await acctApi("/api/me/watchlist", { method: "POST", body: { ticker } });
      input.value = "";
      msg.textContent = `${ticker} added.`; msg.className = "form-msg ok";
      await load();
    } catch (err) { msg.textContent = err.message; msg.className = "form-msg error"; }
  });

  load();
}

// --- portfolio page -------------------------------------------------------------------
let _sectorChart = null;
const _SECTOR_COLORS = ["#2f6fdb", "#16a34a", "#d97706", "#dc2626", "#8b5cf6", "#0891b2", "#db2777",
                        "#65a30d", "#ea580c", "#475569", "#0d9488", "#a16207", "#6366f1"];

let _pfMarketOpen = null;
function _renderPortfolio(d) {
  const t = d.totals;
  _pfMarketOpen = d.market_open;
  const setTile = (id, text, cls) => {
    const el = document.getElementById(id);
    el.textContent = text;
    el.className = "value " + (cls || "");
  };
  setTile("pf-value", `Rs ${_rs(t.value_ltp)}`);
  const dayEl = document.getElementById("pf-day");
  dayEl.innerHTML = `${_esc(_signed(t.day_pl))}${t.day_pct == null ? "" : ` <small>(${_esc(_signedPct(t.day_pct))})</small>`}`;
  dayEl.className = "value " + _signCls(t.day_pl);
  // After the close it is still today's move (LTP vs previous close), so say which session it is.
  document.getElementById("pf-day-label").textContent =
    d.market_open === false ? "Change (last session)" : "Today's change";
  setTile("pf-count", String(t.count));
  document.getElementById("pf-source").textContent = d.market_open === true
    ? `market open · live · ${new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kathmandu" })}`
    : d.market_open === false ? "market closed" : "last close";

  const wrap = document.getElementById("holdings-wrap");
  if (!d.holdings.length) {
    wrap.innerHTML = `<p class="text-dim mb-0">No holdings yet. Use <strong>+ Add holding</strong> to add a scrip and its quantity.</p>`;
  } else {
    wrap.innerHTML = `<table class="data-table holdings-table">
      <thead><tr><th>#</th><th>Scrip</th><th class="num">Balance</th>
        <th class="num">Last closing price</th><th class="num">Value at last close</th><th class="num">LTP</th><th class="num">Value at LTP</th>
        <th class="num">Today</th><th>Signal</th><th></th></tr></thead>
      <tbody>${d.holdings.map((r, i) => `<tr>
        <td class="text-dim">${i + 1}</td>
        <td><a href="/stock/${encodeURIComponent(r.ticker)}" title="${_esc(r.name)}">${_esc(r.ticker)}</a>
            ${r.priced ? "" : `<span class="text-dim" title="No price available for this scrip">*</span>`}</td>
        <td class="num">${r.quantity.toLocaleString("en-IN")}</td>
        <td class="num">${_rs(r.lcp)}</td>
        <td class="num">${_rs(r.value_lcp)}</td>
        <td class="num">${_rs(r.ltp)}</td>
        <td class="num">${_rs(r.value_ltp)}</td>
        <td class="num ${_signCls(r.day_pl)}">${_signed(r.day_pl)}</td>
        <td data-signal-for="${_esc(r.ticker)}"><span class="text-dim">…</span></td>
        <td class="num text-nowrap">
          <button class="btn-link-sm" data-edit="${_esc(r.ticker)}" data-qty="${r.quantity}">Edit</button>
          <button class="btn-x" data-del="${_esc(r.ticker)}" title="Remove ${_esc(r.ticker)}" aria-label="Remove ${_esc(r.ticker)}">✕</button>
        </td>
      </tr>`).join("")}</tbody>
      <tfoot><tr>
        <td></td><td><strong>Total</strong></td><td></td><td></td>
        <td class="num"><strong>${_rs(t.value_lcp)}</strong></td><td></td>
        <td class="num"><strong>${_rs(t.value_ltp)}</strong></td>
        <td class="num ${_signCls(t.day_pl)}"><strong>${_signed(t.day_pl)}</strong></td><td></td><td></td>
      </tr></tfoot></table>`;
    _fillSignals(wrap);
  }

  // sector doughnut + legend
  const legend = document.getElementById("sector-legend");
  const canvas = document.getElementById("sector-chart");
  if (_sectorChart) { _sectorChart.destroy(); _sectorChart = null; }
  if (!d.sectors.length) {
    legend.innerHTML = `<span class="text-dim">Add a holding to see your sector mix.</span>`;
    canvas.style.display = "none";
  } else {
    canvas.style.display = "";
    legend.innerHTML = d.sectors.map((s, i) => `<div class="legend-row">
      <span class="dot" style="background:${_SECTOR_COLORS[i % _SECTOR_COLORS.length]}"></span>
      <span class="grow">${_esc(s.sector)}</span><span class="num">${s.share_pct}%</span></div>`).join("");
    if (window.Chart) {
      _sectorChart = new Chart(canvas, {
        type: "doughnut",
        data: {
          labels: d.sectors.map(s => s.sector),
          datasets: [{ data: d.sectors.map(s => s.value),
                       backgroundColor: d.sectors.map((_, i) => _SECTOR_COLORS[i % _SECTOR_COLORS.length]),
                       borderWidth: 0 }],
        },
        options: { plugins: { legend: { display: false },
                              tooltip: { callbacks: { label: (c) => ` ${c.label}: Rs ${_rs(c.parsed)}` } } },
                   cutout: "62%" },
      });
    }
  }

}

async function initPortfolioPage() {
  const wrap = document.getElementById("holdings-wrap");
  if (!wrap) return;
  _wirePicker("tx-ticker", "tx-ticker-results", (row) => {
    const f = document.getElementById("tx-form");
    f.ticker.value = row.t;
    f.quantity.focus();
  });

  async function load() {
    try {
      _renderPortfolio(await acctApi("/api/me/portfolio"));
      // holdings changed: refresh the other tabs next time they're shown (or now, if visible)
      if (_fcData) { _fcData = null; if (!document.getElementById("pf-forecast").hidden) _loadForecastTab(); }
      if (_ideasLoaded) { _ideasLoaded = false; if (!document.getElementById("pf-ideas").hidden) _loadIdeasTab(); }
    } catch (e) {
      wrap.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
    }
  }

  const modalEl = document.getElementById("tx-modal");
  const form = document.getElementById("tx-form");
  const msg = document.getElementById("tx-msg");
  const modal = () => bootstrap.Modal.getOrCreateInstance(modalEl);
  function openModal(prefill = {}) {
    msg.textContent = ""; msg.className = "form-msg";
    form.ticker.value = prefill.ticker || "";
    form.quantity.value = prefill.quantity || "";
    document.getElementById("tx-modal-title").textContent = prefill.quantity ? `Edit ${prefill.ticker}` : "Add holding";
    // focus once Bootstrap has finished showing the dialog (it moves focus itself on "shown")
    modalEl.addEventListener("shown.bs.modal", () => (prefill.ticker ? form.quantity : form.ticker).focus(), { once: true });
    modal().show();
  }
  document.getElementById("open-tx-modal").addEventListener("click", () => openModal());

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = ""; msg.className = "form-msg";
    const fd = new FormData(form);
    const btn = document.getElementById("tx-submit");
    btn.disabled = true;
    try {
      await acctApi("/api/me/holdings", { method: "POST", body: {
        ticker: await _resolveSymbol(fd.get("ticker")), quantity: fd.get("quantity"),
      } });
      form.quantity.value = ""; form.ticker.value = "";
      modal().hide();
      await load();
    } catch (err) {
      msg.textContent = err.message; msg.className = "form-msg error";
    } finally {
      btn.disabled = false;
      // a disabled button drops focus to <body>, where Esc no longer closes the dialog
      if (document.activeElement === document.body) modalEl.focus();
    }
  });

  wrap.addEventListener("click", async (e) => {
    const ed = e.target.closest("[data-edit]");
    if (ed) { openModal({ ticker: ed.dataset.edit, quantity: ed.dataset.qty }); return; }
    const b = e.target.closest("[data-del]");
    if (!b || !confirm(`Remove ${b.dataset.del} from your portfolio?`)) return;
    b.disabled = true;
    try {
      await acctApi(`/api/me/holdings/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" });
      await load();
    } catch (err) { alert(err.message); b.disabled = false; }
  });

  const add = new URLSearchParams(location.search).get("add");
  _initPortfolioTabs();
  await load();

  // While the market is open, re-value holdings every 60s (the server's live
  // snapshot refreshes about once a minute). Paused while the tab is hidden
  // or the edit dialog is open, and caught up as soon as the page is visible.
  const REFRESH_MS = 60000;
  let lastLoad = Date.now();
  const refresh = async () => {
    if (document.hidden || modalEl.classList.contains("show")) return;
    if (_pfMarketOpen !== true) return;
    lastLoad = Date.now();
    await load();
  };
  setInterval(refresh, REFRESH_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - lastLoad > REFRESH_MS) refresh();
  });
  if (add) openModal({ ticker: add.toUpperCase() });
}

// --- portfolio tabs: Holdings / Forecast / Ideas ------------------------------------
let _fcData = null, _fcRangeChart = null, _fcPathChart = null;
const _todayISO = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kathmandu" });

function _renderForecastRange(items) {
  const box = document.getElementById("fc-range-box");
  const canvas = document.getElementById("fc-range-chart");
  if (_fcRangeChart) { _fcRangeChart.destroy(); _fcRangeChart = null; }
  if (!window.Chart || !items.length) return;
  box.style.height = `${Math.max(_isPhone() ? 200 : 300, items.length * 34 + 70)}px`;
  const c = CHART_COLORS;
  _fcRangeChart = new Chart(canvas, {
    data: {
      labels: items.map(i => i.ticker),
      datasets: [
        { type: "bar", label: "Likely range", data: items.map(i => [i.lower_pct, i.upper_pct]),
          backgroundColor: items.map(i => i.change_pct >= 0 ? "rgba(22,163,74,0.22)" : "rgba(220,38,38,0.22)"),
          borderColor: items.map(i => i.change_pct >= 0 ? c.green : c.red), borderWidth: 1,
          borderRadius: 4, borderSkipped: false, barThickness: 16 },
        { type: "line", label: "Forecast", data: items.map(i => i.change_pct), showLine: false,
          pointStyle: "rectRot", pointRadius: 6, pointHoverRadius: 7,
          pointBackgroundColor: items.map(i => i.change_pct >= 0 ? c.green : c.red), pointBorderColor: c.bg },
      ],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: (ctx) => {
            const it = items[ctx.dataIndex];
            return ctx.datasetIndex === 0
              ? `Range ${_signedPct(it.lower_pct)} to ${_signedPct(it.upper_pct)}`
              : `Forecast ${_signedPct(it.change_pct)} (Rs ${_rs(it.forecast_price)})`;
          } } },
      },
      scales: {
        x: { ticks: { callback: (v) => `${v > 0 ? "+" : ""}${v}%` },
             grid: { color: (g) => (g.tick && g.tick.value === 0 ? c.text : c.grid) } },
        y: { grid: { display: false } },
      },
    },
  });
}

function _renderForecastPath(item) {
  const canvas = document.getElementById("fc-path-chart");
  const meta = document.getElementById("fc-path-meta");
  if (_fcPathChart) { _fcPathChart.destroy(); _fcPathChart = null; }
  if (!item) { meta.innerHTML = ""; return; }
  const today = _todayISO();
  const path = (item.path || []).filter(p => p.date >= today);
  meta.innerHTML = `<strong>${_esc(item.ticker)}</strong> · ${item.quantity.toLocaleString("en-IN")} shares ·
    now Rs ${_rs(item.ltp)} → <span class="${_signCls(item.change_pct)}">Rs ${_rs(item.forecast_price)} (${_signedPct(item.change_pct)})</span>
    <span class="text-dim">· projected value Rs ${_rs(item.value_forecast)}</span>`;
  if (!window.Chart || !path.length) return;
  const c = CHART_COLORS;
  const labels = ["Now", ...path.map(p => _shortDay(p.date))];
  const up = item.change_pct >= 0;
  const line = up ? c.green : c.red;
  _fcPathChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Upper", data: [item.ltp, ...path.map(p => p.hi)], borderWidth: 0, pointRadius: 0,
          fill: "+1", backgroundColor: up ? "rgba(22,163,74,0.12)" : "rgba(220,38,38,0.12)", tension: 0.35 },
        { label: "Lower", data: [item.ltp, ...path.map(p => p.lo)], borderWidth: 0, pointRadius: 0, fill: false, tension: 0.35 },
        { label: "Forecast", data: [item.ltp, ...path.map(p => p.p)], borderColor: line, borderWidth: 2,
          pointRadius: 0, pointHoverRadius: 4, tension: 0.35, fill: false },
        { label: "Today's price", data: labels.map(() => item.ltp), borderColor: c.text, borderWidth: 1,
          borderDash: [5, 4], pointRadius: 0, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { filter: (t) => t.datasetIndex !== 3,
                   callbacks: { label: (t) => `${t.dataset.label}: Rs ${_rs(t.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: _isPhone() ? 4 : 7, maxRotation: 0 } },
        y: { position: "right", ticks: { maxTicksLimit: 5 } },
      },
    },
  });
}

function _shortDay(iso) {
  const d = new Date(iso + "T00:00:00Z");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

function _renderForecastTab(d) {
  const t = d.totals;
  const set = (id, html, cls) => { const el = document.getElementById(id); el.innerHTML = html; el.className = "value " + (cls || ""); };
  const table = document.getElementById("fc-table");
  const foot = document.getElementById("fc-foot");
  if (!d.items.length) {
    ["fc-now", "fc-proj", "fc-chg", "fc-range"].forEach(id => set(id, "—"));
    table.innerHTML = `<p class="text-dim mb-0">${d.missing.length ? "None of your holdings have a forecast yet." : "Add a holding to see its forecast."}</p>`;
    foot.textContent = "";
    _renderForecastRange([]); _renderForecastPath(null);
    document.getElementById("fc-pick").innerHTML = "";
    return;
  }
  set("fc-now", `Rs ${_rs(t.value_now, 0)}`);
  set("fc-proj", `Rs ${_rs(t.value_forecast, 0)}`, _signCls(t.value_change));
  set("fc-chg", `${_signed(t.value_change, 0)} <small>(${_signedPct(t.change_pct)})</small>`, _signCls(t.value_change));
  set("fc-range", `Rs ${_rs(t.value_low, 0)} – ${_rs(t.value_high, 0)}`);

  table.innerHTML = `<table class="data-table fc-table">
    <thead><tr><th>Scrip</th><th class="num">Qty</th><th class="num">LTP</th><th class="num">30-day forecast</th>
      <th class="num">Expected</th><th class="num">Likely range</th><th class="num">Value now</th><th class="num">Projected value</th><th class="num">Change</th></tr></thead>
    <tbody>${d.items.map(r => `<tr data-fc="${_esc(r.ticker)}" tabindex="0" title="Show ${_esc(r.ticker)} on the chart">
      <td><a href="/stock/${encodeURIComponent(r.ticker)}">${_esc(r.ticker)}</a>${r.rescaled ? ` <span class="text-dim" title="Price moved 20%+ since the forecast ran; see note below">*</span>` : ""}</td>
      <td class="num">${r.quantity.toLocaleString("en-IN")}</td>
      <td class="num">${_rs(r.ltp)}</td>
      <td class="num">${_rs(r.forecast_price)}</td>
      <td class="num ${_signCls(r.change_pct)}">${_signedPct(r.change_pct)}</td>
      <td class="num text-dim">${_rs(r.lower_bound)} – ${_rs(r.upper_bound)}</td>
      <td class="num">${_rs(r.value_now)}</td>
      <td class="num">${_rs(r.value_forecast)}</td>
      <td class="num ${_signCls(r.value_change)}">${_signed(r.value_change)}</td>
    </tr>`).join("")}</tbody>
    <tfoot><tr><td><strong>Total</strong></td><td></td><td></td><td></td>
      <td class="num ${_signCls(t.change_pct)}"><strong>${_signedPct(t.change_pct)}</strong></td><td></td>
      <td class="num"><strong>${_rs(t.value_now)}</strong></td><td class="num"><strong>${_rs(t.value_forecast)}</strong></td>
      <td class="num ${_signCls(t.value_change)}"><strong>${_signed(t.value_change)}</strong></td></tr></tfoot></table>`;

  const wide = d.items.filter(i => i.band_pct >= 40).map(i => i.ticker);
  const rescaled = d.items.filter(i => i.rescaled).map(i => i.ticker);
  foot.innerHTML = [
    d.generated_at ? `Prophet forecasts generated ${_esc(d.generated_at)}, compared with today's price.` : "",
    "The range total adds up each stock's own range, so the true portfolio range is narrower.",
    wide.length ? `Very wide ranges (40%+ of the price), so treat these with extra caution: ${wide.map(_esc).join(", ")}.` : "",
    rescaled.length ? `The price has moved more than 20% since the forecast ran, so its expected move is applied to today's price: ${rescaled.map(_esc).join(", ")}.` : "",
    d.missing.length ? `No forecast yet for: ${d.missing.map(_esc).join(", ")}.` : "",
  ].filter(Boolean).join(" ");

  _renderForecastRange(d.items);
  const pick = document.getElementById("fc-pick");
  const keep = pick.value;
  pick.innerHTML = d.items.map(i => `<option value="${_esc(i.ticker)}">${_esc(i.ticker)} (${_signedPct(i.change_pct)})</option>`).join("");
  if (d.items.some(i => i.ticker === keep)) pick.value = keep;
  _renderForecastPath(d.items.find(i => i.ticker === pick.value) || d.items[0]);
}

async function _loadForecastTab(force) {
  if (_fcData && !force) return;
  const table = document.getElementById("fc-table");
  try {
    _fcData = await acctApi("/api/me/portfolio/forecast");
    _renderForecastTab(_fcData);
  } catch (e) {
    table.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
  }
}

let _ideasLoaded = false;
async function _loadIdeasTab(force) {
  if (_ideasLoaded && !force) return;
  const list = document.getElementById("ideas-list");
  const basis = document.getElementById("ideas-basis");
  try {
    const d = await acctApi("/api/me/recommendations?limit=6");
    _ideasLoaded = true;
    basis.textContent = d.basis === "personal"
      ? "Picked from the sectors of the stocks you hold and search for. Stocks you already hold, searched or watch are left out."
      : "Add holdings or search for a few stocks to get ideas from your sectors. For now these are picked across the whole market.";
    if (!d.items.length) {
      list.innerHTML = `<p class="text-dim mb-0">No ideas right now: nothing in your sectors has both a positive forecast and positive recent momentum.</p>`;
      return;
    }
    list.innerHTML = d.items.map(r => `<article class="idea-card">
      <div class="idea-top">
        <a class="idea-sym" href="/stock/${encodeURIComponent(r.ticker)}">${_esc(r.ticker)}</a>
        <span class="ts-tag ${r.forecast_pct >= 0 ? "pos" : "neg"}" title="30-day forecast">${_signedPct(r.forecast_pct)}</span>
      </div>
      <div class="idea-name">${_esc(r.name)}</div>
      <div class="text-dim idea-sector">${_esc(r.sector || "")} · Rs ${_rs(r.close)}</div>
      <ul class="idea-why">${r.reasons.map(x => `<li>${_esc(x)}</li>`).join("")}</ul>
      <div class="idea-actions">
        <a class="btn-ghost-sm" href="/stock/${encodeURIComponent(r.ticker)}">View</a>
        <button class="btn-ghost-sm" type="button" data-watch-idea="${_esc(r.ticker)}">☆ Watch</button>
      </div>
    </article>`).join("");
  } catch (e) {
    list.innerHTML = `<p class="text-dim mb-0">${_esc(e.message)}</p>`;
  }
}

function _initPortfolioTabs() {
  const tabs = [...document.querySelectorAll(".pf-tabs [role=tab]")];
  if (!tabs.length) return;
  function show(name, focus) {
    tabs.forEach(t => {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      if (on && focus) t.focus();
    });
    if (name === "forecast") _loadForecastTab();
    if (name === "ideas") _loadIdeasTab();
    if (history.replaceState) history.replaceState(null, "", name === "holdings" ? location.pathname + location.search : `#${name}`);
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t.dataset.tab));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      show(n.dataset.tab, true);
    });
  });
  document.getElementById("fc-pick").addEventListener("change", (e) => {
    _renderForecastPath((_fcData?.items || []).find(i => i.ticker === e.target.value));
  });
  document.getElementById("fc-table").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-fc]");
    if (!tr || e.target.closest("a")) return;
    const pick = document.getElementById("fc-pick");
    pick.value = tr.dataset.fc;
    pick.dispatchEvent(new Event("change"));
    document.getElementById("fc-path-chart").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  document.getElementById("ideas-list").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-watch-idea]");
    if (!b) return;
    b.disabled = true;
    try {
      await acctApi("/api/me/watchlist", { method: "POST", body: { ticker: b.dataset.watchIdea } });
      b.textContent = "★ Watching";
    } catch (err) { b.title = err.message; b.disabled = false; }
  });
  const fromHash = () => {
    const h = (location.hash || "").slice(1);
    if (["holdings", "forecast", "ideas"].includes(h)) show(h);
  };
  window.addEventListener("hashchange", fromHash);   // e.g. "See why" in the search box while on this page
  fromHash();
}

/* ---- Sign-up / password forms: show-hide toggle, live confirm check, email suggestions ---- */
(function () {
  function addToggle(input) {
    if (input.closest('.pw-wrap')) return;
    var wrap = document.createElement('span');
    wrap.className = 'pw-wrap';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pw-toggle';
    btn.textContent = 'Show';
    btn.setAttribute('aria-label', 'Show password');
    btn.setAttribute('aria-pressed', 'false');
    btn.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Hide' : 'Show';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      btn.setAttribute('aria-pressed', show ? 'true' : 'false');
    });
    wrap.appendChild(btn);
    // never leave a password visible after the form is sent
    if (input.form) input.form.addEventListener('submit', function () {
      input.type = 'password'; btn.textContent = 'Show'; btn.setAttribute('aria-pressed', 'false');
    });
  }

  function wireConfirm(form) {
    var confirm = form.querySelector('input[name=confirm]');
    var pw = form.querySelector('input[name=password], input[name=new_password]');
    if (!confirm || !pw) return;
    var msg = form.querySelector('[data-confirm-msg]');
    if (!msg) {
      msg = document.createElement('small');
      msg.className = 'field-error';
      msg.setAttribute('data-confirm-msg', '');
      msg.textContent = "Passwords don't match.";
      msg.hidden = true;
      confirm.closest('label').appendChild(msg);
    }
    function check() {
      var bad = confirm.value !== '' && confirm.value !== pw.value;
      confirm.classList.toggle('invalid', bad);
      confirm.setAttribute('aria-invalid', bad ? 'true' : 'false');
      msg.hidden = !bad;
    }
    confirm.addEventListener('input', check);
    pw.addEventListener('input', check);
  }

  function init() {
    document.querySelectorAll('input[type=password]').forEach(addToggle);
    document.querySelectorAll('form').forEach(wireConfirm);
    document.querySelectorAll('.suggest-chip').forEach(function (b) {
      b.addEventListener('click', function () {
        var email = document.querySelector('input[name=email]');
        if (!email) return;
        email.value = b.getAttribute('data-email');
        email.classList.remove('invalid');
        var err = email.parentNode.querySelector('.field-error');
        if (err) err.remove();
        email.focus();
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
