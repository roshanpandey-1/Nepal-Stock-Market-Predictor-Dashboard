// Compare stocks (/compare) and the stock screener (/screener).
// All numbers come from /api/compare and /api/screener (ml/analysis); model
// signals come from the existing /api/signal endpoint and are labelled as such.

function _rEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function _rPct(x, signed = true) {
  if (x === null || x === undefined) return '<span class="text-dim">n/a</span>';
  const cls = x > 0 ? "pos" : x < 0 ? "neg" : "";
  return `<span class="${cls}">${signed && x > 0 ? "+" : ""}${Number(x).toFixed(2)}%</span>`;
}
function _rNum(x, d = 2) {
  if (x === null || x === undefined) return '<span class="text-dim">n/a</span>';
  return Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}
function _rBig(x) {
  if (x === null || x === undefined) return '<span class="text-dim">n/a</span>';
  for (const [div, unit] of [[1e9, "arba"], [1e7, "crore"], [1e5, "lakh"]]) {
    if (Math.abs(x) >= div) return `Rs ${(x / div).toFixed(2)} ${unit}`;
  }
  return "Rs " + _rNum(x, 0);
}
function _rCss(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

// ------------------------------------------------------------------ compare
const _cmp = { tickers: [], period: "6M", chart: null, data: null };
const CMP_MAX = 5;

function _cmpColors() {
  return [_rCss("--accent"), _rCss("--green"), _rCss("--amber"), _rCss("--red"), "#8b5cf6"];
}

function _cmpSyncUrl() {
  const u = new URL(location.href);
  if (_cmp.tickers.length) u.searchParams.set("t", _cmp.tickers.join(",")); else u.searchParams.delete("t");
  u.searchParams.set("period", _cmp.period);
  history.replaceState(null, "", u);
}

function _cmpRenderChips() {
  const colors = _cmpColors();
  document.getElementById("cmp-chips").innerHTML = _cmp.tickers.map((t, i) =>
    `<span class="cmp-chip" style="border-color:${colors[i]}"><span class="dot" style="background:${colors[i]}"></span>${_rEsc(t)}
      <button type="button" aria-label="Remove ${_rEsc(t)}" data-rm="${_rEsc(t)}">×</button></span>`).join("");
  document.querySelectorAll("#cmp-chips [data-rm]").forEach((b) => b.addEventListener("click", () => {
    _cmp.tickers = _cmp.tickers.filter((t) => t !== b.dataset.rm);
    _cmpLoad();
  }));
}

function _cmpFmt(key, v) {
  if (v === null || v === undefined) return '<span class="text-dim">n/a</span>';
  if (key === "trend") return `<span class="trend-${_rEsc(v)}">${_rEsc(v)}</span>`;
  if (key === "avg_turnover_20d") return _rBig(v);
  if (["close", "support", "resistance"].includes(key)) return "Rs " + _rNum(v);
  if (key === "rsi_14") return _rNum(v, 1);
  if (key === "relative_volume") return _rNum(v) + "x";
  if (key === "vs_sector_1m") return `<span class="${v > 0 ? "pos" : v < 0 ? "neg" : ""}">${v > 0 ? "+" : ""}${Number(v).toFixed(2)}</span>`;
  if (key === "volatility_20d") return _rNum(v) + "%";
  if (["eps", "pe", "pbv"].includes(key)) return _rNum(v);
  if (key === "book_value") return "Rs " + _rNum(v);
  if (key === "cash_dividend") return _rNum(v) + "%";
  return _rPct(v);
}

function _cmpRenderChart(d) {
  const colors = _cmpColors();
  const el = document.getElementById("cmp-chart");
  if (_cmp.chart) _cmp.chart.destroy();
  if (!window.Chart) return;
  _cmp.chart = new Chart(el, {
    type: "line",
    data: {
      labels: d.chart.dates,
      datasets: d.tickers.map((t, i) => ({ label: t, data: d.chart.series[t], borderColor: colors[i],
        backgroundColor: colors[i], pointRadius: 0, borderWidth: 2, tension: 0.15 })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: _rCss("--text-dim") } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)} (${(c.parsed.y - 100).toFixed(1)}%)` } } },
      scales: { x: { ticks: { color: _rCss("--text-dim"), maxTicksLimit: 8 }, grid: { display: false } },
                y: { ticks: { color: _rCss("--text-dim") }, grid: { color: _rCss("--border") } } },
    },
  });
  const n = d.chart.dates.length;
  document.getElementById("cmp-chart-note").textContent = n
    ? `Each line starts at 100 on ${d.chart.dates[0]} and runs to ${d.chart.dates[n - 1]} (${n - 1} common trading sessions).`
    : "These stocks have no trading days in common in this period.";
}

function _cmpRenderTable(d) {
  const head = `<thead><tr><th>Measure</th>${d.tickers.map((t) =>
    `<th class="num"><a href="/stock/${encodeURIComponent(t)}">${_rEsc(t)}</a><div class="cmp-sub">${_rEsc(d.stocks[t].sector || "")}</div></th>`).join("")}</tr></thead>`;
  const rows = d.table.map((r) => {
    const vals = d.tickers.map((t) => r.values[t]).filter((v) => typeof v === "number");
    let best = null;
    if (r.better && vals.length >= 2 && new Set(vals).size > 1) best = r.better === "high" ? Math.max(...vals) : Math.min(...vals);
    return `<tr><td>${_rEsc(r.label)}</td>${d.tickers.map((t) => {
      const v = r.values[t];
      return `<td class="num${best !== null && v === best ? " cmp-best" : ""}">${_cmpFmt(r.key, v)}</td>`;
    }).join("")}</tr>`;
  }).join("");
  const sig = `<tr class="cmp-model"><td>Model signal <span class="basis-chip basis-model">Model</span></td>${d.tickers.map((t) =>
    `<td class="num" id="cmp-sig-${_rEsc(t)}"><span class="text-dim">…</span></td>`).join("")}</tr>`;
  document.getElementById("cmp-table").innerHTML = head + `<tbody>${rows}${sig}</tbody>`;
  document.getElementById("cmp-asof").textContent = d.as_of;
  d.tickers.forEach(async (t) => {
    const cell = document.getElementById(`cmp-sig-${t}`);
    try {
      const s = await (await fetch(`/api/signal/${encodeURIComponent(t)}`)).json();
      if (!s || !s.signal) { cell.innerHTML = '<span class="text-dim">n/a</span>'; return; }
      const cls = { Buy: "badge-buy", Sell: "badge-sell", Hold: "badge-hold" }[s.signal] || "badge-hold";
      const rel = s.reliability || {};
      cell.innerHTML = `<span class="badge-pill sm ${cls}${rel.level === "no_edge" ? " is-muted" : ""}">${_rEsc(s.signal)}</span>` +
        (rel.label ? `<div class="cmp-sub" title="${_rEsc(rel.caveat || "")}">${_rEsc(rel.label)}</div>` : "");
    } catch (e) { cell.innerHTML = '<span class="text-dim">n/a</span>'; }
  });
}

function _cmpRenderRel(d) {
  document.getElementById("cmp-rel").innerHTML = d.tickers.map((t) => {
    const r = d.relative[t] || { strengths: [], weaknesses: [] };
    const li = (a, cls) => a.length ? `<ul class="an-obs ${cls}">${a.map((x) => `<li>${_rEsc(x)}</li>`).join("")}</ul>` : '<p class="text-dim an-empty">None in this group.</p>';
    return `<div class="cmp-rel-card"><h4><a href="/stock/${encodeURIComponent(t)}">${_rEsc(t)}</a> <span class="cmp-sub">${_rEsc(d.stocks[t].name)}</span></h4>
      <h5 class="an-bull">Relative strengths</h5>${li(r.strengths, "bull")}
      <h5 class="an-bear">Relative weaknesses</h5>${li(r.weaknesses, "bear")}
      ${d.stocks[t].traded_on_market_date === false ? `<p class="text-dim an-note">Did not trade in the latest session; figures are from ${_rEsc(d.stocks[t].as_of)}.</p>` : ""}
      <a class="an-note" href="/stock/${encodeURIComponent(t)}">Full analysis report →</a></div>`;
  }).join("");
  document.getElementById("cmp-note").textContent = d.note;
}

async function _cmpLoad() {
  _cmpRenderChips();
  _cmpSyncUrl();
  const msg = document.getElementById("cmp-msg"), box = document.getElementById("cmp-result");
  if (_cmp.tickers.length < 2) {
    box.style.display = "none";
    msg.textContent = "Pick at least two stocks. Tip: try NABIL, NICA and GBIME.";
    return;
  }
  msg.textContent = "Loading…";
  try {
    const d = await (await fetch(`/api/compare?t=${encodeURIComponent(_cmp.tickers.join(","))}&period=${_cmp.period}`)).json();
    if (d.error) { msg.textContent = d.error; box.style.display = "none"; return; }
    if (d.missing && d.missing.length) {
      _cmp.tickers = _cmp.tickers.filter((t) => !d.missing.includes(t));
      _cmpRenderChips(); _cmpSyncUrl();
    }
    msg.textContent = d.missing && d.missing.length ? `No price history for: ${d.missing.join(", ")}.` : "";
    if (d.tickers.length < 2) { box.style.display = "none"; return; }
    box.style.display = "";
    _cmp.data = d;
    _cmpRenderChart(d); _cmpRenderTable(d); _cmpRenderRel(d);
  } catch (e) {
    msg.textContent = "The comparison could not be loaded. Please try again.";
  }
}

async function initCompare() {
  const params = new URLSearchParams(location.search);
  _cmp.tickers = (params.get("t") || "").split(",").map((t) => t.trim().toUpperCase()).filter(Boolean).slice(0, CMP_MAX);
  const p = params.get("period");
  if (["1M", "3M", "6M", "1Y"].includes(p)) _cmp.period = p;
  document.querySelectorAll("#cmp-period button").forEach((b) => {
    b.classList.toggle("active", b.dataset.p === _cmp.period);
    b.addEventListener("click", () => {
      _cmp.period = b.dataset.p;
      document.querySelectorAll("#cmp-period button").forEach((x) => x.classList.toggle("active", x === b));
      _cmpLoad();
    });
  });
  document.getElementById("cmp-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const inp = document.getElementById("cmp-input");
    const t = inp.value.trim().split(/\s|—|-/)[0].toUpperCase();
    inp.value = "";
    if (!t || _cmp.tickers.includes(t)) return;
    if (_cmp.tickers.length >= CMP_MAX) { document.getElementById("cmp-msg").textContent = `Up to ${CMP_MAX} stocks at a time.`; return; }
    _cmp.tickers.push(t);
    _cmpLoad();
  });
  try {
    const list = await (await fetch("/api/tickers")).json();
    document.getElementById("cmp-tickers").innerHTML = list.map((o) => `<option value="${_rEsc(o.t)}">${_rEsc(o.n)}</option>`).join("");
  } catch (e) { /* the input still accepts typed symbols */ }
  _cmpLoad();
}

// ------------------------------------------------------------------ screener
const _scr = { preset: "", sort: null, order: null, presets: {}, selected: new Set(), timer: null };
const SCR_COLS = [
  ["ticker", "Stock"], ["sector", "Sector"], ["close", "Close", "num"], ["change_pct", "Day", "num"],
  ["ret_1m", "1M", "num"], ["ret_3m", "3M", "num"], ["avg_turnover_20d", "Avg turnover", "num"],
  ["relative_volume", "Vol vs avg", "num"], ["rsi_14", "RSI", "num"], ["pe", "P/E", "num"], ["trend", "Trend"],
];
const SCR_EXTRA = {
  near_support: ["support_pct", "To support", "num"], near_resistance: ["resistance_pct", "To resistance", "num"],
  outperform_sector: ["vs_sector_1m", "1M vs sector", "num"], underperform_sector: ["vs_sector_1m", "1M vs sector", "num"],
  near_high: ["from_high_pct", "From 1Y high", "num"], near_low: ["from_low_pct", "From 1Y low", "num"],
};

function _scrCell(key, r) {
  const v = r[key];
  if (key === "ticker") return `<a href="/stock/${encodeURIComponent(v)}"><strong>${_rEsc(v)}</strong></a><div class="cmp-sub scr-name" title="${_rEsc(r.name)}">${_rEsc(r.name)}</div>`;
  if (key === "sector") return `<span class="text-dim">${_rEsc(v || "")}</span>`;
  if (key === "trend") return `<span class="trend-${_rEsc(v)}">${_rEsc(v)}</span>`;
  if (key === "close") return _rNum(v);
  if (key === "avg_turnover_20d") return _rBig(v);
  if (key === "relative_volume") return v == null ? '<span class="text-dim">n/a</span>' : _rNum(v, 1) + "x";
  if (key === "rsi_14") return _rNum(v, 1);
  if (key === "pe" || key === "pbv") return v == null ? '<span class="text-dim">n/a</span>' : _rNum(v, 1);
  if (key === "vs_sector_1m") return v == null ? "n/a" : `<span class="${v > 0 ? "pos" : "neg"}">${v > 0 ? "+" : ""}${Number(v).toFixed(2)} pts</span>`;
  return _rPct(v);
}

function _scrQuery() {
  const f = new FormData(document.getElementById("scr-form"));
  const q = new URLSearchParams();
  for (const [k, v] of f.entries()) if (v !== "") q.set(k, v);
  if (_scr.preset) q.set("preset", _scr.preset);
  if (_scr.sort) { q.set("sort", _scr.sort); q.set("order", _scr.order); }
  return q;
}

function _scrUpdateCompare() {
  const a = document.getElementById("scr-compare");
  const n = _scr.selected.size;
  a.style.display = n >= 2 ? "" : "none";
  a.textContent = `Compare selected (${n})`;
  a.href = "/compare?t=" + encodeURIComponent([..._scr.selected].join(","));
}

async function _scrLoad() {
  const table = document.getElementById("scr-table"), meta = document.getElementById("scr-meta");
  const q = _scrQuery();
  history.replaceState(null, "", "?" + q.toString());
  table.innerHTML = '<tbody><tr><td class="text-dim">Loading…</td></tr></tbody>';
  let d;
  try { d = await (await fetch("/api/screener?" + q.toString())).json(); }
  catch (e) { table.innerHTML = '<tbody><tr><td class="text-dim">The screener could not be loaded.</td></tr></tbody>'; return; }
  if (d.error) { table.innerHTML = `<tbody><tr><td class="text-dim">${_rEsc(d.error)}</td></tr></tbody>`; return; }
  const cols = [...SCR_COLS];
  if (SCR_EXTRA[_scr.preset]) cols.splice(2, 0, SCR_EXTRA[_scr.preset]);
  const head = `<thead><tr><th class="scr-sel"><span class="visually-hidden">Select</span></th>${cols.map(([k, label, cls]) => {
    const active = d.sort === k;
    return `<th class="${cls || ""} scr-sort${active ? " active" : ""}" data-sort="${k}" tabindex="0" role="button"
      aria-sort="${active ? (d.descending ? "descending" : "ascending") : "none"}">${_rEsc(label)}${active ? (d.descending ? " ▾" : " ▴") : ""}</th>`;
  }).join("")}</tr></thead>`;
  const body = d.rows.length ? d.rows.map((r) => `<tr><td class="scr-sel"><input type="checkbox" data-t="${_rEsc(r.ticker)}"
      ${_scr.selected.has(r.ticker) ? "checked" : ""} aria-label="Select ${_rEsc(r.ticker)} to compare"></td>
      ${cols.map(([k, , cls]) => `<td class="${cls || ""}">${_scrCell(k, r)}</td>`).join("")}</tr>`).join("")
    : `<tr><td colspan="${cols.length + 1}" class="text-dim">No stocks match these filters today.</td></tr>`;
  table.innerHTML = head + `<tbody>${body}</tbody>`;
  document.getElementById("scr-title").textContent =
    `${(_scr.presets[_scr.preset] || {}).label || "All stocks"}: ${d.count} match${d.count === 1 ? "" : "es"}`;
  meta.innerHTML = `Data as of ${_rEsc(d.as_of)}. Filters applied: ${d.applied.map((a) => _rEsc(a.replace(/\.$/, ""))).join(" · ") || "none"}.` +
    (d.count > d.rows.length ? ` Showing the first ${d.rows.length}.` : "") + ` <strong>${_rEsc(d.note)}</strong> Tick up to 5 rows to compare them.`;
  table.querySelectorAll("th.scr-sort").forEach((th) => {
    const go = () => {
      if (_scr.sort === th.dataset.sort) _scr.order = _scr.order === "desc" ? "asc" : "desc";
      else { _scr.sort = th.dataset.sort; _scr.order = th.dataset.sort === "ticker" ? "asc" : "desc"; }
      _scrLoad();
    };
    th.addEventListener("click", go);
    th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  table.querySelectorAll("input[data-t]").forEach((cb) => cb.addEventListener("change", () => {
    if (cb.checked) {
      if (_scr.selected.size >= CMP_MAX) { cb.checked = false; return; }
      _scr.selected.add(cb.dataset.t);
    } else _scr.selected.delete(cb.dataset.t);
    _scrUpdateCompare();
  }));
}

function initScreener() {
  document.querySelectorAll("#scr-presets .scr-chip").forEach((b) => {
    _scr.presets[b.dataset.preset] = { label: b.textContent.trim(), rule: b.title };
  });
  const params = new URLSearchParams(location.search);
  const form = document.getElementById("scr-form");
  for (const [k, v] of params.entries()) {
    const el = form.elements[k];
    if (!el) continue;
    if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
  }
  if (params.get("preset") in _scr.presets) _scr.preset = params.get("preset");
  if (params.get("sort")) { _scr.sort = params.get("sort"); _scr.order = params.get("order") || "desc"; }
  const setRule = () => {
    const p = _scr.presets[_scr.preset];
    document.getElementById("scr-rule").textContent = _scr.preset && p ? `Rule: ${p.rule}` : "Showing every stock that matches the filters below.";
  };
  document.querySelectorAll("#scr-presets .scr-chip").forEach((b) => {
    b.classList.toggle("active", b.dataset.preset === _scr.preset);
    b.addEventListener("click", () => {
      _scr.preset = b.dataset.preset; _scr.sort = null; _scr.order = null;
      document.querySelectorAll("#scr-presets .scr-chip").forEach((x) => x.classList.toggle("active", x === b));
      setRule(); _scrLoad();
    });
  });
  form.addEventListener("input", () => { clearTimeout(_scr.timer); _scr.timer = setTimeout(_scrLoad, 350); });
  form.addEventListener("submit", (e) => e.preventDefault());
  setRule();
  _scrLoad();
}
