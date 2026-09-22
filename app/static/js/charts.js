// Shared Chart.js helpers for the NEPSE Intelligence dashboard.
// Colors are kept minimal and readable against the dark theme in main.css.

const CHART_COLORS = {
  accent: "#4f8cff",
  green: "#22c55e",
  red: "#ef4444",
  amber: "#f5a623",
  grid: "rgba(255,255,255,0.06)",
  text: "#9aa2b1",
};

Chart.defaults.color = CHART_COLORS.text;
Chart.defaults.borderColor = CHART_COLORS.grid;
Chart.defaults.font.family = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

function renderBacktestChart(canvasId, rows) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !rows || !rows.length) return;

  new Chart(ctx, {
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
}

function renderSentimentChart(canvasId, dailyRows) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !dailyRows || !dailyRows.length) return;

  new Chart(ctx, {
    type: "line",
    data: {
      labels: dailyRows.map(r => r.Date),
      datasets: [{
        label: "Avg. Daily Sentiment (FinBERT)",
        data: dailyRows.map(r => parseFloat(r.avg_sentiment)),
        borderColor: CHART_COLORS.accent,
        backgroundColor: "rgba(79,140,255,0.12)",
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
}

function renderPriceChart(canvasId, history) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !history || !history.length) return;

  new Chart(ctx, {
    type: "line",
    data: {
      labels: history.map(h => h.date),
      datasets: [{
        label: "Close Price",
        data: history.map(h => h.close),
        borderColor: CHART_COLORS.accent,
        backgroundColor: "rgba(79,140,255,0.10)",
        fill: true,
        tension: 0.15,
        pointRadius: 0,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 10 } },
        y: { title: { display: true, text: "Price (NPR)" } },
      },
    },
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
  try {
    const histResp = await fetch(`/api/forecast/${ticker}`);
    const histData = await histResp.json();
    renderPriceChart("price-chart", histData.history);
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
