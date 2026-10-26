// Shared Chart.js helpers for the NEPSE Intelligence dashboard.
// Chart colors are read live from the page's CSS custom properties (see
// :root / :root[data-theme="dark"] / the prefers-color-scheme block in
// main.css) so charts stay readable across the light/dark/system toggle.

function _computeChartColors() {
  const cs = getComputedStyle(document.documentElement);
  const get = (name, fallback) => {
    const v = cs.getPropertyValue(name);
    return v && v.trim() ? v.trim() : fallback;
  };
  const red = get("--red", "#ef4444");
  return {
    accent: get("--accent", "#1d6fd6"),
    green: get("--green", "#22c55e"),
    red: red,
    redFillTransparent: _hexToRgba(red, 0.15),
    amber: get("--amber", "#f5a623"),
    grid: get("--border", "rgba(11,46,79,0.08)"),
    text: get("--text-dim", "#6b7686"),
    bg: get("--card-bg", "#ffffff"),
  };
}

function _hexToRgba(hex, alpha) {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!m) return `rgba(239,68,68,${alpha})`; // fallback: --red default
  const [r, g, b] = [m[1], m[2], m[3]].map(h => parseInt(h, 16));
  return `rgba(${r},${g},${b},${alpha})`;
}

function _isDarkTheme() {
  const t = _currentTheme();
  if (t === "dark") return true;
  if (t === "light") return false;
  return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
}

// Mutated in place (never reassigned) so every chart config/plugin that
// closed over this object picks up new colors automatically on theme change.
const CHART_COLORS = _computeChartColors();

function _applyChartTheme() {
  Object.assign(CHART_COLORS, _computeChartColors());
  Chart.defaults.color = CHART_COLORS.text;
  Chart.defaults.borderColor = CHART_COLORS.grid;
}

_applyChartTheme();
Chart.defaults.font.family = "Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

// --- Theme toggle (Light / Dark / System) ---------------------------------
// Baked-in Chart.js dataset colors (borderColor/backgroundColor strings)
// don't update themselves when CHART_COLORS changes -- only a fresh
// new Chart(...) picks up the new values. So each render*Chart function
// below registers a "redraw with current data" closure here, and switching
// themes replays whichever charts are currently on the page.
// Phone-width check used to thin out axis labels so they stop overlapping.
function _shortDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return iso;
  return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+m[2] - 1] + " " + m[1].slice(2);
}
function _isPhone() { return window.matchMedia("(max-width: 640px)").matches; }
// Crossing the phone/desktop breakpoint (rotating a phone, resizing a window)
// rebuilds the charts so tick density and legend placement match the new width.
try {
  window.matchMedia("(max-width: 640px)").addEventListener("change", () => {
    try { _redrawForTheme(); } catch (e) {}
    try { _renderForecastChart(); } catch (e) {}
  });
} catch (e) {}

const _themeRedraws = {};
function _registerThemeRedraw(key, fn) { _themeRedraws[key] = fn; }

function _currentTheme() {
  try { return localStorage.getItem("nepse-theme") || "system"; } catch (e) { return "system"; }
}

function _updateThemeToggleUI(theme) {
  const wrap = document.getElementById("theme-toggle");
  if (!wrap) return;
  wrap.querySelectorAll("button").forEach(b => {
    b.classList.toggle("active", b.dataset.themeChoice === theme);
  });
}

function _redrawForTheme() {
  _applyChartTheme();
  Object.values(_themeRedraws).forEach(fn => {
    try { fn(); } catch (e) { console.error("Theme redraw failed", e); }
  });
}

function setTheme(theme) {
  try { localStorage.setItem("nepse-theme", theme); } catch (e) { /* private mode, etc. */ }
  document.documentElement.setAttribute("data-theme", theme);
  _updateThemeToggleUI(theme);
  _redrawForTheme();
}

function wireThemeToggle() {
  const wrap = document.getElementById("theme-toggle");
  if (!wrap) return;
  _updateThemeToggleUI(_currentTheme());
  wrap.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => setTheme(btn.dataset.themeChoice));
  });
  // "System" stays live-synced to the OS setting while the tab is open.
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => { if (_currentTheme() === "system") _redrawForTheme(); };
    if (mq.addEventListener) mq.addEventListener("change", handler);
    else if (mq.addListener) mq.addListener(handler); // older Safari
  }
}

wireThemeToggle();

let _backtestChartInstance = null;

function renderBacktestChart(canvasId, rows) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !rows || !rows.length) return;

  if (_backtestChartInstance) {
    _backtestChartInstance.destroy();
  }
  _backtestChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: rows.map(r => r.sector),
      datasets: [
        {
          label: "ML Strategy Return %",
          data: rows.map(r => r.ml_return_pct),
          backgroundColor: CHART_COLORS.accent,
          borderRadius: 4,
        },
        {
          label: "Buy & Hold Return %",
          data: rows.map(r => r.bnh_return_pct),
          backgroundColor: CHART_COLORS.amber,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "top" } },
      scales: {
        x: { ticks: { autoSkip: false, maxRotation: _isPhone() ? 60 : 30, minRotation: _isPhone() ? 60 : 30, font: { size: _isPhone() ? 10 : 12 } } },
        y: { title: { display: true, text: "Return (%)" } },
      },
    },
  });
  _registerThemeRedraw("backtest", () => renderBacktestChart(canvasId, rows));
}

let _priceChartInstance = null;
let _priceChartFullHistory = [];

// ShareHub-style crosshair: a dashed vertical + horizontal line through the
// hovered point, plus a small value badge on the y-axis. Chart.js has no
// built-in crosshair, so this is a small custom plugin rather than pulling
// in an extra dependency.
const _pointY = (p) => (p !== null && typeof p === "object" ? p.y : p);

const crosshairPlugin = {
  id: "crosshair",
  afterDraw(chart) {
    const active = chart.getActiveElements();
    if (!active || !active.length) return;
    const { ctx, chartArea } = chart;
    const point = active[0].element;
    const x = point.x;
    const y = point.y;

    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = CHART_COLORS.text;
    ctx.lineWidth = 1;

    // vertical line
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();

    // horizontal line
    ctx.beginPath();
    ctx.moveTo(chartArea.left, y);
    ctx.lineTo(chartArea.right, y);
    ctx.stroke();
    ctx.restore();

    // y-axis value badge
    const yScale = chart.scales.y;
    if (yScale) {
      const value = yScale.getValueForPixel(y);
      const label = Number.isFinite(value) ? value.toFixed(2) : "";
      ctx.save();
      ctx.setLineDash([]);
      const isDown = point.$context && point.$context.dataIndex > 0 &&
        _pointY(chart.data.datasets[0].data[point.$context.dataIndex]) <
        _pointY(chart.data.datasets[0].data[point.$context.dataIndex - 1]);
      ctx.fillStyle = isDown ? CHART_COLORS.red : CHART_COLORS.green;
      const textWidth = ctx.measureText(label).width + 12;
      ctx.fillRect(chartArea.right, y - 9, textWidth, 18);
      ctx.fillStyle = "#fff";
      ctx.font = "11px -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
      ctx.textBaseline = "middle";
      ctx.fillText(label, chartArea.right + 6, y);
      ctx.restore();
    }
  },
};

