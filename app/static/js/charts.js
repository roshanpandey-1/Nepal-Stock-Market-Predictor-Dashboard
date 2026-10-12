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
Chart.defaults.font.family = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

// --- Theme toggle (Light / Dark / System) ---------------------------------
// Baked-in Chart.js dataset colors (borderColor/backgroundColor strings)
// don't update themselves when CHART_COLORS changes -- only a fresh
// new Chart(...) picks up the new values. So each render*Chart function
// below registers a "redraw with current data" closure here, and switching
// themes replays whichever charts are currently on the page.
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
      plugins: { legend: { position: "top" } },
      scales: {
        x: { ticks: { autoSkip: false, maxRotation: 30, minRotation: 30 } },
        y: { title: { display: true, text: "Return (%)" } },
      },
    },
  });
  _registerThemeRedraw("backtest", () => renderBacktestChart(canvasId, rows));
}

let _sentimentChartInstance = null;

function renderSentimentChart(canvasId, dailyRows) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !dailyRows || !dailyRows.length) return;

  if (_sentimentChartInstance) {
    _sentimentChartInstance.destroy();
  }
  _sentimentChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: dailyRows.map(r => r.Date),
      datasets: [{
        label: "Avg. Daily Sentiment (FinBERT)",
        data: dailyRows.map(r => parseFloat(r.avg_sentiment)),
        borderColor: CHART_COLORS.accent,
        backgroundColor: "rgba(29,111,214,0.08)",
        fill: true,
        tension: 0.25,
        pointRadius: 2,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          title: { display: true, text: "Sentiment (-1 to 1)" },
          suggestedMin: -1,
          suggestedMax: 1,
        },
      },
    },
  });
  _registerThemeRedraw("sentiment", () => renderSentimentChart(canvasId, dailyRows));
}

let _priceChartInstance = null;
let _priceChartFullHistory = [];

