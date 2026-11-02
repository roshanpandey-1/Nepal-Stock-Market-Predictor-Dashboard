// Stock analysis report (stock page). Data comes from /api/analysis/<ticker>,
// which is built by ml/analysis from the daily price files using fixed rules --
// no language model. The model section reuses the signal charts.js already
// fetched (the "signal:loaded" event), so the model is not run twice.

const _an = { report: null, signal: undefined };

document.addEventListener("signal:loaded", (e) => {
  _an.signal = e.detail;
  _renderModelSection();
});

function _anEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const _BASIS = {
  data: ["Data", "Read directly from the daily price files"],
  calculated: ["Calculated", "Computed from the data by a stated formula"],
  rules: ["Rule-based reading", "Written by fixed rules from the calculated values; not a forecast"],
  model: ["Model output", "From the sector's machine-learning model"],
};

function _basisChip(basis) {
  const b = _BASIS[basis] || [basis, ""];
  return `<span class="basis-chip basis-${_anEsc(basis)}" title="${_anEsc(b[1])}">${_anEsc(b[0])}</span>`;
}

function _anPct(x) {
  if (x === null || x === undefined) return "n/a";
  return `${x > 0 ? "+" : ""}${Number(x).toFixed(2)}%`;
}

function _anRs(x) {
  if (x === null || x === undefined) return "n/a";
  return "Rs " + Number(x).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _anSection(sec, inner, extraClass = "") {
  return `<section class="an-sec ${extraClass}">
    <div class="an-sec-head"><h4>${_anEsc(sec.title)}</h4>${_basisChip(sec.basis)}</div>${inner}</section>`;
}

function _anLines(lines) {
  return `<ul class="an-lines">${(lines || []).map((l) => `<li>${_anEsc(l)}</li>`).join("")}</ul>`;
}

function _anObs(items, cls, empty) {
  if (!items || !items.length) return `<p class="text-dim an-empty">${_anEsc(empty)}</p>`;
  return `<ul class="an-obs ${cls}">${items.map((o) =>
    `<li><span>${_anEsc(o.text)}</span><span class="an-rule" title="Rule">${_anEsc(o.rule)}</span></li>`).join("")}</ul>`;
}

function _anLevelRows(list, kind) {
  return list.map((l) => `<tr><td><span class="an-lvl an-lvl-${kind}">${kind === "s" ? "Support" : "Resistance"}</span></td>
    <td class="num">${_anRs(l.level)}</td><td class="num">${_anPct(l.distance_pct)}</td>
    <td class="num">${l.touches}</td><td class="num">${_anEsc(l.last_touch)}</td></tr>`).join("");
}

function _renderModelSection() {
  const el = document.getElementById("an-model");
  if (!el || !_an.report) return;
  const m = _an.report.model || {};
  const s = _an.signal;
  let body;
  if (_an.signal === undefined) {
    body = `<p class="text-dim">Loading the model signal…</p>`;
  } else if (!s || s.error || !s.signal) {
    body = `<p class="text-dim">No model signal is available for this stock${s && s.error ? ` (${_anEsc(s.error)})` : ""}.</p>`;
  } else {
    const p = s.probabilities || {};
    const probs = ["Buy", "Hold", "Sell"].filter((k) => k in p).map((k) => `${k} ${(p[k] * 100).toFixed(0)}%`).join(" · ");
    const rel = s.reliability || {};
    const lines = [
      `Signal: <strong>${_anEsc(s.signal)}</strong> from the ${_anEsc(s.sector || "")} sector ${_anEsc(m.type || "")} model, using daily data up to ${_anEsc(m.data_up_to)} (for the next session).`,
      probs ? `Model probabilities: ${_anEsc(probs)}. These are the model's own scores, not calibrated odds.` : "",
      rel.label ? `Reliability on unseen data: <span class="rel-chip lvl-${_anEsc(rel.level)}">${_anEsc(rel.label)}</span> ${_anEsc(rel.headline || "")} ${_anEsc(rel.caveat || "")}` : "",
      m.evidence && m.evidence.headline ? `Across all sectors (tested ${_anEsc(m.evidence.generated)}): ${_anEsc(m.evidence.headline)} <a href="/backtest">See the tests</a>.` : "",
    ].filter(Boolean);
    body = `<ul class="an-lines">${lines.map((l) => `<li>${l}</li>`).join("")}</ul>`;
  }
  el.innerHTML = `<div class="an-sec-head"><h4>Model outlook</h4>${_basisChip("model")}</div>${body}`;
}

function renderAnalysis(data) {
  const box = document.getElementById("analysis-body");
  if (!box) return;
  if (!data || data.error || !data.report) {
    box.innerHTML = `<p class="text-dim">${_anEsc((data && data.error) || "The analysis report is unavailable right now.")}</p>`;
    return;
  }
  const r = data.report, S = r.sections;
  _an.report = r;

  const sum = S.summary;
  const toneCls = { "mostly positive": "pos", "mostly negative": "neg" }[sum.tone] || "mixed";
  const summaryHTML = `<div class="an-summary tone-${toneCls}">
      <div class="an-sec-head"><h4>Summary</h4>${_basisChip("rules")}</div>
      <p>${_anEsc(sum.text)}</p></div>`;

  const techRows = (S.technical.rows || []).map((x) =>
    `<tr><td>${_anEsc(x.indicator)}</td><td class="num">${_anEsc(x.value)}</td><td>${_anEsc(x.reading)}</td></tr>`).join("");
  const tech = _anSection(S.technical, `<div class="table-scroll"><table class="data-table an-table an-tech">
      <thead><tr><th>Indicator</th><th class="num">Value</th><th>Reading</th></tr></thead><tbody>${techRows}</tbody></table></div>`);

  const sig = S.signals;
  const signals = _anSection(sig, `<div class="an-cols">
      <div><h5 class="an-bull">Bullish</h5>${_anObs(sig.bullish, "bull", "None of the bullish rules fired.")}</div>
      <div><h5 class="an-bear">Bearish</h5>${_anObs(sig.bearish, "bear", "None of the bearish rules fired.")}</div>
      <div><h5 class="an-caut">Watch</h5>${_anObs(sig.caution, "caut", "Nothing flagged.")}</div></div>`);

  const L = S.levels;
  const refRows = (L.reference || []).map((x) => `<tr><td>${_anEsc(x.label)}</td><td class="num">${_anRs(x.level)}</td>
      <td class="num">${_anPct(x.distance_pct)}</td><td></td><td></td></tr>`).join("");
  const levelRows = _anLevelRows([...(L.resistance || [])].reverse(), "r") +
    `<tr class="an-now"><td>Last close</td><td class="num">${_anRs(data.snapshot.price.close)}</td><td></td><td></td><td></td></tr>` +
    _anLevelRows(L.support || [], "s");
  const levels = _anSection(L, `<div class="table-scroll"><table class="data-table an-table">
      <thead><tr><th>Level</th><th class="num">Price</th><th class="num">From close</th><th class="num">Touches</th><th class="num">Last touch</th></tr></thead>
      <tbody>${levelRows}${refRows}</tbody></table></div>
      <p class="text-dim an-note">Method: ${_anEsc(L.method || "not enough data")}. Levels are where price turned before; they can break.</p>`);

  box.innerHTML = `
    <p class="text-dim an-asof">Data as of <strong>${_anEsc(r.as_of)}</strong> (latest completed session${r.market_date && r.market_date !== r.as_of ? `; market's latest is ${_anEsc(r.market_date)}` : ""}).
      Source: ${_anEsc(r.source)}.</p>
    ${summaryHTML}
    <div class="an-grid">
      ${_anSection(S.overview, _anLines(S.overview.lines))}
      ${_anSection(S.trend, _anLines(S.trend.lines) + `<p class="text-dim an-note">Rule: ${_anEsc(S.trend.rule)}</p>`)}
    </div>
    ${tech}
    ${signals}
    ${levels}
    <div class="an-grid">
      ${_anSection(S.risk, _anLines(S.risk.lines))}
      <section class="an-sec" id="an-model"></section>
    </div>
    <p class="an-disclaimer">${_anEsc(sum.disclaimer)}</p>`;
  _renderModelSection();
}

async function initAnalysis(ticker) {
  const box = document.getElementById("analysis-body");
  if (!box) return;
  try {
    const resp = await fetch(`/api/analysis/${encodeURIComponent(ticker)}`);
    renderAnalysis(await resp.json());
  } catch (e) {
    console.error("Failed to load analysis", e);
    renderAnalysis(null);
  }
}