function renderPriceChart(canvasId, history) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !history || !history.length) return;

  // NOTE: do NOT reassign _priceChartFullHistory here. This function is called
  // with an already-sliced subset (e.g. the last 5 rows for "1W"), and it used
  // to overwrite the full history with that slice -- so clicking 1W and then
  // 1M would slice(-30) off only 5 remaining rows and silently keep showing
  // the 1W chart until a full page reload restored the full history.
  // _priceChartFullHistory is the single source of truth and is only ever
  // set once, in loadStockDetail() after the /api/forecast fetch.

  if (_priceChartInstance) {
    _priceChartInstance.destroy();
  }
  _priceChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: history.map(h => h.date),
      datasets: [{
        label: "Close Price",
        data: history.map(h => h.close),
        borderColor: CHART_COLORS.accent,
        backgroundColor: "rgba(29,111,214,0.06)",
        fill: true,
        tension: 0.15,
        pointRadius: 0,
        pointHitRadius: 12,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 44 } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title(items) {
              const h = history[items[0].dataIndex];
              return h ? h.date : "";
            },
            label(item) {
              const h = history[item.dataIndex];
              const vol = h && h.volume != null ? h.volume.toLocaleString() : "—";
              return [`Price  Rs. ${item.parsed.y.toFixed(2)}`, `Vol  ${vol}`];
            },
          },
        },
      },
      scales: {
        x: { ticks: { maxTicksLimit: _isPhone() ? 4 : 10, maxRotation: 0,
                      // "2026-03-25" -> "Mar 26" on phones so labels don't collide
                      callback: function (v) { const l = this.getLabelForValue(v); return _isPhone() ? _shortDate(l) : l; } } },
        y: { title: { display: !_isPhone(), text: "Price (NPR)" } },
      },
    },
    plugins: [crosshairPlugin],
  });
  _registerThemeRedraw("price", () => renderPriceChart(canvasId, history));
}

function applyPricePeriod(days) {
  const slice = days > 0 ? _priceChartFullHistory.slice(-days) : _priceChartFullHistory;
  renderPriceChart("price-chart", slice);
}

function wirePeriodToggle() {
  const wrap = document.getElementById("period-toggle");
  if (!wrap) return;
  wrap.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      wrap.querySelectorAll("button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      applyPricePeriod(parseInt(btn.dataset.days, 10));
    });
  });
}

function setSignalBadge(signalData) {
  const badge = document.getElementById("signal-badge");
  const conf = document.getElementById("signal-confidence");
  if (!badge) return;

  if (!signalData || signalData.error) {
    badge.innerHTML = `<span class="text-dim">Unavailable</span>`;
    if (conf) conf.textContent = signalData && signalData.error ? signalData.error : "";
    return;
  }

  const cls = { Buy: "badge-buy", Sell: "badge-sell", Hold: "badge-hold" }[signalData.signal] || "badge-hold";
  const rel = signalData.reliability || null;
  const level = rel ? rel.level : "unknown";
  // A Hold from a model that says Hold almost every day is not a real call, so it is shown muted.
  const muted = level === "no_edge" ? " is-muted" : "";
  badge.innerHTML = `<span class="badge-pill ${cls}${muted}">${_escapeHTML(signalData.signal)}</span>` +
    (rel ? ` <span class="rel-chip lvl-${_escapeHTML(level)}" title="${_escapeHTML(rel.caveat)}">${_escapeHTML(rel.label)}</span>` : "");
  if (conf) {
    const p = signalData.probabilities || {};
    const probs = ["Sell", "Hold", "Buy"].filter(k => k in p).map(k => `${k} ${(p[k] * 100).toFixed(0)}%`).join(" · ");
    conf.innerHTML =
      (probs ? `<div>Model probabilities: ${_escapeHTML(probs)}</div>` : "") +
      (rel ? `<div class="rel-text lvl-${_escapeHTML(level)}"><strong>${_escapeHTML(rel.headline)}</strong> ${_escapeHTML(rel.caveat)}</div>` : "");
  }
}

async function loadStockDetail(ticker) {
  wirePeriodToggle();

  try {
    const histResp = await fetch(`/api/forecast/${ticker}`);
    const histData = await histResp.json();
    // initial render honors whichever period button starts active (default 6M)
    const activeBtn = document.querySelector("#period-toggle button.active");
    const days = activeBtn ? parseInt(activeBtn.dataset.days, 10) : 0;
    _priceChartFullHistory = histData.history || [];
    applyPricePeriod(days);
  } catch (e) {
    console.error("Failed to load price history", e);
  }

  try {
    const sigResp = await fetch(`/api/signal/${ticker}`);
    const sigData = await sigResp.json();
    setSignalBadge(sigData);
  } catch (e) {
    console.error("Failed to load signal", e);
    setSignalBadge(null);
  }
}

// --- Live market panel ------------------------------------------------------
// Polls /api/live, which is served from a short server-side cache. NEPSE is
// never contacted per page load. The panel is display-only: these intraday
// values are intentionally kept out of the model signals, which run on
// completed daily candles.

const LIVE_POLL_MS = 60000;

function _liveBreadth(b) {
  if (!b) return "";
  // Each pill opens a pop-up listing the scrips behind its number.
  const pill = (cls, bucket, n, label) =>
    `<button type="button" class="breadth-pill ${cls}" data-bucket="${bucket}"
       title="Show the ${label.toLowerCase()} list"><span class="n">${n}</span>${label}</button>`;
  return `<div class="breadth-row mt-2">
    ${pill("adv", "advancing", b.advancing, "Advancing")}
    ${pill("dec", "declining", b.declining, "Declining")}
    ${pill("unc", "unchanged", b.unchanged, "Unchanged")}
  </div>`;
}

// --- Breadth pop-up (Advancing / Declining / Unchanged lists) ----------------
const BREADTH_PAGE_SIZE = 10;
const _breadthState = { bucket: null, rows: [], page: 1 };
const _BREADTH_TITLES = { advancing: "Advancing", declining: "Declining", unchanged: "Unchanged" };

// NEPSE-style short units: K = thousand, L = lakh, Cr = crore.
function _shortNum(v) {
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  const f = (x) => String(+x.toFixed(2));
  if (a >= 1e7) return `${f(v / 1e7)} Cr`;
  if (a >= 1e5) return `${f(v / 1e5)} L`;
  if (a >= 1e3) return `${f(v / 1e3)} K`;
  return f(v);
}
const _px = (v) => (v == null || isNaN(v) ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }));

function _breadthPageWindow(page, pages, around = 2) {
  const out = [];
  for (let n = 1; n <= pages; n++) {
    if (n === 1 || n === pages || Math.abs(n - page) <= around) out.push(n);
    else if (out[out.length - 1] !== null) out.push(null);
  }
  return out;
}