// ShareHub-style crosshair: a dashed vertical + horizontal line through the
// hovered point, plus a small value badge on the y-axis. Chart.js has no
// built-in crosshair, so this is a small custom plugin rather than pulling
// in an extra dependency.
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
        chart.data.datasets[0].data[point.$context.dataIndex] <
        chart.data.datasets[0].data[point.$context.dataIndex - 1];
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
        x: { ticks: { maxTicksLimit: 10 } },
        y: { title: { display: true, text: "Price (NPR)" } },
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
  badge.innerHTML = `<span class="badge-pill ${cls}">${signalData.signal}</span>`;
  if (conf) {
    conf.textContent = `Confidence: ${(signalData.confidence * 100).toFixed(1)}%  ·  ${signalData.note || ""}`;
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
  return `<div class="breadth-row mt-2">
    <div class="breadth-pill adv"><span class="n">${b.advancing}</span>Advancing</div>
    <div class="breadth-pill dec"><span class="n">${b.declining}</span>Declining</div>
    <div class="breadth-pill unc"><span class="n">${b.unchanged}</span>Unchanged</div>
  </div>`;
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

function _renderTopTurnover(rows) {
  const panel = document.getElementById("turnover-panel");
  const body = document.getElementById("turnover-body");
  if (!panel || !body) return;
  if (!rows || !rows.length) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "";
  body.innerHTML = `<table class="data-table">
    <thead><tr><th>Symbol</th><th>LTP</th><th>Change</th><th>Turnover</th></tr></thead>
    <tbody>${rows.map(r => {
      const up = (r.change_pct ?? 0) >= 0;
      const cls = up ? "pos" : "neg";
      const sign = up ? "+" : "";
      const pct = r.change_pct == null ? "—" : `${sign}${r.change_pct}%`;
      const cr = (r.turnover / 10000000).toFixed(2); // paisa-free Rs -> Cr, matches ShareHub's "Cr" unit
      const title = r.name ? ` title="${r.name.replace(/"/g, "&quot;")}"` : "";
      return `<tr>
        <td${title}><a href="/stock/${encodeURIComponent(r.ticker)}">${r.ticker}</a></td>
        <td>${r.ltp}</td>
        <td class="${cls}">${pct}</td>
        <td>Rs ${cr} Cr</td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;
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
  _renderTopTurnover(data.top_turnover);
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
    chgEl.textContent = [chg, pct].filter(Boolean).join("  ");
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
  const shown = pct == null ? "—" : `${sign}${pct}%`;
  const title = m.name ? ` title="${m.name.replace(/"/g, "&quot;")}"` : "";
  return `<tr>
    <td${title}><a href="/stock/${encodeURIComponent(m.ticker)}">${m.ticker}</a></td>
    <td>${m.ltp}</td>
    <td class="${cls}">${shown}</td>
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
    srcEl.className = "src-badge " + (data.stale ? "stale" : "live");
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

function renderLiveIndexChart(rawSeries, indexInfo) {
  const wrap = document.getElementById("live-chart-wrap");
  const ctx = document.getElementById("live-index-chart");
  if (!wrap || !ctx) return;

  if (!rawSeries || rawSeries.length < 2) {
    wrap.style.display = "none";
    return;
  }
  const series = _trimTrailingFlat(rawSeries);
  wrap.style.display = "";

  // Colour the curve by the day's direction, like ShareHub does.
  const down = (indexInfo && indexInfo.change_pct != null)
    ? indexInfo.change_pct < 0
    : series[series.length - 1].v < series[0].v;
  const line = down ? CHART_COLORS.red : CHART_COLORS.green;
  const fill = down ? "rgba(220,38,38,0.10)" : "rgba(22,163,74,0.10)";

  if (_liveIndexChart) _liveIndexChart.destroy();

  _liveIndexChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: series.map(p => _nptTime(p.t)),
      datasets: [{
        label: "NEPSE Index",
        data: series.map(p => p.v),
        borderColor: line,
        backgroundColor: fill,
        borderWidth: 1.5,
        fill: true,
        tension: 0.1,
        pointRadius: 0,
        pointHitRadius: 10,
      }],
    },
    options: {
      responsive: true,
      animation: false,          // avoid a redraw flicker on each 60s poll
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => `Index  ${item.parsed.y.toFixed(2)}`,
          },
        },
      },
      scales: {
        x: { ticks: { maxTicksLimit: 6, autoSkip: true } },
        y: { position: "right", ticks: { maxTicksLimit: 6 } },
      },
    },
    plugins: [crosshairPlugin],
  });
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
      const pts = r.change == null ? "" : ` <span class="text-dim">(${sign}${r.change})</span>`;
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

// --- Navbar ticker search ---------------------------------------------------
// A custom autocomplete rather than a native <datalist>: browsers dump every
// option on focus, which meant all 260 tickers appeared before typing a
// character. This only renders after input and caps the list.

const NAV_SEARCH_LIMIT = 8;
let _tickerIndex = null;      // [{t, n}], fetched once
let _tickerIndexPromise = null;
let _navSearchActive = -1;    // highlighted row for keyboard nav

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
  const starts = [], contains = [];
  for (const row of _tickerIndex) {
    const t = row.t.toLowerCase();
    const n = (row.n || "").toLowerCase();
    if (t.startsWith(q) || n.startsWith(q)) starts.push(row);
    else if (t.includes(q) || n.includes(q)) contains.push(row);
    if (starts.length >= NAV_SEARCH_LIMIT) break;
  }
  return starts.concat(contains).slice(0, NAV_SEARCH_LIMIT);
}

function _escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, ch => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function _renderNavResults(rows) {
  const box = document.getElementById("nav-search-results");
  const input = document.getElementById("nav-search-input");
  if (!box) return;

  if (!rows.length) {
    box.innerHTML = "";
    box.classList.remove("open");
    if (input) input.setAttribute("aria-expanded", "false");
    return;
  }
  box.innerHTML = rows.map((r, i) => `
    <div class="nav-search-item${i === _navSearchActive ? " active" : ""}"
         role="option" data-ticker="${_escapeHTML(r.t)}" data-index="${i}">
      <span class="sym">${_escapeHTML(r.t)}</span>
      <span class="nm">${_escapeHTML(r.n || "")}</span>
    </div>`).join("");
  box.classList.add("open");
  if (input) input.setAttribute("aria-expanded", "true");
}

function _closeNavResults() {
  const box = document.getElementById("nav-search-results");
  const input = document.getElementById("nav-search-input");
  _navSearchActive = -1;
  if (box) { box.innerHTML = ""; box.classList.remove("open"); }
  if (input) input.setAttribute("aria-expanded", "false");
}

function _gotoTicker(ticker) {
  if (ticker) window.location = `/stock/${encodeURIComponent(ticker)}`;
}

function wireNavSearch() {
  const form = document.getElementById("nav-search-form");
  const input = document.getElementById("nav-search-input");
  const box = document.getElementById("nav-search-results");
  if (!form || !input || !box) return;

  // warm the index on focus so the first keystroke already has data
  input.addEventListener("focus", _loadTickerIndex);

  input.addEventListener("input", async () => {
    await _loadTickerIndex();
    _navSearchActive = -1;
    _renderNavResults(_matchTickers(input.value));
  });

  input.addEventListener("keydown", (e) => {
    const rows = box.querySelectorAll(".nav-search-item");
    if (e.key === "ArrowDown" && rows.length) {
      e.preventDefault();
      _navSearchActive = Math.min(_navSearchActive + 1, rows.length - 1);
      _renderNavResults(_matchTickers(input.value));
    } else if (e.key === "ArrowUp" && rows.length) {
      e.preventDefault();
      _navSearchActive = Math.max(_navSearchActive - 1, 0);
      _renderNavResults(_matchTickers(input.value));
    } else if (e.key === "Escape") {
      _closeNavResults();
    }
  });

  box.addEventListener("mousedown", (e) => {
    // mousedown, not click -- blur would close the list first
    const item = e.target.closest(".nav-search-item");
    if (item) { e.preventDefault(); _gotoTicker(item.dataset.ticker); }
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const matches = _matchTickers(input.value);
    if (_navSearchActive >= 0 && matches[_navSearchActive]) {
      _gotoTicker(matches[_navSearchActive].t);
    } else if (matches.length) {
      _gotoTicker(matches[0].t);          // best match on plain Enter
    } else if (input.value.trim()) {
      _gotoTicker(input.value.trim().toUpperCase());
    }
  });

  document.addEventListener("click", (e) => {
    if (!form.contains(e.target)) _closeNavResults();
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
  return {
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
        activecolor: c.accent,
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
      name: "Forecast", mode: "lines",
      line: { color: c.red, width: 2, dash: "dash" },
      hovertemplate: "<b>%{x}</b><br>Forecast: Rs. %{y:.1f}<extra></extra>",
    },
    {
      x: days.map(d => d.date), y: days.map(d => d.upper_bound),
      name: "Upper Bound", mode: "lines",
      line: { width: 0 }, showlegend: false,
      hovertemplate: "Upper: Rs. %{y:.1f}<extra></extra>",
    },
    {
      x: days.map(d => d.date), y: days.map(d => d.lower_bound),
      name: "Confidence Interval", mode: "lines",
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
      metaEl.textContent = `Snapshot price at forecast time: Rs. ${fc.current_price} `
        + `(forecast generated ${fc.generated_at}, based on ${fc.rows_used} days of history).`;
    }
  } catch (e) {
    panel.style.display = "none";
  }
}
