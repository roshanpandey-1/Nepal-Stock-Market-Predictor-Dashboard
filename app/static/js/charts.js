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