function _renderBreadthModal() {
  const { bucket, rows, page } = _breadthState;
  const body = document.getElementById("breadth-modal-body");
  const pager = document.getElementById("breadth-modal-pager");
  if (!body || !pager) return;
  const pages = Math.max(1, Math.ceil(rows.length / BREADTH_PAGE_SIZE));
  const slice = rows.slice((page - 1) * BREADTH_PAGE_SIZE, page * BREADTH_PAGE_SIZE);

  if (!rows.length) {
    body.innerHTML = `<p class="text-dim mb-0">No ${bucket} scrips to show right now.</p>`;
    pager.innerHTML = "";
    return;
  }
  body.innerHTML = `<table class="data-table breadth-table">
    <thead><tr>
      <th>Symbol</th><th>LTP</th><th>CH</th><th>CH %</th><th>Open</th><th>High</th>
      <th>Low</th><th>Vol.</th><th>Turnover</th><th>Pr. Close</th>
    </tr></thead>
    <tbody>${slice.map(r => {
      const cp = r.change_pct;
      const cls = cp == null || cp === 0 ? "" : cp > 0 ? "pos" : "neg";
      const sign = cp > 0 ? "+" : "";
      const ch = r.change == null ? "—" : `${r.change > 0 ? "+" : ""}${_px(r.change)}`;
      const title = r.name ? ` title="${String(r.name).replace(/"/g, "&quot;")}"` : "";
      return `<tr>
        <td${title}><a href="/stock/${encodeURIComponent(r.ticker)}">${r.ticker}</a></td>
        <td>${_px(r.ltp)}</td>
        <td class="${cls}">${ch}</td>
        <td class="${cls}">${cp == null ? "—" : `${sign}${cp}%`}</td>
        <td>${_px(r.open)}</td><td>${_px(r.high)}</td><td>${_px(r.low)}</td>
        <td>${_shortNum(r.volume)}</td><td>${_shortNum(r.turnover)}</td>
        <td>${_px(r.prev_close)}</td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;

  const link = (label, n, disabled) => disabled
    ? `<span class="disabled">${label}</span>`
    : `<a href="#" data-page="${n}">${label}</a>`;
  pager.innerHTML = pages <= 1 ? "" :
    link("‹ Previous", page - 1, page <= 1) +
    _breadthPageWindow(page, pages).map(n =>
      n === null ? `<span class="gap">…</span>`
        : n === page ? `<span class="current">${n}</span>`
        : `<a href="#" data-page="${n}">${n}</a>`).join("") +
    link("Next ›", page + 1, page >= pages);
}

async function openBreadthModal(bucket) {
  const modalEl = document.getElementById("breadth-modal");
  if (!modalEl || !window.bootstrap) return;
  _breadthState.bucket = bucket;
  _breadthState.rows = [];
  _breadthState.page = 1;
  document.getElementById("breadth-modal-title").textContent = _BREADTH_TITLES[bucket] || bucket;
  document.getElementById("breadth-modal-body").innerHTML = `<p class="text-dim mb-0">Loading…</p>`;
  document.getElementById("breadth-modal-pager").innerHTML = "";
  bootstrap.Modal.getOrCreateInstance(modalEl).show();
  try {
    const res = await fetch(`/api/live/breadth/${encodeURIComponent(bucket)}`);
    const data = await res.json();
    if (!data.available) {
      document.getElementById("breadth-modal-body").innerHTML =
        `<p class="text-dim mb-0">${data.reason || "Live data is unavailable right now."}</p>`;
      return;
    }
    _breadthState.rows = data.rows || [];
    const t = document.getElementById("breadth-modal-title");
    t.textContent = `${_BREADTH_TITLES[bucket] || bucket} (${_breadthState.rows.length})`;
    _renderBreadthModal();
  } catch (e) {
    document.getElementById("breadth-modal-body").innerHTML =
      `<p class="text-dim mb-0">Could not load the list. Try again in a moment.</p>`;
  }
}

function _initBreadthModal() {
  const live = document.getElementById("live-body");
  if (live) {
    live.addEventListener("click", (e) => {
      const pill = e.target.closest(".breadth-pill[data-bucket]");
      if (pill) openBreadthModal(pill.dataset.bucket);
    });
  }
  const pager = document.getElementById("breadth-modal-pager");
  if (pager) {
    pager.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-page]");
      if (!a) return;
      e.preventDefault();
      _breadthState.page = parseInt(a.dataset.page, 10) || 1;
      _renderBreadthModal();
      // re-rendering drops the clicked link; keep focus inside the dialog so Esc still closes it
      const modalEl = document.getElementById("breadth-modal");
      if (modalEl) modalEl.focus();
    });
  }
}

function _renderIndicesStrip(rows) {
  const wrap = document.getElementById("indices-strip");
  if (!wrap) return;
  if (!rows || !rows.length) {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = rows.map(r => {
    const up = (r.change_pct ?? 0) >= 0;
    const cls = up ? "pos" : "neg";
    const sign = up ? "+" : "";
    const pct = r.change_pct == null ? "—" : `${sign}${r.change_pct}%`;
    return `<div class="index-chip">
      <span class="name">${r.name.replace(/\s*Index$/i, "")}</span>
      <span class="value">${r.value}</span>
      <span class="${cls}">${pct}</span>
    </div>`;
  }).join("");
}

// "Most active" card: top 10 by turnover or by volume, switched by the tabs in the card header.
let _mostActive = { turnover: [], volume: [], view: "turnover" };

function _renderTopTurnover(rows, volumeRows) {
  const panel = document.getElementById("turnover-panel");
  const body = document.getElementById("turnover-body");
  if (!panel || !body) return;
  _mostActive.turnover = rows || [];
  _mostActive.volume = volumeRows || [];
  if (!_mostActive.turnover.length && !_mostActive.volume.length) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";
  _wireMostActiveTabs();
  _drawMostActive();
}

function _wireMostActiveTabs() {
  const tabs = document.getElementById("active-tabs");
  if (!tabs || tabs.dataset.wired) return;
  tabs.dataset.wired = "1";
  tabs.querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
    _mostActive.view = btn.dataset.view;
    _drawMostActive();
  }));
}

function _drawMostActive() {
  const body = document.getElementById("turnover-body");
  const tabs = document.getElementById("active-tabs");
  if (!body) return;
  const byVolume = _mostActive.view === "volume" && _mostActive.volume.length;
  if (tabs) tabs.querySelectorAll("button").forEach(b => {
    const on = b.dataset.view === (byVolume ? "volume" : "turnover");
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  const rows = byVolume ? _mostActive.volume : _mostActive.turnover;
  if (!rows.length) {
    body.innerHTML = `<p class="text-dim mb-0">No data yet.</p>`;
    return;
  }
  body.innerHTML = `<div class="table-scroll"><table class="data-table">
    <thead><tr><th>#</th><th>Symbol</th><th class="num">LTP</th><th class="num">Change</th><th class="num">${byVolume ? "Volume" : "Turnover"}</th></tr></thead>
    <tbody>${rows.map((r, i) => {
      const up = (r.change_pct ?? 0) >= 0;
      const cls = up ? "pos" : "neg";
      const sign = up ? "+" : "";
      const pct = r.change_pct == null ? "—" : `${sign}${Number(r.change_pct).toFixed(2)}%`;
      const metric = byVolume
        ? (r.volume == null ? "—" : Math.round(r.volume).toLocaleString("en-IN"))
        : (r.turnover == null ? "—" : `Rs ${(r.turnover / 10000000).toFixed(2)} Cr`);
      const title = r.name ? ` title="${_escapeHTML(r.name)}"` : "";
      return `<tr>
        <td class="text-dim">${i + 1}</td>
        <td${title}><a href="/stock/${encodeURIComponent(r.ticker)}">${_escapeHTML(r.ticker)}</a></td>
        <td class="num">${r.ltp ?? "—"}</td>
        <td class="num ${cls}">${pct}</td>
        <td class="num">${metric}</td>
      </tr>`;
    }).join("")}</tbody>
  </table></div>`;
}

function renderLiveMarket(data) {
  const statusEl = document.getElementById("live-status");
  const bodyEl = document.getElementById("live-body");
  if (!statusEl || !bodyEl) return;

  if (!data || !data.available) {
    statusEl.textContent = "unavailable";
    statusEl.className = "live-badge off";
    bodyEl.innerHTML = `<span class="text-dim">${
      (data && data.reason) || "Live data unavailable."
    }</span>`;
    const wrap = document.getElementById("live-chart-wrap");
    if (wrap) wrap.style.display = "none";
    const sub = document.getElementById("subindex-panel");
    if (sub) sub.style.display = "none";
    const turnover = document.getElementById("turnover-panel");
    if (turnover) turnover.style.display = "none";
    _renderIndicesStrip(null);
    return;
  }

  if (data.stale) {
    statusEl.textContent = "stale";
    statusEl.className = "live-badge stale";
  } else if (data.market_open === true) {
    statusEl.textContent = "market open";
    statusEl.className = "live-badge on";
  } else if (data.market_open === false) {
    statusEl.textContent = "market closed";
    statusEl.className = "live-badge off";
  } else {
    statusEl.textContent = "live";
    statusEl.className = "live-badge on";
  }

  let html = "";

  // The indices strip already carries a NEPSE chip, so only show this big
  // line as a fallback when the strip has nothing (avoids a duplicate).
  const stripHasIndex = Array.isArray(data.all_indices) && data.all_indices.length > 0;
  if (data.index && !stripHasIndex) {
    const cls = (data.index.change_pct ?? 0) >= 0 ? "pos" : "neg";
    const sign = (data.index.change_pct ?? 0) >= 0 ? "+" : "";
    const chg = data.index.change_pct == null
      ? "" : ` <span class="${cls}">${sign}${data.index.change_pct}%</span>`;
    html += `<div class="live-index">
      <span class="live-index-name">${data.index.name}</span>
      <span class="live-index-value">${data.index.value}</span>${chg}
    </div>`;
  }

  html += _liveBreadth(data.breadth);

  if (!html) html = `<span class="text-dim">No live data to show right now.</span>`;
  bodyEl.innerHTML = html;

  renderLiveIndexChart(data.index_history, data.index);
  renderSubIndices(data.subindices);
  _renderIndicesStrip(data.all_indices);
  _renderTopTurnover(data.top_turnover, data.top_volume);
  _layoutIndicesRow();
  _renderNavIndex(data);
}

// When the Top Turnover panel has nothing to show, its column stays
// display:none but Bootstrap's grid still reserves its width -- Sector
// Indices was left looking cramped against a dead strip of empty page.
// Let Sector Indices claim the full row instead when that happens.
function _layoutIndicesRow() {
  const subCol = document.getElementById("subindex-col");
  const turnoverPanel = document.getElementById("turnover-panel");
  if (!subCol) return;
  const turnoverVisible = turnoverPanel && turnoverPanel.style.display !== "none";
  subCol.classList.toggle("col-md-7", turnoverVisible);
  subCol.classList.toggle("col-12", !turnoverVisible);
}

// --- NEPSE index badge in the navbar -----------------------------------
// Shown on every page (not just the dashboard), so it polls /api/live on
// its own rather than piggybacking only on the dashboard's live panel.

function _renderNavIndex(data) {
  const wrap = document.getElementById("nav-index");
  if (!wrap) return;
  if (!data || !data.available || !data.index) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";
  const idx = data.index;
  const up = (idx.change_pct ?? 0) >= 0;
  const sign = up ? "+" : "";
  const arrow = up ? "▲" : "▼";
  wrap.className = "nav-index " + (up ? "pos" : "neg");
  const dot = document.getElementById("nav-index-dot");
  if (dot) dot.className = "nav-index-dot " + (data.market_open ? "on" : "off");
  const valueEl = document.getElementById("nav-index-value");
  if (valueEl) valueEl.textContent = idx.value;
  const chgEl = document.getElementById("nav-index-change");
  if (chgEl) {
    const chg = idx.change == null ? "" : `${sign}${idx.change}`;
    const pct = idx.change_pct == null ? "" : `${arrow} ${sign}${idx.change_pct}%`;
    // two parts so narrow laptop widths can drop the points and keep the %
    chgEl.textContent = "";
    if (chg) { const s1 = document.createElement("span"); s1.className = "nav-index-pts"; s1.textContent = chg; chgEl.append(s1, " "); }
    if (pct) { const s2 = document.createElement("span"); s2.textContent = pct; chgEl.append(s2); }
  }
}

async function _pollNavIndex() {
  const wrap = document.getElementById("nav-index");
  if (!wrap) return;
  // Skip if the dashboard's own live panel is already on this page and
  // will call _renderNavIndex itself from the same /api/live response.
  if (document.getElementById("live-panel")) return;
  try {
    const res = await fetch("/api/live");
    _renderNavIndex(await res.json());
  } catch (e) {
    wrap.style.display = "none";
  }
}

function initNavIndex() {
  _pollNavIndex();
  setInterval(_pollNavIndex, LIVE_POLL_MS);
}
initNavIndex();

// --- Upgrade the end-of-day sections with live data ------------------------
// The server renders yesterday's close so the page is useful immediately (and
// without JS). Once /api/live answers, these sections are swapped to live
// values. When the market closes, NEPSE keeps returning that day's final
// numbers, so the tables simply hold at the closing values until it reopens --
// no special "market closed" handling needed.

function _sourceLabel(data) {
  if (data.stale) return "delayed";
  if (data.market_open === true) return "live";
  if (data.market_open === false) return "market closed";
  return "live";
}

function _moverRowHTML(m, positive) {
  const pct = m.change_pct;
  const cls = (pct ?? 0) >= 0 ? "pos" : "neg";
  const sign = (pct ?? 0) >= 0 ? "+" : "";
  const shown = pct == null ? "—" : `${sign}${Number(pct).toFixed(2)}%`;
  const title = m.name ? ` title="${m.name.replace(/"/g, "&quot;")}"` : "";
  // .num right-aligns the numbers under their right-aligned column headers
  return `<tr>
    <td${title}><a href="/stock/${encodeURIComponent(m.ticker)}">${m.ticker}</a></td>
    <td class="num">${m.ltp ?? "—"}</td>
    <td class="num ${cls}">${shown}</td>
  </tr>`;
}

