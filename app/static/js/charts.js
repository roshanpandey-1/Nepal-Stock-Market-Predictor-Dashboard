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
  return {
    accent: get("--accent", "#1d6fd6"),
    green: get("--green", "#22c55e"),
    red: get("--red", "#ef4444"),
    amber: get("--amber", "#f5a623"),
    grid: get("--border", "rgba(11,46,79,0.08)"),
    text: get("--text-dim", "#6b7686"),
  };
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

  if (data.index) {
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
}

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