function updateEodSectionsFromLive(data) {
  if (!data || !data.available) return;
  const label = _sourceLabel(data);

  const gBody = document.getElementById("gainers-body");
  const lBody = document.getElementById("losers-body");
  const srcEl = document.getElementById("movers-source");

  if (gBody && data.gainers && data.gainers.length) {
    gBody.innerHTML = data.gainers.slice(0, 5).map(m => _moverRowHTML(m, true)).join("");
  }
  if (lBody && data.losers && data.losers.length) {
    lBody.innerHTML = data.losers.slice(0, 5).map(m => _moverRowHTML(m, false)).join("");
  }
  if (srcEl && ((data.gainers || []).length || (data.losers || []).length)) {
    srcEl.textContent = label;
    srcEl.className = "src-badge " + (data.stale ? "stale" : data.market_open === false ? "" : "live");
  }

  // Site-wide ticker strip, so it doesn't sit next to live tables showing
  // yesterday's numbers.
  const strip = document.querySelector(".ticker-strip");
  const stripSource = (data.gainers || []).concat(data.losers || []).slice(0, 8);
  if (strip && stripSource.length) {
    const item = m => {
      const cls = (m.change_pct ?? 0) >= 0 ? "pos" : "neg";
      const sign = (m.change_pct ?? 0) >= 0 ? "+" : "";
      const pct = m.change_pct == null ? "—" : `${sign}${m.change_pct}%`;
      const title = m.name ? ` title="${m.name.replace(/"/g, "&quot;")}"` : "";
      return `<a class="ticker-item" href="/stock/${encodeURIComponent(m.ticker)}"${title}>
        <span class="sym">${m.ticker}</span>
        <span>Rs ${m.ltp}</span>
        <span class="chg ${cls}">${pct}</span>
      </a>`;
    };
    // duplicated for the seamless marquee loop, same as the server-rendered markup
    strip.innerHTML = stripSource.map(item).join("") + stripSource.map(item).join("");
  }
}

async function loadLiveMarket() {
  try {
    const resp = await fetch("/api/live");
    const data = await resp.json();
    renderLiveMarket(data);
    updateEodSectionsFromLive(data);
  } catch (e) {
    console.error("Live market fetch failed", e);
    renderLiveMarket(null);
  }
}

function initLiveMarket() {
  if (!document.getElementById("live-panel")) return;
  _initBreadthModal();
  loadLiveMarket();
  setInterval(loadLiveMarket, LIVE_POLL_MS);
}

// --- Intraday NEPSE index chart (ShareHub-style 1D view) --------------------
// Data comes from getDailyNepseIndexGraph(), which returns genuine intraday
// points (~one every 30s through the session), so this is a real intraday
// curve rather than a line joining daily closes.

let _liveIndexChart = null;

// NEPSE trades in Nepal Time. The server may run in another region and the
// viewer may be anywhere, so timestamps are always formatted as NPT rather
// than the viewer's locale -- otherwise the session would appear to start at
// the wrong hour.
function _nptTime(unixSeconds) {
  return new Date(unixSeconds * 1000).toLocaleTimeString("en-US", {
    timeZone: "Asia/Kathmandu",
    hour: "numeric",
    minute: "2-digit",
  });
}

// After the market closes, NEPSE keeps appending points at the same closing
// value while we keep polling -- which drew as an ugly flat line stretching
// to "now" on the chart. Trim that trailing repeated-value run down to a
// single point, so the line stops where the price actually stopped moving.
function _trimTrailingFlat(series) {
  if (!series || series.length < 3) return series;
  let end = series.length - 1;
  const lastVal = series[end].v;
  while (end > 0 && series[end - 1].v === lastVal) {
    end -= 1;
  }
  // Keep one point past the last real move so the line still reaches it.
  const cutoff = Math.min(end + 1, series.length - 1);
  return series.slice(0, cutoff + 1);
}

// Draws a dashed line at the previous close and a value tag for the latest
// point on the right axis -- the two reference marks ShareHub's 1D chart has.
const _liveRefPlugin = {
  id: "liveRef",
  afterDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea, scales: { y } } = chart;
    if (!y) return;
    const font = "600 11px -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
    const tag = (value, bg, fg, dash) => {
      if (!Number.isFinite(value)) return;
      const py = y.getPixelForValue(value);
      if (py < chartArea.top - 1 || py > chartArea.bottom + 1) return;
      ctx.save();
      ctx.setLineDash(dash);
      ctx.strokeStyle = bg;
      ctx.globalAlpha = 0.85;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(chartArea.left, py);
      ctx.lineTo(chartArea.right, py);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
      ctx.font = font;
      const label = value.toFixed(2);
      const w = ctx.measureText(label).width + 12;
      ctx.fillStyle = bg;
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(chartArea.right + 2, py - 9, w, 18, 3) : ctx.rect(chartArea.right + 2, py - 9, w, 18);
      ctx.fill();
      ctx.fillStyle = fg;
      ctx.textBaseline = "middle";
      ctx.fillText(label, chartArea.right + 8, py);
      ctx.restore();
    };
    tag(opts.prevClose, CHART_COLORS.text, CHART_COLORS.bg || "#111", [2, 3]);   // previous close: dotted grey
    const data = chart.data.datasets[0].data;
    tag(_pointY(data[data.length - 1]), opts.lineColor, "#fff", [5, 4]);                 // latest value: dashed, like ShareHub
  },
};

function _liveGradient(chart, rgb) {
  const { ctx, chartArea } = chart;
  if (!chartArea) return `rgba(${rgb},0.15)`;
  const g = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
  g.addColorStop(0, `rgba(${rgb},0.38)`);
  g.addColorStop(0.65, `rgba(${rgb},0.10)`);
  g.addColorStop(1, `rgba(${rgb},0.0)`);
  return g;
}

// NEPSE's regular session runs 11:00-15:00 Nepal Time (UTC+5:45). The x-axis
// always spans that whole window, so mid-session the curve stops at "now"
// with empty space to 3 PM, the way ShareHub draws it.
const NPT_OFFSET_S = 5.75 * 3600;
const SESSION_OPEN_H = 11, SESSION_CLOSE_H = 15;

function _sessionWindow(unixSeconds) {
  const nptMidnight = Math.floor((unixSeconds + NPT_OFFSET_S) / 86400) * 86400 - NPT_OFFSET_S;
  return { open: nptMidnight + SESSION_OPEN_H * 3600, close: nptMidnight + SESSION_CLOSE_H * 3600 };
}

function _nptHourLabel(unixSeconds) {
  const h = Math.round(((unixSeconds + NPT_OFFSET_S) % 86400) / 3600) % 24;
  return `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`;
}

function renderLiveIndexChart(rawSeries, indexInfo) {
  const wrap = document.getElementById("live-chart-wrap");
  const ctx = document.getElementById("live-index-chart");
  if (!wrap || !ctx) return;

  if (!rawSeries || rawSeries.length < 2) {
    wrap.style.display = "none";
    return;
  }
  const win = _sessionWindow(rawSeries[rawSeries.length - 1].t);
  // drop pre-open / after-close ticks so the curve lives inside 11 AM - 3 PM
  const inSession = rawSeries.filter(p => p.t >= win.open && p.t <= win.close);
  const series = _trimTrailingFlat(inSession.length >= 2 ? inSession : rawSeries);
  wrap.style.display = "";

  // Colour the curve by the day's direction, like ShareHub does.
  const down = (indexInfo && indexInfo.change_pct != null)
    ? indexInfo.change_pct < 0
    : series[series.length - 1].v < series[0].v;
  const line = down ? CHART_COLORS.red : CHART_COLORS.green;
  const rgb = down ? "220,38,38" : "22,163,74";
  const prevClose = (indexInfo && indexInfo.value != null && indexInfo.change != null)
    ? indexInfo.value - indexInfo.change : null;

  const points = series.map(p => ({ x: p.t, y: p.v }));
  const values = series.map(p => p.v);

  // Each 60s poll updates the existing chart in place instead of destroying
  // and rebuilding it, so the line extends smoothly without a flash.
  if (_liveIndexChart && _liveIndexChart.canvas === ctx && _liveIndexChart.$down === down
      && _liveIndexChart.$phone === _isPhone()) {
    _liveIndexChart.data.datasets[0].data = points;
    _liveIndexChart.options.scales.x.min = win.open;
    _liveIndexChart.options.scales.x.max = win.close;
    _liveIndexChart.options.plugins.liveRef.prevClose = prevClose;
    _liveIndexChart.update("none");
    return;
  }
  if (_liveIndexChart) _liveIndexChart.destroy();

  // keep the previous-close line in view when it sits just outside the day's range
  let suggestedMin, suggestedMax;
  if (prevClose != null) {
    suggestedMin = Math.min(...values, prevClose);
    suggestedMax = Math.max(...values, prevClose);
  }

  _liveIndexChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [{
        label: "NEPSE Index",
        data: points,
        borderColor: line,
        backgroundColor: (c) => _liveGradient(c.chart, rgb),
        borderWidth: 2,
        fill: "start",
        cubicInterpolationMode: "monotone",   // smooth curve that never overshoots the data
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: line,
        pointHitRadius: 10,
        borderCapStyle: "round",
        borderJoinStyle: "round",
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,          // no redraw flicker on each 60s poll
      layout: { padding: { right: 4, top: 6 } },
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: {
        legend: { display: false },
        liveRef: { prevClose, lineColor: line },
        tooltip: {
          displayColors: false,
          callbacks: {
            title: (items) => _nptTime(items[0].parsed.x) + " NPT",
            label: (item) => {
              const v = item.parsed.y;
              if (prevClose == null) return `Index ${v.toFixed(2)}`;
              const d = v - prevClose;
              return `Index ${v.toFixed(2)}  (${d >= 0 ? "+" : ""}${d.toFixed(2)})`;
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: win.open,
          max: win.close,
          grid: { display: false },
          border: { display: false },
          // one tick per hour: 11 AM, 12 PM, 1 PM, 2 PM, 3 PM
          afterBuildTicks: (scale) => {
            scale.ticks = [];
            for (let t = scale.min; t <= scale.max; t += 3600) scale.ticks.push({ value: t });
          },
          ticks: { maxRotation: 0, padding: 6, autoSkip: false, callback: (v) => _nptHourLabel(v) },
        },
        y: {
          position: "right",
          suggestedMin, suggestedMax,
          grace: "6%",
          border: { display: false },
          grid: { color: CHART_COLORS.grid, drawTicks: false },
          ticks: { maxTicksLimit: _isPhone() ? 5 : 6, padding: 8, callback: (v) => Number(v).toFixed(0) },
          afterFit: (scale) => { scale.width = Math.max(scale.width, 58); },  // room for the value tags
        },
      },
    },
    plugins: [crosshairPlugin, _liveRefPlugin],
  });
  _liveIndexChart.$down = down;
  _liveIndexChart.$phone = _isPhone();
  _registerThemeRedraw("liveIndex", () => { if (_liveIndexChart) { _liveIndexChart.destroy(); _liveIndexChart = null; } renderLiveIndexChart(rawSeries, indexInfo); });
}

// --- Live quote on the stock detail page -----------------------------------
// Upgrades the server-rendered end-of-day figures to live values. Backed by
// /api/live/quote/<ticker>, which reads the same cached getLiveMarket payload
// the dashboard uses -- so this adds no extra load on NEPSE.

function _fmtRs(v) {
  return v == null ? "—" : `Rs. ${v}`;
}

function _fmtInt(v) {
  return v == null ? "—" : Math.round(v).toLocaleString();
}

function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderLiveQuote(q) {
  // Leave the server-rendered end-of-day values untouched when there's no
  // live data (market never opened for this scrip, NEPSE unreachable, etc.)
  if (!q || !q.available) return;

  _setText("q-ltp", _fmtRs(q.ltp));

  const chgEl = document.getElementById("q-change");
  if (chgEl) {
    if (q.change == null && q.change_pct == null) {
      chgEl.textContent = "";
    } else {
      const up = (q.change ?? q.change_pct ?? 0) >= 0;
      const sign = up ? "+" : "";
      const pts = q.change == null ? "" : `${sign}${q.change}`;
      const pct = q.change_pct == null ? "" : ` (${sign}${q.change_pct}%)`;
      chgEl.textContent = `${pts}${pct}`.trim();
      chgEl.className = "chg " + (up ? "pos" : "neg");
    }
  }

  _setText("q-open", _fmtRs(q.open));
  _setText("q-high", _fmtRs(q.high));
  _setText("q-low", _fmtRs(q.low));
  _setText("q-prev", _fmtRs(q.prev_close));
  _setText("q-volume", _fmtInt(q.volume));
  _setText("q-turnover", _fmtInt(q.turnover));

  if (q.avg_price != null) {
    const wrap = document.getElementById("q-avg-wrap");
    if (wrap) wrap.style.display = "";
    _setText("q-avg", _fmtRs(q.avg_price));
  }

  const label = q.stale ? "delayed"
    : q.market_open === false ? "market closed"
    : "live";
  const srcEl = document.getElementById("q-source");
  if (srcEl) {
    srcEl.textContent = label;
    srcEl.className = "src-badge " + (q.stale ? "stale" : "live");
  }
  _setText("q-asof", q.market_open === false
    ? "Latest traded values from NEPSE (market closed)"
    : "Live from NEPSE, refreshed about once a minute");
}

async function loadLiveQuote(ticker) {
  try {
    const resp = await fetch(`/api/live/quote/${encodeURIComponent(ticker)}`);
    renderLiveQuote(await resp.json());
  } catch (e) {
    console.error("Live quote fetch failed", e);
  }
}

function initLiveQuote(ticker) {
  if (!ticker || !document.getElementById("q-ltp")) return;
  loadLiveQuote(ticker);
  setInterval(() => loadLiveQuote(ticker), LIVE_POLL_MS);
}

// --- Sector sub-indices -----------------------------------------------------
// NEPSE publishes a live index per sector. Sectors this project models are
// marked, tying live sector moves back to the sector-wise classifiers.

function renderSubIndices(rows) {
  const panel = document.getElementById("subindex-panel");
  const body = document.getElementById("subindex-body");
  if (!panel || !body) return;

  if (!rows || !rows.length) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";

  body.innerHTML = `<table class="data-table">
    <thead><tr><th>Sector</th><th>Index</th><th>Change</th></tr></thead>
    <tbody>${rows.map(r => {
      const up = (r.change_pct ?? 0) >= 0;
      const cls = up ? "pos" : "neg";
      const sign = up ? "+" : "";
      const pct = r.change_pct == null ? "—" : `${sign}${r.change_pct}%`;
      const pts = r.change == null ? "" : ` <span class="text-dim pts">(${sign}${r.change})</span>`;
      const dot = r.model_sector
        ? `<span class="model-dot" title="Modeled sector: ${r.model_sector}"></span>`
        : "";
      return `<tr>
        <td>${dot}${r.name}</td>
        <td>${r.value}</td>
        <td class="${cls}">${pct}${pts}</td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;
}

// --- Ticker search (navbar, watchlist, portfolio) ------------------------------
// A custom autocomplete rather than a native <datalist>: browsers dump every
// option on focus, which meant all ~270 tickers appeared before typing a
// character. This renders a short, ranked list as you type; on an empty
// field it shows your last 5 searches and (signed in) a few stock ideas.

const NAV_SEARCH_LIMIT = 8;
const SEARCH_HISTORY_SHOWN = 5;
const _LOCAL_HISTORY_KEY = "nepse-search-history";
let _tickerIndex = null;      // [{t, n}], fetched once
let _tickerIndexPromise = null;

async function _loadTickerIndex() {
  if (_tickerIndex) return _tickerIndex;
  if (!_tickerIndexPromise) {
    _tickerIndexPromise = fetch("/api/tickers")
      .then(r => r.json())
      .then(rows => { _tickerIndex = Array.isArray(rows) ? rows : []; return _tickerIndex; })
      .catch(() => { _tickerIndex = []; return _tickerIndex; });
  }
  return _tickerIndexPromise;
}

function _matchTickers(query) {
  const q = (query || "").trim().toLowerCase();
  if (!q || !_tickerIndex) return [];
  // exact symbol first, then symbol prefix, then name prefix / word prefix, then substring
  // (a symbol prefix that is also the company's first word -- "nab" -> NABIL,
  // Nabil Bank -- outranks a symbol-only prefix like NABBC)
  const buckets = [[], [], [], [], []];
  for (const row of _tickerIndex) {
    const t = row.t.toLowerCase();
    const n = (row.n || "").toLowerCase();
    const namePrefix = n.startsWith(q);
    if (t === q) buckets[0].push(row);
    else if (t.startsWith(q) && namePrefix) buckets[1].push(row);
    else if (t.startsWith(q)) buckets[2].push(row);
    else if (namePrefix || n.includes(" " + q)) buckets[3].push(row);
    else if (t.includes(q) || n.includes(q)) buckets[4].push(row);
  }
  return buckets.flat().slice(0, NAV_SEARCH_LIMIT);
}

function _escapeHTML(s) {
  return String(s ?? "").replace(/[&<>"']/g, ch => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function _highlight(text, q) {
  const s = String(text || "");
  const i = q ? s.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return _escapeHTML(s);
  return _escapeHTML(s.slice(0, i)) + "<mark>" + _escapeHTML(s.slice(i, i + q.length)) + "</mark>"
    + _escapeHTML(s.slice(i + q.length));
}

const _metaContent = (name) => (document.querySelector(`meta[name="${name}"]`) || {}).content || "";
const _isSignedIn = () => _metaContent("signed-in") === "1";

// Search history: kept on the server for signed-in users (so it follows them
// across devices and feeds their stock ideas), in this browser otherwise.
function _localHistory() {
  try { return JSON.parse(localStorage.getItem(_LOCAL_HISTORY_KEY) || "[]").slice(0, SEARCH_HISTORY_SHOWN); }
  catch (e) { return []; }
}
function _saveLocalHistory(rows) {
  try { localStorage.setItem(_LOCAL_HISTORY_KEY, JSON.stringify(rows.slice(0, SEARCH_HISTORY_SHOWN))); } catch (e) { /* storage off */ }
}

let _historyCache = null;
async function _loadHistory() {
  if (_historyCache) return _historyCache;
  if (_isSignedIn()) {
    try {
      const r = await fetch("/api/me/search-history", { credentials: "same-origin" });
      const d = await r.json();
      if (d.ok) { _historyCache = d.items; return _historyCache; }
    } catch (e) { /* fall back to local */ }
  }
  _historyCache = _localHistory();
  return _historyCache;
}

function _recordSearch(row) {
  const next = [row, ...(_historyCache || _localHistory()).filter(h => h.t !== row.t)].slice(0, SEARCH_HISTORY_SHOWN);
  _historyCache = next;
  _saveLocalHistory(next);
  if (_isSignedIn()) {
    // keepalive lets the request finish while the page navigates away
    fetch("/api/me/search-history", {
      method: "POST", keepalive: true, credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": _metaContent("csrf-token") },
      body: JSON.stringify({ ticker: row.t }),
    }).catch(() => {});
  }
}

async function _clearHistory() {
  _historyCache = [];
  _saveLocalHistory([]);
  if (_isSignedIn()) {
    try {
      await fetch("/api/me/search-history", {
        method: "DELETE", credentials: "same-origin", headers: { "X-CSRF-Token": _metaContent("csrf-token") },
      });
    } catch (e) { /* already cleared locally */ }
  }
}

let _ideasPromise = null;
function _loadIdeas() {
  if (!_isSignedIn()) return Promise.resolve([]);
  if (!_ideasPromise) {
    _ideasPromise = fetch("/api/me/recommendations?limit=3", { credentials: "same-origin" })
      .then(r => r.json()).then(d => (d.ok ? d.items : [])).catch(() => []);
  }
  return _ideasPromise;
}

/**
 * Attach the autocomplete to an <input> and its results <div>.
 * opts.onPick(row)       called with {t, n} when a symbol is chosen
 * opts.showHistory       show recent searches + ideas on an empty field
 * opts.record            save picks to the search history
 */
function attachTickerSearch(input, box, opts = {}) {
  if (!input || !box || input.dataset.tsReady) return;
  input.dataset.tsReady = "1";
  input.setAttribute("autocomplete", "off");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  if (box.id) input.setAttribute("aria-controls", box.id);
  box.setAttribute("role", "listbox");

  let rows = [];        // rows currently selectable, in display order
  let active = -1;
  let timer = null;
  let seq = 0;          // drops stale async renders

  const open = () => { box.classList.add("open"); input.setAttribute("aria-expanded", "true"); };
  const close = () => {
    box.classList.remove("open");
    input.setAttribute("aria-expanded", "false");
    active = -1;
  };

  const item = (r, i, q, extra = "") => `
    <div class="nav-search-item${i === active ? " active" : ""}" role="option" id="${box.id || "ts"}-opt-${i}"
         aria-selected="${i === active}" data-index="${i}">
      <span class="sym">${_highlight(r.t, q)}</span>
      <span class="nm">${_highlight(r.n || "", q)}</span>${extra}
    </div>`;

  function paintActive() {
    box.querySelectorAll(".nav-search-item").forEach((el) => {
      const on = Number(el.dataset.index) === active;
      el.classList.toggle("active", on);
      el.setAttribute("aria-selected", on ? "true" : "false");
      if (on) el.scrollIntoView({ block: "nearest" });
    });
    input.setAttribute("aria-activedescendant", active >= 0 ? `${box.id || "ts"}-opt-${active}` : "");
  }

  async function renderEmpty() {
    if (!opts.showHistory) { close(); return; }
    const my = ++seq;
    const [hist, ideas] = await Promise.all([_loadHistory(), _loadIdeas()]);
    if (my !== seq || input.value.trim()) return;
    rows = [];
    let html = "";
    if (hist.length) {
      html += `<div class="ts-head"><span>Recent searches</span><button type="button" class="ts-clear" data-clear>Clear</button></div>`;
      html += hist.map(h => { rows.push(h); return item(h, rows.length - 1, "", `<span class="ts-ico" aria-hidden="true">↺</span>`); }).join("");
    }
    if (ideas.length) {
      html += `<div class="ts-head"><span>Ideas for you</span><a href="/portfolio#ideas" class="ts-clear">See why</a></div>`;
      html += ideas.map(r => {
        const row = { t: r.ticker, n: r.name };
        rows.push(row);
        const cls = r.forecast_pct >= 0 ? "pos" : "neg";
        return item(row, rows.length - 1, "", `<span class="ts-tag ${cls}">${r.forecast_pct > 0 ? "+" : ""}${r.forecast_pct}%</span>`);
      }).join("");
    }
    if (!html) { close(); return; }
    box.innerHTML = html;
    open();
  }

  async function renderQuery() {
    const q = input.value.trim();
    if (!q) { renderEmpty(); return; }
    const my = ++seq;
    await _loadTickerIndex();
    if (my !== seq) return;
    rows = _matchTickers(q);
    active = rows.length ? 0 : -1;   // Enter picks the best match
    box.innerHTML = rows.length
      ? rows.map((r, i) => item(r, i, q)).join("")
      : `<div class="ts-empty">No symbol or company matches “${_escapeHTML(q)}”.</div>`;
    open();
    paintActive();
  }

  function pick(row) {
    if (!row) return;
    if (opts.record) _recordSearch(row);
    close();
    if (opts.onPick) opts.onPick(row);
  }

  input.addEventListener("focus", () => { _loadTickerIndex(); if (!input.value.trim()) renderEmpty(); });
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(renderQuery, 60);   // light debounce: smooth while typing fast
  });
  input.addEventListener("keydown", (e) => {
    const isOpen = box.classList.contains("open");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!isOpen) { input.value.trim() ? renderQuery() : renderEmpty(); return; }
      if (rows.length) { active = (active + 1) % rows.length; paintActive(); }
    } else if (e.key === "ArrowUp" && isOpen && rows.length) {
      e.preventDefault();
      active = active <= 0 ? rows.length - 1 : active - 1;
      paintActive();
    } else if (e.key === "Enter" && isOpen && active >= 0 && rows[active]) {
      e.preventDefault();
      pick(rows[active]);
    } else if (e.key === "Escape") {
      close();
    }
  });
  box.addEventListener("mousedown", async (e) => {
    // mousedown, not click -- blur would close the list first
    if (e.target.closest("[data-clear]")) {
      e.preventDefault();
      await _clearHistory();
      renderEmpty();
      return;
    }
    if (e.target.closest("a")) return;
    const el = e.target.closest(".nav-search-item");
    if (el) { e.preventDefault(); pick(rows[Number(el.dataset.index)]); }
  });
  box.addEventListener("mousemove", (e) => {
    const el = e.target.closest(".nav-search-item");
    if (el && Number(el.dataset.index) !== active) { active = Number(el.dataset.index); paintActive(); }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
}

function _gotoTicker(ticker) {
  if (ticker) window.location = `/stock/${encodeURIComponent(ticker)}`;
}

function wireNavSearch() {
  const form = document.getElementById("nav-search-form");
  const input = document.getElementById("nav-search-input");
  const box = document.getElementById("nav-search-results");
  if (!form || !input || !box) return;
  attachTickerSearch(input, box, { showHistory: true, record: true, onPick: (r) => _gotoTicker(r.t) });
  form.addEventListener("submit", async (e) => {
    // Enter with the list closed (or no match): best effort
    e.preventDefault();
    await _loadTickerIndex();
    const best = _matchTickers(input.value)[0];
    if (best) { _recordSearch(best); _gotoTicker(best.t); }
    else if (input.value.trim()) _gotoTicker(input.value.trim().toUpperCase());
  });
}

wireNavSearch();

// ── Price Forecast chart (stock detail page) ────────────────────────────
// Mirrors notebooks/forecasting_models.ipynb: actual price history (last
// ~180 days) + the forecast's dashed line + a shaded confidence band, with
// Plotly's built-in range slider and 1W/1M/3M/6M/All zoom buttons. Fetches
// its own two endpoints once and keeps its own Plotly figure -- deliberately
// separate from initLiveQuote()/loadStockDetail() above, so it never touches
// or is touched by the live-quote polling or the Chart.js price-history chart.
let _forecastHistory = null;   // [{date, close}, ...] from /api/forecast (reused -- see note in app/api.py)
let _forecastDays = null;      // [{date, forecast_price, lower_bound, upper_bound}, ...]

function _forecastPlotlyLayout() {
  const c = CHART_COLORS;
  const dark = _isDarkTheme();
  const phone = _isPhone();
  const layout = {
    title: { text: "", font: { color: c.text } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: c.text, family: "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif" },
    margin: { l: 55, r: 130, t: 30, b: 40 },
    hovermode: "x unified",
    showlegend: true,
    // Vertical, docked to the right of the plot -- the range-selector
    // buttons (1W/1M/3M/6M/All) already occupy the top-left above the
    // plot, so a horizontal top legend collided with them. Right margin
    // above is widened to make room for this legend outside the plot area.
    legend: { orientation: "v", x: 1.02, xanchor: "left", y: 1, yanchor: "top", font: { color: c.text } },
    xaxis: {
      gridcolor: c.grid, zerolinecolor: c.grid, color: c.text,
      rangeslider: { visible: true, bgcolor: "rgba(0,0,0,0)", bordercolor: c.grid, thickness: 0.08 },
      rangeselector: {
        x: 0, xanchor: "left", y: 1.12, yanchor: "bottom",
        bgcolor: dark ? "#1a1a1a" : "#f0f2f5",
        activecolor: dark ? "#3b4a63" : "#c7d7f5",
        font: { color: c.text },
        buttons: [
          { count: 7, label: "1W", step: "day", stepmode: "backward" },
          { count: 1, label: "1M", step: "month", stepmode: "backward" },
          { count: 3, label: "3M", step: "month", stepmode: "backward" },
          { count: 6, label: "6M", step: "month", stepmode: "backward" },
          { step: "all", label: "All" },
        ],
      },
    },
    yaxis: { title: "Price (Rs.)", gridcolor: c.grid, zerolinecolor: c.grid, color: c.text },
  };
  if (phone) {
    // Narrow screens: legend moves under the chart, margins shrink, axis
    // labels stay horizontal and sparse, and the range buttons get smaller.
    layout.height = 400;
    layout.margin = { l: 44, r: 10, t: 40, b: 10 };
    layout.font.size = 11;
    layout.legend = { orientation: "h", x: 0, xanchor: "left", y: -0.1, yanchor: "top", font: { color: c.text, size: 11 } };
    layout.xaxis.nticks = 4;
    layout.xaxis.tickangle = 0;
    layout.xaxis.tickformat = "%b %y";
    layout.xaxis.rangeslider.visible = false;
    layout.xaxis.rangeselector.y = 1.04;
    layout.xaxis.rangeselector.font = { color: c.text, size: 11 };
    layout.yaxis.title = "";
    layout.yaxis.nticks = 5;
    // Open zoomed on the last ~3 months + the forecast, so the 30-day
    // window isn't a thin sliver at the right edge of a narrow screen.
    const hist = _forecastHistory || [], days = _forecastDays || [];
    if (hist.length > 60 && days.length) {
      layout.xaxis.range = [hist[hist.length - 60].date, days[days.length - 1].date];
      layout.xaxis.rangeselector.buttons.forEach(b => { b.active = false; });
    }
  } else {
    layout.height = 460;
  }
  return layout;
}

function _forecastPlotlyTraces() {
  const c = CHART_COLORS;
  const hist = _forecastHistory || [];
  const days = _forecastDays || [];

  return [
    {
      x: hist.map(h => h.date), y: hist.map(h => h.close),
      name: "Actual Price", mode: "lines",
      line: { color: c.accent, width: 2 },
      hovertemplate: "<b>%{x}</b><br>Price: Rs. %{y:.1f}<extra></extra>",
    },
    {
      x: days.map(d => d.date), y: days.map(d => d.forecast_price),
      name: "Middle of range", mode: "lines",
      line: { color: c.red, width: 2 },
      hovertemplate: "<b>%{x}</b><br>Middle of range: Rs. %{y:.1f}<extra></extra>",
    },
    {
      x: days.map(d => d.date), y: days.map(d => d.upper_bound),
      name: "Upper Bound", mode: "lines",
      line: { width: 0 }, showlegend: false,
      hovertemplate: "Upper: Rs. %{y:.1f}<extra></extra>",
    },
    {
      x: days.map(d => d.date), y: days.map(d => d.lower_bound),
      name: "80% range", mode: "lines",
      line: { width: 0 }, fill: "tonexty", fillcolor: c.redFillTransparent,
      hovertemplate: "Lower: Rs. %{y:.1f}<extra></extra>",
    },
  ];
}

function _renderForecastChart() {
  const el = document.getElementById("forecast-chart");
  if (!el || typeof Plotly === "undefined") return;
  Plotly.react(el, _forecastPlotlyTraces(), _forecastPlotlyLayout(), {
    responsive: true,
    displayModeBar: !_isPhone(),
    displaylogo: false,
    // Drop the camera/download-image button and the box-zoom drag-mode
    // tool -- the +/- buttons already next to them cover zooming.
    modeBarButtonsToRemove: ["toImage", "zoom2d"],
  });
}
_registerThemeRedraw("forecast-chart", () => {
  if (_forecastDays) _renderForecastChart();
});

async function initForecast(ticker) {
  const panel = document.getElementById("forecast-panel");
  const chartEl = document.getElementById("forecast-chart");
  if (!panel || !chartEl) return;

  try {
    const [histRes, fcRes] = await Promise.all([
      fetch(`/api/forecast/${ticker}`),
      fetch(`/api/price-forecast/${ticker}`),
    ]);
    const fc = await fcRes.json();
    if (fc.status !== "ok" || !fc.days || !fc.days.length) {
      panel.style.display = "none";
      return;
    }
    const hist = await histRes.json();

    // Last ~180 days of actual closes, same cutoff as the notebook, so the
    // chart reads as "recent history -> forecast" rather than the full
    // multi-year series dwarfing the 30-day forecast window.
    _forecastHistory = (hist.history || []).slice(-180);
    _forecastDays = fc.days;

    panel.style.display = "";
    _renderForecastChart();

    const currentEl = document.getElementById("forecast-current");
    const priceEl = document.getElementById("forecast-price");
    const lowerEl = document.getElementById("forecast-lower");
    const upperEl = document.getElementById("forecast-upper");
    const lastDay = fc.days[fc.days.length - 1];
    if (currentEl) currentEl.textContent = `Rs. ${fc.current_price}`;
    if (priceEl) priceEl.textContent = `Rs. ${lastDay.forecast_price}`;
    if (lowerEl) lowerEl.textContent = `Rs. ${lastDay.lower_bound}`;
    if (upperEl) upperEl.textContent = `Rs. ${lastDay.upper_bound}`;

    const metaEl = document.getElementById("forecast-meta");
    if (metaEl) {
      metaEl.textContent = `Starting price: Rs. ${fc.current_price} `
        + `(range generated ${fc.generated_at} from the last 2 years of closing prices).`;
    }
  } catch (e) {
    panel.style.display = "none";
  }
}

// --- "Why this signal?" panel -------------------------------------------------
// Fetched only when the viewer opens the panel (the explanation is computed live
// on the server, so there is no reason to pay for it on every page view).
function _renderExplain(d) {
  const body = document.getElementById("explain-body");
  if (!body) return;
  if (!d || d.error) {
    body.innerHTML = `<span class="text-dim">${_escapeHTML((d && d.error) || "Explanation unavailable.")}</span>`;
    return;
  }
  const rel = d.reliability || null;
  const maxAbs = Math.max(...d.drivers.map(x => Math.abs(x.effect)), 1e-9);
  const rows = d.drivers.map(x => {
    const w = Math.round(48 * Math.abs(x.effect) / maxAbs);
    const side = x.toward === "Buy" ? "buy" : "sell";
    const val = x.value === null ? "" : ` <span class="text-dim">(${_escapeHTML(String(x.value))})</span>`;
    return `<div class="ex-row">
      <div class="ex-name">${_escapeHTML(x.label)}${val}</div>
      <div class="ex-bar"><span class="ex-fill ${side}" style="width:${w}%"></span></div>
      <div class="ex-share">${x.toward === "Buy" ? "&rarr; Buy" : "&rarr; Sell"} &middot; ${x.share_pct.toFixed(0)}%</div>
    </div>`;
  }).join("");
  body.innerHTML =
    (rel ? `<div class="limitation-note" style="margin-bottom:12px;"><strong>${_escapeHTML(rel.headline)}</strong>
       This panel shows what the model reacted to, not whether it is right. ${_escapeHTML(rel.caveat)}</div>` : "") +
    `<p class="text-dim" style="font-size:0.85rem;">The model's score for today is
       <strong>${d.score.toFixed(2)}</strong> (Buy minus Sell; a typical day is ${d.baseline.toFixed(2)}).
       Above zero leans Buy, below zero leans Sell, and near zero the two cancel out, which is why the signal is Hold.
       Bars show how much each input moved the score compared with ${_escapeHTML(d.compared_with)}.
       Percentages are each input's share of the total movement across all inputs; the top ${d.drivers.length} are shown.</p>` +
    `<div class="ex-list">${rows}</div>` +
    `<p class="text-dim" style="font-size:0.75rem; margin-top:8px;">${_escapeHTML(d.model_type)} model for ${_escapeHTML(d.sector)},
       data as of ${_escapeHTML(d.as_of)}. Computed with ${d.method === "tree_shap" ? "TreeSHAP" : "expected gradients (the SHAP gradient method)"}
       after market close${d.generated ? ` on ${_escapeHTML(d.generated)}` : ""}, from the same model as the signal.
       Several inputs measure nearly the same thing (for example the different moving averages), so their effects overlap.</p>`;
}

function initExplain() {
  const el = document.getElementById("explain-details");
  if (!el) return;
  let started = false;
  el.addEventListener("toggle", async () => {
    if (!el.open || started) return;
    started = true;
    try {
      const r = await fetch(`/api/explain/${encodeURIComponent(el.dataset.ticker)}`);
      _renderExplain(await r.json());
    } catch (e) {
      started = false;
      _renderExplain({ error: "Could not load the explanation. Close and reopen to retry." });
    }
  });
}
